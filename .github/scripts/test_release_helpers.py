"""Stdlib regression tests for the fail-closed manual release gate (Python 3.12 CI)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_environment
import release_gate


class ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.old_cwd = Path.cwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, self.old_cwd)
        Path("pyproject.toml").write_text('[project]\nversion="0.2.0"\n', encoding="utf-8")
        self.sha = "a" * 40
        self.env = {
            "RELEASE_COMMIT": self.sha,
            "RELEASE_VERSION": "0.2.0",
            "PROJECT_LICENSE_ATTESTED": "true",
            "DEPENDENCY_DISTRIBUTION_ATTESTED": "true",
        }
        # This temporary synthetic fixture is never written to the repository and
        # is not a license grant. The gate checks presence; rights are attested.
        self.grant_fixture = "Synthetic gate test text, not a real license. " + "x" * 150

    def run_gate(self, **changes: str) -> None:
        with (
            patch.dict(os.environ, {**self.env, **changes}, clear=True),
            patch.object(release_gate.subprocess, "check_output", return_value=self.sha + "\n"),
        ):
            release_gate.main()

    def test_missing_license_fails_despite_both_attestations(self) -> None:
        with self.assertRaisesRegex(SystemExit, "LICENSE grant"):
            self.run_gate()

    def test_placeholder_license_fails(self) -> None:
        Path("LICENSE").write_text("TODO " + self.grant_fixture, encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "placeholder"):
            self.run_gate()

    def test_each_attestation_is_required(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture, encoding="utf-8")
        for key in ("PROJECT_LICENSE_ATTESTED", "DEPENDENCY_DISTRIBUTION_ATTESTED"):
            with self.subTest(key=key), self.assertRaisesRegex(SystemExit, key):
                self.run_gate(**{key: "false"})

    def test_exact_commit_is_required(self) -> None:
        with self.assertRaisesRegex(SystemExit, "40-character"):
            self.run_gate(RELEASE_COMMIT="main")
        with self.assertRaisesRegex(SystemExit, "does not match"):
            self.run_gate(RELEASE_COMMIT="b" * 40)

    def test_version_must_match_metadata(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture, encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "pyproject.toml"):
            self.run_gate(RELEASE_VERSION="0.9.0")

    def test_untrusted_input_cannot_be_a_version(self) -> None:
        with self.assertRaisesRegex(SystemExit, "major.minor.patch"):
            self.run_gate(RELEASE_VERSION="0.2.0; echo injected")

    def test_presence_gate_accepts_only_matching_affirmed_fixture(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture, encoding="utf-8")
        self.run_gate()


class AuditExportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "pins.txt"
        self.editable = json.dumps([{"name": "pyforge-tool", "version": "0.2.0"}])

    def test_all_pins_exported_and_only_own_editable_omitted(self) -> None:
        with patch.object(
            audit_environment.subprocess,
            "check_output",
            side_effect=[self.editable, "pip==26.2.1\npytest==9.1.1\n"],
        ):
            audit_environment.export_requirements(self.output)
        self.assertEqual(self.output.read_text(), "pip==26.2.1\npytest==9.1.1\n")

    def test_unexpected_editable_is_not_silently_omitted(self) -> None:
        editable = json.dumps([{"name": "pyforge-tool"}, {"name": "unreviewed-local-project"}])
        with (
            patch.object(audit_environment.subprocess, "check_output", return_value=editable),
            self.assertRaisesRegex(SystemExit, "Do not silently skip"),
        ):
            audit_environment.export_requirements(self.output)
        self.assertFalse(self.output.exists())

    def test_url_or_marker_requirements_fail_closed(self) -> None:
        for requirement in (
            "package @ file:///private/path\n",
            "package==1.0;python_version>'3.10'\n",
        ):
            with (
                self.subTest(requirement=requirement),
                patch.object(
                    audit_environment.subprocess,
                    "check_output",
                    side_effect=[self.editable, requirement],
                ),
                self.assertRaisesRegex(SystemExit, "exact installed"),
            ):
                audit_environment.export_requirements(self.output)
        self.assertFalse(self.output.exists())

    def test_own_package_cannot_be_included_in_pins(self) -> None:
        with (
            patch.object(
                audit_environment.subprocess,
                "check_output",
                side_effect=[self.editable, "pyforge_tool==0.2.0\n"],
            ),
            self.assertRaisesRegex(SystemExit, "unexpectedly included"),
        ):
            audit_environment.export_requirements(self.output)


if __name__ == "__main__":
    unittest.main()
