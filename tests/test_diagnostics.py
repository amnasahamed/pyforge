"""Doctor checks are read-only and return actionable structured findings."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyforge.config import BuildConfig
from pyforge.diagnostics import run_doctor
from pyforge.platform import host_target


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "main.py"
        self.script.write_text("import json\n", encoding="utf-8")
        self.config = BuildConfig(self.script, self.root / "output", "Hello")

    def test_invalid_configuration_makes_report_not_ok(self) -> None:
        config = BuildConfig(self.root / "missing.py", self.root / "output", "../escape")
        report = run_doctor(config)
        self.assertFalse(report.ok)
        self.assertTrue(any(item.severity == "error" for item in report.findings))

    def test_cross_platform_request_is_actionable_error(self) -> None:
        target = "windows" if host_target() != "windows" else "linux"
        config = BuildConfig(self.script, self.root / "output", "Hello", target=target)
        report = run_doctor(config)
        self.assertFalse(report.ok)
        text = " ".join(item.message + " " + item.recovery for item in report.findings).lower()
        self.assertTrue("cross" in text or "machine" in text or "host" in text)

    def test_missing_packager_is_error_with_recovery(self) -> None:
        real_find_spec = importlib.util.find_spec
        real_version = importlib.metadata.version

        def find_spec(name: str, *args: object, **kwargs: object) -> object:
            if name.lower() == "pyinstaller":
                return None
            return real_find_spec(name, *args, **kwargs)

        def version(name: str) -> str:
            if name.lower() == "pyinstaller":
                raise importlib.metadata.PackageNotFoundError(name)
            return real_version(name)

        with (
            patch("importlib.util.find_spec", side_effect=find_spec),
            patch("importlib.metadata.version", side_effect=version),
        ):
            report = run_doctor(self.config)
        findings = [
            item
            for item in report.findings
            if "pyinstaller" in item.message.lower() or "pyinstaller" in item.code.lower()
        ]
        self.assertTrue(findings)
        self.assertTrue(any(item.severity == "error" and item.recovery for item in findings))
        self.assertFalse(report.ok)

    def test_doctor_does_not_run_or_install_project(self) -> None:
        marker = self.root / "ran.txt"
        self.script.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8"
        )
        requirements = self.root / "requirements.txt"
        requirements.write_bytes(b"# preserved\n")
        before = {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        with patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
            report = run_doctor(self.config)
        popen.assert_not_called()
        run.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertFalse(self.config.output_dir.exists())
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        )
        self.assertIsNotNone(report.dependencies)

    def test_report_findings_are_structured_and_json_serializable(self) -> None:
        report = run_doctor(self.config)
        self.assertTrue(report.findings)
        for item in report.findings:
            self.assertIn(item.severity, ("info", "warning", "error"))
            self.assertTrue(item.code)
            self.assertTrue(item.message)
            self.assertIsInstance(item.recovery, str)
        json.dumps(report.to_dict())

    def test_multiple_qt_binding_imports_are_warned(self) -> None:
        self.script.write_text("import PyQt5\nimport PySide6\n", encoding="utf-8")
        report = run_doctor(self.config)
        self.assertTrue(any(item.code == "qt-conflict" for item in report.findings))

    def test_auto_linux_windowed_warning(self) -> None:
        with patch("pyforge.diagnostics.host_target", return_value="linux"):
            report = run_doctor(
                BuildConfig(self.script, self.root / "output", "Hello", console=False)
            )
        self.assertTrue(any(item.code == "linux-windowed" for item in report.findings))

    def test_frozen_preview_cannot_recursively_build(self) -> None:
        with patch.object(__import__("sys"), "frozen", True, create=True):
            report = run_doctor(self.config)
        self.assertFalse(report.ok)
        self.assertTrue(any(item.code == "frozen-runtime" for item in report.findings))

    def test_unsupported_packager_versions_are_errors(self) -> None:
        for version in ("5.13.2", "6.0", "7.0", "broken"):
            with (
                self.subTest(version=version),
                patch("importlib.metadata.version", return_value=version),
            ):
                self.assertFalse(run_doctor(self.config).ok)


if __name__ == "__main__":
    unittest.main()
