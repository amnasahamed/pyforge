"""Stdlib regression tests for the fail-closed manual release gate (Python 3.12 CI)."""

from __future__ import annotations

import email
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import audit_environment
import package_preview
import release_gate
import verify_distribution


class ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.old_cwd = Path.cwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, self.old_cwd)
        self.write_metadata()
        Path("NOTICE").write_text("Test-only scope fixture.", encoding="utf-8")
        Path("docs").mkdir()
        Path("docs/LICENSING.md").write_text("Test-only legal fixture.", encoding="utf-8")
        self.sha = "a" * 40
        self.env = {
            "RELEASE_COMMIT": self.sha,
            "RELEASE_VERSION": "0.2.0",
            "PROJECT_LICENSE_ATTESTED": "true",
            "DEPENDENCY_DISTRIBUTION_ATTESTED": "true",
        }
        # Copy the existing authorized project grant, never synthesize a new one.
        self.grant_fixture = (Path(__file__).resolve().parents[2] / "LICENSE").read_text()

    def write_metadata(self, license: str = "MIT", files: tuple[str, ...] | None = None) -> None:
        paths = files if files is not None else ("LICENSE", "NOTICE", "docs/LICENSING.md")
        Path("pyproject.toml").write_text(
            f'[project]\nversion="0.2.0"\nlicense="{license}"\nlicense-files={json.dumps(paths)}\n',
            encoding="utf-8",
        )

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

    def test_arbitrary_long_text_is_not_an_mit_grant(self) -> None:
        Path("LICENSE").write_text("Synthetic text, not a license. " + "x" * 150)
        with self.assertRaisesRegex(SystemExit, "MIT grant structure"):
            self.run_gate()

    def test_license_metadata_cannot_disagree_with_grant(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture)
        self.write_metadata(license="GPL-3.0-only")
        with self.assertRaisesRegex(SystemExit, "license metadata"):
            self.run_gate()

    def test_scope_files_must_be_declared_and_present(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture)
        self.write_metadata(files=("LICENSE",))
        with self.assertRaisesRegex(SystemExit, "license-files"):
            self.run_gate()
        self.write_metadata()
        for file in ("NOTICE", "docs/LICENSING.md"):
            with self.subTest(file=file):
                path = Path(file)
                original = path.read_text()
                path.unlink()
                with self.assertRaisesRegex(SystemExit, "scope/legal notices"):
                    self.run_gate()
                path.write_text(original)

    def test_license_does_not_supply_missing_or_uppercase_attestation(self) -> None:
        Path("LICENSE").write_text(self.grant_fixture)
        for key in ("PROJECT_LICENSE_ATTESTED", "DEPENDENCY_DISTRIBUTION_ATTESTED"):
            for value in ("", "TRUE", "1"):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(SystemExit, key):
                    self.run_gate(**{key: value})


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


class PreviewNoticeTests(unittest.TestCase):
    def check_preview(self, target: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "artifacts" / "gui-preview"
            output.mkdir(parents=True)
            artifact = root / "preview-app"
            artifact.mkdir()
            (artifact / "app.bin").write_bytes(b"reviewed mock artifact")
            (root / "docs").mkdir()
            legal_bytes = {}
            for name in ("LICENSE", "NOTICE", "docs/LICENSING.md"):
                content = f"Test-only copy of {name}".encode()
                (root / name).write_bytes(content)
                legal_bytes[f"project-licenses/{name}"] = content
            (root / "forge.png").write_bytes(b"excluded original fixture")
            engine = SimpleNamespace(
                build=lambda *args, **kwargs: SimpleNamespace(success=True, artifact=artifact)
            )
            with (
                patch.object(package_preview, "__file__", str(root / ".github/scripts/preview.py")),
                patch.object(package_preview, "host_target", return_value=target),
                patch.object(package_preview, "BuildEngine", return_value=engine),
            ):
                package_preview.main()
            if target == "windows":
                with zipfile.ZipFile(next(output.glob("*.zip"))) as archive:
                    for name, content in legal_bytes.items():
                        self.assertEqual(archive.read(name), content)
                    self.assertNotIn("forge.png", archive.namelist())
            else:
                with tarfile.open(next(output.glob("*.tar.gz")), "r:gz") as archive:
                    for name, content in legal_bytes.items():
                        file = archive.extractfile(name)
                        assert file is not None
                        self.assertEqual(file.read(), content)
                    self.assertNotIn("forge.png", archive.getnames())
            self.assertIn(
                "does not license the combined GUI binary",
                (output / "PREVIEW-NOTICE.txt").read_text(),
            )

    def test_zip_contains_project_notices_without_original_icons(self) -> None:
        self.check_preview("windows")

    def test_tar_contains_project_notices_without_original_icons(self) -> None:
        self.check_preview("linux")


class DistributionLicenseTests(unittest.TestCase):
    headers = (
        "Metadata-Version: 2.4\nLicense-Expression: MIT\nLicense-File: LICENSE\n"
        "License-File: NOTICE\nLicense-File: docs/LICENSING.md\n"
    )

    def test_matching_metadata_and_notices_pass(self) -> None:
        verify_distribution.verify_license_metadata(email.message_from_string(self.headers), "test")
        payloads = {name: b"reviewed fixture" for name in verify_distribution.LICENSE_FILES}
        verify_distribution.verify_license_payloads(payloads, payloads, "test")

    def test_missing_wrong_duplicate_or_legacy_metadata_fails(self) -> None:
        for headers in (
            self.headers.replace("License-Expression: MIT\n", ""),
            self.headers.replace("MIT", "GPL-3.0-only"),
            self.headers.replace("2.4", "2.3"),
            self.headers.replace("License-File: NOTICE\n", ""),
            self.headers + "License-Expression: MIT\n",
            self.headers + "License-File: NOTICE\n",
            self.headers + "License: MIT\n",
        ):
            with self.subTest(headers=headers), self.assertRaises(SystemExit):
                verify_distribution.verify_license_metadata(
                    email.message_from_string(headers), "test"
                )

    def test_missing_or_changed_legal_payloads_fail(self) -> None:
        expected = {name: b"reviewed fixture" for name in verify_distribution.LICENSE_FILES}
        for changed in ({"LICENSE": b"reviewed fixture"}, {**expected, "NOTICE": b"changed"}):
            with self.subTest(payloads=changed), self.assertRaises(SystemExit):
                verify_distribution.verify_license_payloads(changed, expected, "test")

    def test_zip_legal_member_cannot_be_a_symlink(self) -> None:
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            member = zipfile.ZipInfo("LICENSE")
            member.create_system = 3
            member.external_attr = 0o120777 << 16
            archive.writestr(member, b"external-target")
        memory.seek(0)
        with zipfile.ZipFile(memory) as archive, self.assertRaisesRegex(SystemExit, "regular"):
            verify_distribution.read_wheel_file(archive, "LICENSE")

    def test_tar_legal_member_cannot_be_a_link(self) -> None:
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode="w") as archive:
            member = tarfile.TarInfo("LICENSE")
            member.type = tarfile.SYMTYPE
            member.linkname = "external-target"
            archive.addfile(member)
        memory.seek(0)
        with (
            tarfile.open(fileobj=memory, mode="r") as archive,
            self.assertRaisesRegex(SystemExit, "regular"),
        ):
            verify_distribution.read_sdist_file(archive, "LICENSE")


if __name__ == "__main__":
    unittest.main()
