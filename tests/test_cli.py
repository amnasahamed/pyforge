"""Headless CLI commands, inert profiles, trust and machine-readable failures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import pyforge.cli as cli_module
from pyforge.build import BuildResult
from pyforge.cli import main
from pyforge.config import MAX_SCRIPT_BYTES, load_profile
from pyforge.dependencies import DependencyReport
from pyforge.diagnostics import Diagnostic, DoctorReport


@pytest.fixture
def script(tmp_path: Path) -> Path:
    result = tmp_path / "demo.py"
    result.write_text("import json\nprint('never run on inspect')\n", encoding="utf-8")
    return result


def test_cli_import_does_not_import_qt() -> None:
    # Other tests legitimately import Qt during pytest collection; use a fresh process.
    source = Path(cli_module.__file__).resolve().parents[1]
    code = f"import sys; sys.path.insert(0, {str(source)!r}); import pyforge.cli; assert 'PyQt5.QtWidgets' not in sys.modules"
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_inspect_json_is_read_only(
    script: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "executed"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\nimport json\n",
        encoding="utf-8",
    )
    assert main(["inspect", str(script), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["files_scanned"] == 1
    assert not marker.exists()


def test_inspect_parse_error_is_nonzero(script: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script.write_text("syntax is invalid !!!\n", encoding="utf-8")
    assert main(["inspect", str(script), "--json"]) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]


def test_inspect_oversized_entry_is_nonzero(
    script: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script.write_bytes(b"#" * (MAX_SCRIPT_BYTES + 1))
    assert main(["inspect", str(script), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert not data["ok"] and not data["entry_inspected"]


def test_build_rejects_missing_trust(script: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build", str(script), "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "untrusted" and not result["success"]
    assert not (script.parent / "dist").exists()


def test_cli_doctor_json_and_nonzero_status(
    script: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = DoctorReport(
        [Diagnostic("error", "missing", "Missing build dependency", "Review build extra")],
        DependencyReport([], [], 1),
    )
    monkeypatch.setattr(cli_module, "run_doctor", lambda _: report)
    assert main(["doctor", str(script), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert not data["ok"] and data["findings"][0]["recovery"] == "Review build extra"


def test_doctor_reports_invalid_configuration_without_executing(
    script: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor", str(script), "--name", "../bad", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert any(finding["code"] == "config" for finding in data["findings"])


def test_profile_save_roundtrip_and_build_overrides(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "profiles" / "demo.json"
    assert (
        main(
            [
                "profile",
                "save",
                str(path),
                str(script),
                "--name",
                "Saved",
                "--version",
                "2.3.4",
                "--hidden-import",
                "json",
                "--no-console",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["profile"] == str(path)
    saved = load_profile(path)
    assert saved.name == "Saved" and saved.hidden_imports == ("json",) and not saved.console
    assert "trusted" not in path.read_text(encoding="utf-8")
    seen = []

    class Engine:
        def build(self, config: object, *, trusted: bool, on_event: object) -> BuildResult:
            seen.append((config, trusted))
            return BuildResult(True, "success", artifact=tmp_path / "native")

    monkeypatch.setattr(cli_module, "BuildEngine", Engine)
    assert (
        main(
            [
                "build",
                "--profile",
                str(path),
                "--name",
                "Override",
                "--console",
                "--mode",
                "onefile",
                "--trust-code",
                "--json",
            ]
        )
        == 0
    )
    assert seen[0][0].name == "Override" and seen[0][0].console and seen[0][1] is True
    assert json.loads(capsys.readouterr().out)["success"]
    assert load_profile(path).name == "Saved"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["unknown"],
        ["build"],
        ["build", "--bogus"],
        ["profile"],
        ["build", "--timeout", "not-an-int"],
    ],
)
def test_argument_errors_are_machine_readable(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*arguments, "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "invalid" and data["errors"]


def test_script_and_profile_are_mutually_exclusive(
    script: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", str(script), "--profile", "other.json", "--json"]) == 2
    assert "not both" in json.loads(capsys.readouterr().out)["errors"][0]


def test_invalid_trailing_name_is_not_silently_normalized(
    script: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", str(script), "--name", "bad ", "--trust-code", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"


@pytest.mark.parametrize(
    "status, expected",
    [("failed", 1), ("cancelled", 130), ("timeout", 124), ("preflight_failed", 1)],
)
def test_cli_maps_build_exit_status(
    script: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected: int,
) -> None:
    class Engine:
        def build(self, *args: object, **kwargs: object) -> BuildResult:
            return BuildResult(False, status, errors=("Actionable issue",))

    monkeypatch.setattr(cli_module, "BuildEngine", Engine)
    assert main(["build", str(script), "--trust-code", "--json"]) == expected
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_ctrl_c_outside_build_has_nonzero_json(
    script: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli_module, "inspect_dependencies", lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    assert main(["inspect", str(script), "--json"]) == 130
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"


def test_help_is_available_without_gui(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_status:
        main(["--help"])
    assert exit_status.value.code == 0
    assert "inspect" in capsys.readouterr().out
