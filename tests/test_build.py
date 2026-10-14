"""Engine contracts use fake PyInstaller processes; controlled children test cleanup."""

from __future__ import annotations

import ast
import io
import json
import os
import plistlib
import queue
import struct
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import pyforge.build as build_module
from pyforge.build import (
    MAX_LOG_LINE_CHARS,
    MAX_LOG_LINES,
    ArtifactError,
    BuildEngine,
    BuildEvent,
    BuildResult,
    _read_output,
    _terminate_process_tree,
    _write_linux_metadata,
    _write_spec,
    verify_artifact,
)
from pyforge.config import BuildConfig
from pyforge.dependencies import DependencyReport
from pyforge.diagnostics import Diagnostic, DoctorReport
from pyforge.platform import host_target


@pytest.fixture
def config(tmp_path: Path) -> BuildConfig:
    script = tmp_path / "project with spaces" / "main.py"
    script.parent.mkdir()
    script.write_text("print('reviewed example')\n", encoding="utf-8")
    return BuildConfig(script, tmp_path / "output", "Demo", target=host_target())


def elf_bytes() -> bytes:
    result = bytearray(64)
    result[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<H", result, 16, 2)
    struct.pack_into("<H", result, 18, 62)
    struct.pack_into("<H", result, 52, 64)
    return bytes(result)


def pe_bytes() -> bytes:
    result = bytearray(256)
    result[:2] = b"MZ"
    struct.pack_into("<I", result, 60, 64)
    result[64:68] = b"PE\x00\x00"
    struct.pack_into("<H", result, 86, 2)
    struct.pack_into("<H", result, 88, 0x20B)
    return bytes(result)


def macho_bytes() -> bytes:
    result = bytearray(32)
    result[:4] = b"\xcf\xfa\xed\xfe"
    struct.pack_into("<I", result, 12, 2)
    return bytes(result)


def create_artifact(config: BuildConfig, dist: Path) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    if config.target == "macos" and not config.console:
        artifact = dist / (config.name + ".app")
        contents = artifact / "Contents"
        for directory in ("MacOS", "Frameworks", "Resources"):
            (contents / directory).mkdir(parents=True)
        info = {
            "CFBundleExecutable": config.name,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": config.version,
            "CFBundleVersion": config.version,
            "CFBundleGetInfoString": config.description,
            "CFBundleIdentifier": config.bundle_identifier,
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        executable = contents / "MacOS" / config.name
    elif config.mode == "onedir":
        artifact = dist / config.name
        (artifact / "_internal").mkdir(parents=True)
        executable = artifact / (config.name + (".exe" if config.target == "windows" else ""))
    else:
        artifact = dist / (config.name + (".exe" if config.target == "windows" else ""))
        executable = artifact
    executable.write_bytes(
        {"linux": elf_bytes(), "windows": pe_bytes(), "macos": macho_bytes()}[config.target]
    )
    executable.chmod(0o755)
    return artifact


class FakeProcess:
    pid = 987654321

    def __init__(self, output: bytes = b"PyInstaller finished\n", returncode: int = 0) -> None:
        self.stdout = io.BytesIO(output)
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


@pytest.fixture
def fake_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        build_module, "run_doctor", lambda _: DoctorReport([], DependencyReport([], [], 1))
    )
    monkeypatch.setattr(
        build_module,
        "_WindowsJob",
        lambda _: SimpleNamespace(terminate=lambda: None, close=lambda: None),
    )
    monkeypatch.setattr(
        build_module,
        "_windows_version_strings",
        lambda _: {
            "FileVersion": "1.0.0",
            "ProductVersion": "1.0.0",
            "FileDescription": "",
            "ProductName": "Demo",
        },
    )


def test_trust_required_without_any_build_or_files(
    config: BuildConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: pytest.fail("process must not start"))
    for trust in (False, None, 1, "yes"):
        result = BuildEngine().build(config, trusted=trust)
        assert result.status == "untrusted" and not result.success
    assert not config.output_dir.exists()


def test_prelaunch_cancellation_is_sticky(
    config: BuildConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: pytest.fail("process must not start"))
    engine = BuildEngine()
    engine.cancel()
    assert engine.build(config, trusted=True).status == "cancelled"
    assert engine.build(config, trusted=True).status == "cancelled"
    assert not config.output_dir.exists()
    engine.reset_cancellation()
    assert not engine._cancelled.is_set()


def test_active_engine_rejects_concurrent_use_and_reset(config: BuildConfig) -> None:
    engine = BuildEngine()
    engine._active.acquire()
    try:
        assert engine.build(config, trusted=True).status == "busy"
        with pytest.raises(RuntimeError):
            engine.reset_cancellation()
    finally:
        engine._active.release()


def test_invalid_config_does_not_launch(
    config: BuildConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: pytest.fail("process must not start"))
    result = BuildEngine().build(replace(config, name="Invalid."), trusted=True)
    assert result.status == "invalid"
    assert not config.output_dir.exists()


def test_preflight_failure_is_actionable(
    config: BuildConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagnostic = Diagnostic(
        "error", "missing", "PyInstaller missing", "Install reviewed build extra"
    )
    monkeypatch.setattr(
        build_module,
        "run_doctor",
        lambda _: DoctorReport([diagnostic], DependencyReport([], [], 1)),
    )
    result = BuildEngine().build(config, trusted=True)
    assert result.status == "preflight_failed"
    assert "Install reviewed" in result.errors[0]
    assert not config.output_dir.exists()


def test_success_uses_isolated_interpreter_argv_and_unique_runs(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches = []
    events: list[BuildEvent] = []
    original_project = {path.name: path.read_bytes() for path in config.script.parent.iterdir()}

    def launch(command: tuple[str, ...], **options: object) -> FakeProcess:
        launches.append((command, options))
        assert command[:4] == (sys.executable, "-I", "-m", "PyInstaller")
        assert options["shell"] is False and Path(options["cwd"]) != config.script.parent
        assert options["stdin"] == subprocess.DEVNULL
        assert options["start_new_session"] is (os.name != "nt")
        assert "PYTHONPATH" not in options["env"] and "PYTHONHOME" not in options["env"]
        assert Path(options["env"]["PYINSTALLER_CONFIG_DIR"]).parent == options["cwd"]
        spec = Path(command[-1])
        assert spec.parent == options["cwd"]
        ast.parse(spec.read_text(encoding="utf-8"))
        dist = Path(command[command.index("--distpath") + 1])
        create_artifact(config, dist)
        return FakeProcess()

    monkeypatch.setenv("PYTHONPATH", str(config.script.parent))
    monkeypatch.setenv("PYTHONHOME", str(config.script.parent))
    monkeypatch.setattr(subprocess, "Popen", launch)
    first = BuildEngine().build(config, trusted=True, on_event=events.append)
    second = BuildEngine().build(config, trusted=True)
    assert first.success and second.success
    assert first.artifact and first.artifact.exists()
    assert first.run_dir != second.run_dir
    assert (
        first.report_path and json.loads(first.report_path.read_text(encoding="utf-8"))["success"]
    )
    assert first.logs == ("PyInstaller finished",)
    assert events[-1] == BuildEvent("finished", "success", 100)
    for command, options in launches:
        assert not Path(options["cwd"]).exists()
        assert not Path(command[command.index("--workpath") + 1]).exists()
    assert {
        path.name: path.read_bytes() for path in config.script.parent.iterdir()
    } == original_project


def test_process_failure_keeps_report_logs_and_recovery(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_, **__: FakeProcess(b"ModuleNotFoundError: No module named 'plugin'\n", 1),
    )
    result = BuildEngine().build(config, trusted=True)
    assert result.status == "failed" and result.returncode == 1
    assert any("hidden import" in error for error in result.errors)
    assert result.report_path and result.report_path.is_file()


def test_zero_exit_without_artifact_fails_verification(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: FakeProcess())
    result = BuildEngine().build(config, trusted=True)
    assert not result.success and result.status == "failed"
    assert any("Expected" in error for error in result.errors)


def test_launch_failure_has_structured_report(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failure(*_: object, **__: object) -> None:
        raise OSError("simulated process launch failure")

    monkeypatch.setattr(subprocess, "Popen", failure)
    result = BuildEngine().build(config, trusted=True)
    assert result.status == "failed" and "launch failure" in result.errors[0]
    assert result.report_path and result.report_path.exists()


def test_callback_failure_does_not_break_cleanup(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: FakeProcess(returncode=1))

    def callback(_: BuildEvent) -> None:
        raise RuntimeError("UI unavailable")

    assert BuildEngine().build(config, trusted=True, on_event=callback).status == "failed"


@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled", "exception"])
def test_owned_tree_cleanup_precedes_temporary_directory_cleanup(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    events: list[str] = []
    original_temporary_directory = build_module.tempfile.TemporaryDirectory

    class RecordingDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.actual = original_temporary_directory(*args, **kwargs)

        def __enter__(self) -> str:
            return self.actual.__enter__()

        def __exit__(self, *args: object) -> None:
            events.append("temporary_cleanup")
            assert "tree_cleanup" in events
            self.actual.__exit__(*args)

    class RecordingJob:
        def __init__(self, process: object) -> None:
            pass

        def terminate(self) -> None:
            events.append("tree_terminate")

        def close(self) -> None:
            events.append("tree_cleanup")

    monkeypatch.setattr(build_module.tempfile, "TemporaryDirectory", RecordingDirectory)
    monkeypatch.setattr(build_module, "_WindowsJob", RecordingJob)
    if os.name != "nt":
        monkeypatch.setattr(os, "killpg", lambda *args: events.append("tree_cleanup"))

    def launch(command: tuple[str, ...], **options: object) -> FakeProcess:
        create_artifact(config, Path(command[command.index("--distpath") + 1]))
        return FakeProcess(returncode=1 if outcome == "failed" else 0)

    monkeypatch.setattr(subprocess, "Popen", launch)
    if outcome == "exception":

        def fail_verification(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated unexpected verification failure")

        monkeypatch.setattr(build_module, "verify_artifact", fail_verification)
    engine = BuildEngine()

    def on_event(event: BuildEvent) -> None:
        if outcome == "cancelled" and event.kind == "log":
            engine.cancel()
        if event.kind == "finished":
            events.append("finished")

    result = engine.build(config, trusted=True, on_event=on_event)
    assert result.status == ("failed" if outcome == "exception" else outcome)
    assert events.index("tree_cleanup") < events.index("temporary_cleanup")
    assert events.index("tree_cleanup") < events.index("finished")


def test_logs_are_bounded_and_newest_pending_lines_survive() -> None:
    pending: queue.Queue[str] = queue.Queue(maxsize=10)
    dropped = [0]
    stream = io.BytesIO(("x" * 10000 + "\n" + "\n".join(f"line {i}" for i in range(1000))).encode())
    _read_output(stream, pending, threading.Event(), dropped)
    retained = list(pending.queue)
    assert len(retained) == 10 and retained[-1] == "line 999"
    assert max(map(len, retained)) <= MAX_LOG_LINE_CHARS
    assert dropped[0] > 0


def test_report_json_is_serializable_and_bounded() -> None:
    result = BuildResult(
        False, "failed", run_dir=Path("output"), logs=tuple("line" for _ in range(MAX_LOG_LINES))
    )
    data = json.loads(json.dumps(result.to_dict()))
    assert data["run_dir"] == "output" and data["schema_version"] == 1


@pytest.mark.parametrize("target", ["windows", "macos", "linux"])
@pytest.mark.parametrize("mode", ["onefile", "onedir"])
def test_native_headers_and_layout(
    config: BuildConfig, tmp_path: Path, target: str, mode: str
) -> None:
    candidate = replace(config, target=target, mode=mode)
    artifact = create_artifact(candidate, tmp_path / "dist")
    assert verify_artifact(candidate, tmp_path / "dist", verify_metadata=False) == artifact


@pytest.mark.parametrize("target", ["windows", "macos", "linux"])
def test_renamed_python_is_not_a_native_binary(
    config: BuildConfig, tmp_path: Path, target: str
) -> None:
    candidate = replace(config, target=target, mode="onefile")
    artifact = create_artifact(candidate, tmp_path / "dist")
    artifact.write_bytes(b"#!/usr/bin/python\nprint('not a binary')\n")
    with pytest.raises(ArtifactError, match="executable header"):
        verify_artifact(candidate, tmp_path / "dist", verify_metadata=False)


def test_onedir_requires_internal_dependencies(config: BuildConfig, tmp_path: Path) -> None:
    candidate = replace(config, target="linux")
    artifact = create_artifact(candidate, tmp_path / "dist")
    (artifact / "_internal").rmdir()
    with pytest.raises(ArtifactError, match="_internal"):
        verify_artifact(candidate, tmp_path / "dist")


def test_macos_app_metadata_verified(config: BuildConfig, tmp_path: Path) -> None:
    candidate = replace(
        config,
        target="macos",
        console=False,
        version="2.3.4",
        description="App description",
        bundle_identifier="org.example.demo",
    )
    artifact = create_artifact(candidate, tmp_path / "dist")
    assert verify_artifact(candidate, tmp_path / "dist") == artifact
    with pytest.raises(ArtifactError, match="metadata"):
        verify_artifact(replace(candidate, version="9.9.9"), tmp_path / "dist")


def test_mac_universal_header_checks_every_slice(config: BuildConfig, tmp_path: Path) -> None:
    candidate = replace(config, target="macos", mode="onefile")
    artifact = create_artifact(candidate, tmp_path / "dist")
    header = struct.pack(">II", 0xCAFEBABE, 1) + struct.pack(">IIIII", 0x01000007, 3, 28, 32, 0)
    artifact.write_bytes(header + macho_bytes())
    assert verify_artifact(candidate, tmp_path / "dist") == artifact
    artifact.write_bytes(header + b"not a Mach-O executable".ljust(32, b"\x00"))
    with pytest.raises(ArtifactError):
        verify_artifact(candidate, tmp_path / "dist")


def test_generated_spec_preserves_literals_and_real_metadata(
    config: BuildConfig, tmp_path: Path
) -> None:
    for target in ("windows", "macos", "linux"):
        candidate = replace(
            config,
            target=target,
            console=False,
            version="2.3.4",
            description="quoted ' \" \\ café\nline",
            hidden_imports=("pkg.plugin",),
        )
        spec = _write_spec(candidate, tmp_path)
        tree = ast.parse(spec.read_text(encoding="utf-8"))
        assert tree
        if target == "windows":
            assert repr(candidate.description) in (tmp_path / "windows-version.txt").read_text(
                encoding="utf-8"
            )
        if target == "macos":
            assert "CFBundleGetInfoString" in spec.read_text(encoding="utf-8")
            assert "CFBundleVersion" in spec.read_text(encoding="utf-8")


def test_linux_desktop_metadata_escapes_description(config: BuildConfig, tmp_path: Path) -> None:
    candidate = replace(config, target="linux", mode="onefile", description="first\nExec=bad\tlast")
    artifact = create_artifact(candidate, tmp_path / "dist")
    assert _write_linux_metadata(candidate, artifact) is None
    desktop = (artifact.parent / "Demo.desktop").read_text(encoding="utf-8")
    assert "Comment=first\\nExec=bad\\tlast" in desktop
    assert desktop.count("\nExec=") == 1
    assert (
        json.loads(
            (artifact.parent / ".pyforge" / "app-metadata.json").read_text(encoding="utf-8")
        )["description"]
        == candidate.description
    )


@pytest.mark.skipif(os.name == "nt", reason="Windows filenames disallow these characters")
def test_linux_desktop_exec_two_layer_escaping(config: BuildConfig, tmp_path: Path) -> None:
    candidate = replace(config, target="linux", mode="onefile")
    artifact = create_artifact(candidate, tmp_path / 'space \\ "$` %' / "dist")
    assert _write_linux_metadata(candidate, artifact) is None
    desktop = (artifact.parent / "Demo.desktop").read_text(encoding="utf-8")
    assert "\\\\\\\\" in desktop and "\\\\$" in desktop and "%%" in desktop and '\\\\"' in desktop


@pytest.mark.skipif(os.name == "nt", reason="Windows filenames disallow newline")
@pytest.mark.parametrize("folder", ["bad\npath", "path=invalid", "café"])
def test_linux_unrepresentable_launcher_path_is_omitted(
    config: BuildConfig, tmp_path: Path, folder: str
) -> None:
    candidate = replace(config, target="linux", mode="onefile")
    artifact = create_artifact(candidate, tmp_path / folder / "dist")
    assert "launcher omitted" in _write_linux_metadata(candidate, artifact).lower()
    assert not (artifact.parent / "Demo.desktop").exists()
    assert (artifact.parent / ".pyforge" / "app-metadata.json").exists()


@pytest.mark.parametrize("mode", ["onedir", "onefile"])
@pytest.mark.parametrize("name", ["pyforge-metadata.json", "app-metadata.json", "icon.png"])
def test_linux_metadata_never_overwrites_executable(
    config: BuildConfig, tmp_path: Path, mode: str, name: str
) -> None:
    candidate = replace(config, target="linux", mode=mode, name=name)
    artifact = create_artifact(candidate, tmp_path / "dist")
    executable = artifact / name if mode == "onedir" else artifact
    original = executable.read_bytes()
    assert _write_linux_metadata(candidate, artifact) is None
    assert executable.read_bytes() == original
    assert verify_artifact(candidate, tmp_path / "dist") == artifact


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX process group contract; Windows tested in native CI"
)
def test_process_group_cancellation_stops_grandchild(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild-alive"
    child_code = (
        "import pathlib,time; time.sleep(1); pathlib.Path("
        + repr(str(marker))
        + ").write_text('alive'); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', "
        + repr(child_code)
        + "]); print('ready',flush=True); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", parent_code], stdout=subprocess.PIPE, start_new_session=True
    )
    assert process.stdout and process.stdout.readline().strip() == b"ready"
    try:
        _terminate_process_tree(process)
        time.sleep(1.2)
        assert not marker.exists() and process.poll() is not None
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)
        process.stdout.close()


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX controlled child; Windows exercised in native CI"
)
def test_timeout_and_midbuild_cancel_terminate_child(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = subprocess.Popen
    launched = []

    def launch(*_: object, **options: object) -> subprocess.Popen[bytes]:
        process = real_popen(
            [sys.executable, "-I", "-c", "import time; print('ready',flush=True); time.sleep(30)"],
            **options,
        )
        launched.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    engine = BuildEngine()

    def cancel_on_log(event: BuildEvent) -> None:
        if event.kind == "log":
            engine.cancel()

    cancelled = engine.build(config, trusted=True, on_event=cancel_on_log)
    assert cancelled.status == "cancelled" and launched[-1].poll() is not None
    # Accelerate only the deadline clock; the child is still a real owned process.
    real_monotonic = time.monotonic
    monkeypatch.setattr(build_module.time, "monotonic", lambda: real_monotonic() * 200)
    timed_out = BuildEngine().build(replace(config, timeout=10), trusted=True)
    assert timed_out.status == "timeout" and launched[-1].poll() is not None


def test_keyboard_interrupt_is_reported_and_child_is_stopped(
    config: BuildConfig, fake_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_, **__: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    assert BuildEngine().build(config, trusted=True).status == "cancelled"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_job_owns_and_cancels_grandchild(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild-alive"
    child_code = (
        "import pathlib,time; time.sleep(1); pathlib.Path("
        + repr(str(marker))
        + ").write_text('alive'); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; print('ready',flush=True); time.sleep(.2); subprocess.Popen([sys.executable, '-c', "
        + repr(child_code)
        + "]); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", parent_code],
        stdout=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    job = build_module._WindowsJob(process)
    try:
        assert process.stdout and process.stdout.readline().strip() == b"ready"
        time.sleep(0.4)
        job.terminate()
        _terminate_process_tree(process)
        time.sleep(1.2)
        assert process.poll() is not None and not marker.exists()
    finally:
        job.close()
        if process.poll() is None:
            _terminate_process_tree(process)
        if process.stdout:
            process.stdout.close()
