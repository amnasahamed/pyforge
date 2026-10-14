"""Opt-in real native builds of reviewed fixtures, never arbitrary project code."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from pyforge.config import BuildConfig
from pyforge.platform import host_target

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PYFORGE_RUN_INTEGRATION") != "1",
        reason="Set PYFORGE_RUN_INTEGRATION=1 to build and run reviewed examples.",
    ),
]

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _source(tmp_path: Path, filename: str) -> Path:
    source_dir = tmp_path / "reviewed source with spaces"
    source_dir.mkdir()
    source = source_dir / filename
    shutil.copyfile(EXAMPLES / filename, source)
    return source


def _output(tmp_path: Path, scenario: str) -> Path:
    root = os.environ.get("PYFORGE_INTEGRATION_OUTPUT")
    return Path(root).resolve() / scenario if root else tmp_path / "output with spaces"


def _executable(artifact: Path, name: str, target: str) -> Path:
    if artifact.suffix == ".app":
        return artifact / "Contents" / "MacOS" / name
    if artifact.is_dir():
        return artifact / (name + (".exe" if target == "windows" else ""))
    return artifact


@pytest.mark.parametrize("mode", ["onedir", "onefile"])
def test_native_cli_build_and_launch(tmp_path: Path, mode: str) -> None:
    pytest.importorskip("PyInstaller")
    from pyforge.build import BuildEngine

    script = _source(tmp_path, "hello_cli.py")
    requirements = script.parent / "requirements.txt"
    requirements.write_text("# user-maintained file: must not be rewritten\n", encoding="utf-8")
    baseline = requirements.read_bytes()
    config = BuildConfig(
        script=script,
        output_dir=_output(tmp_path, f"cli-{mode}"),
        name=f"ReviewedCLI-{mode}",
        mode=mode,
        target=host_target(),
        version="2.3.4",
        description="Reviewed stdlib packaging fixture",
        timeout=600,
    )
    result = BuildEngine().build(config, trusted=True)
    assert result.success, result.to_dict()
    assert result.artifact is not None
    artifact = Path(result.artifact)
    completed = subprocess.run(
        [str(_executable(artifact, config.name, config.target)), "--name", "Native CI"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    message = json.loads(completed.stdout)
    assert message == {"message": "Hello, Native CI!", "marker": "PYFORGE_SMOKE_OK"}
    assert result.report_path is not None
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["success"] is True
    assert requirements.read_bytes() == baseline
    assert not list(script.parent.glob("*.spec"))
    assert not (script.parent / "build").exists()


def test_native_windowed_gui_build_and_launch(tmp_path: Path) -> None:
    if os.environ.get("PYFORGE_RUN_GUI_INTEGRATION") != "1":
        pytest.skip("Set PYFORGE_RUN_GUI_INTEGRATION=1 to package the reviewed Qt example.")
    pytest.importorskip("PyInstaller")
    pytest.importorskip("PyQt5")
    from pyforge.build import BuildEngine

    script = _source(tmp_path, "hello_gui.py")
    config = BuildConfig(
        script=script,
        output_dir=_output(tmp_path, "gui-onedir"),
        name="ReviewedGUI",
        mode="onedir",
        console=False,
        target=host_target(),
        version="2.3.4",
        description="Reviewed Qt packaging fixture",
        bundle_identifier="org.example.pyforge.reviewedgui",
        timeout=900,
    )
    result = BuildEngine().build(config, trusted=True)
    assert result.success, result.to_dict()
    assert result.artifact is not None
    artifact = Path(result.artifact)
    if config.target == "macos":
        assert artifact.suffix == ".app"
        with (artifact / "Contents" / "Info.plist").open("rb") as handle:
            metadata = plistlib.load(handle)
        assert metadata["CFBundleIdentifier"] == config.bundle_identifier
        assert metadata["CFBundleShortVersionString"] == config.version
        assert metadata["CFBundleVersion"] == config.version

    marker = tmp_path / "explicit-gui-smoke-marker.txt"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    completed = subprocess.run(
        [
            str(_executable(artifact, config.name, config.target)),
            "--smoke-test",
            "--marker-file",
            str(marker),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").strip() == "PYFORGE_GUI_SMOKE_OK"
