"""Dependency inspection must be static and must never mutate the project."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyforge.dependencies import inspect_dependencies


class DependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "main.py"

    def write_script(self, source: str) -> None:
        self.script.write_text(source, encoding="utf-8")

    def test_classifies_stdlib_local_and_installed_distribution_imports(self) -> None:
        self.write_script(
            "import os\nimport json as j\nfrom requests.sessions import Session\nimport helper\n"
        )
        (self.root / "helper.py").write_text("import pathlib\n", encoding="utf-8")
        with patch(
            "importlib.metadata.packages_distributions", return_value={"requests": ["requests"]}
        ):
            report = inspect_dependencies(self.script)
        imports = {dep.name.split(".")[0]: dep for dep in report.imports}
        self.assertIn("os", imports)
        self.assertIn("json", imports)
        self.assertIn("helper", imports)
        self.assertIn("requests", imports)
        self.assertIn(imports["os"].kind, ("stdlib", "standard"))
        self.assertEqual(imports["helper"].kind, "local")
        self.assertEqual(imports["requests"].distributions, ("requests",))
        self.assertGreaterEqual(report.files_scanned, 1)

    def test_never_executes_project_imports_or_top_level_code(self) -> None:
        marker = self.root / "executed.txt"
        evil_source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\nraise RuntimeError('must not run')\n"
        (self.root / "untrusted_pyforge_fixture.py").write_text(evil_source, encoding="utf-8")
        package = self.root / "untrusted_pyforge_package"
        package.mkdir()
        (package / "__init__.py").write_text(evil_source, encoding="utf-8")
        (package / "child.py").write_text("import json\n", encoding="utf-8")
        self.write_script(
            evil_source
            + "\nimport untrusted_pyforge_fixture\nimport untrusted_pyforge_package.child\n"
        )
        with (
            patch.object(sys, "path", [str(self.root), *sys.path]),
            patch("subprocess.run") as run,
            patch("subprocess.Popen") as popen,
        ):
            report = inspect_dependencies(self.script)
        self.assertFalse(marker.exists())
        self.assertNotIn("untrusted_pyforge_fixture", sys.modules)
        self.assertNotIn("untrusted_pyforge_package", sys.modules)
        run.assert_not_called()
        popen.assert_not_called()
        self.assertTrue(report.imports)

    def test_does_not_write_requirements_or_other_project_files(self) -> None:
        requirements = self.root / "requirements.txt"
        requirements.write_bytes(b"# user-owned\ncustom-package==1.2.3\n")
        self.write_script("import json\nimport nonexistent_pyforge_fixture\n")
        before = {
            p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()
        }
        inspect_dependencies(self.script)
        after = {
            p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()
        }
        self.assertEqual(after, before)

    def test_syntax_errors_are_reported_without_crashing(self) -> None:
        self.write_script("def broken(:\n")
        report = inspect_dependencies(self.script)
        self.assertTrue(report.issues)
        self.assertIn("syntax", " ".join(report.issues).lower())

    def test_missing_script_is_reported_without_crashing(self) -> None:
        report = inspect_dependencies(self.root / "missing.py")
        self.assertTrue(report.issues)

    def test_relative_package_imports_and_dynamic_imports_do_not_execute(self) -> None:
        package = self.root / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        self.script = package / "main.py"
        self.write_script(
            "from . import helper\nimport importlib\nimportlib.import_module('untrusted_unknown')\n"
        )
        (package / "helper.py").write_text("import math\n", encoding="utf-8")
        with patch(
            "importlib.import_module",
            side_effect=AssertionError("Inspection executed a dynamic import"),
        ):
            report = inspect_dependencies(self.script)
        self.assertGreaterEqual(report.files_scanned, 1)
        self.assertIsInstance(report.to_dict(), dict)

    def test_report_is_json_serializable(self) -> None:
        import json

        self.write_script("import json\n")
        json.dumps(inspect_dependencies(self.script).to_dict())

    def test_unknown_source_encoding_is_reported(self) -> None:
        self.script.write_bytes(b"# coding: nonexistent_pyforge_encoding\nprint('hello')\n")
        self.assertTrue(inspect_dependencies(self.script).issues)

    def test_stdlib_shadow_is_identified(self) -> None:
        self.write_script("import json\n")
        (self.root / "json.py").write_text("# shadow\n", encoding="utf-8")
        report = inspect_dependencies(self.script)
        self.assertTrue(any("shadows" in issue for issue in report.issues))
        self.assertEqual(next(d for d in report.imports if d.name == "json").kind, "local")

    def test_source_symlinks_are_not_followed(self) -> None:
        self.write_script("import json\n")
        outside = self.root.parent / (self.root.name + "-outside.py")
        outside.write_text("import nonexistent_outside_dependency\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        try:
            (self.root / "linked.py").symlink_to(outside)
        except OSError:
            self.skipTest("Host does not permit symlinks")
        report = inspect_dependencies(self.script)
        self.assertNotIn("nonexistent_outside_dependency", {d.name for d in report.imports})

    def test_scan_limits_are_reported(self) -> None:
        self.write_script("import json\n")
        for i in range(3):
            (self.root / f"helper{i}.py").write_text("import os\n", encoding="utf-8")
        with patch("pyforge.dependencies.MAX_FILES", 2):
            report = inspect_dependencies(self.script)
        self.assertEqual(report.files_scanned, 2)
        self.assertTrue(any("stopped" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
