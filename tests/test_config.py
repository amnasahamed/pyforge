"""Configuration and profile safety contracts, independent of Qt or PyInstaller."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyforge.config import BuildConfig, ConfigError, load_profile, save_profile
from pyforge.platform import expected_artifact, resolve_target


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "hello.py"
        self.script.write_text("print('hello')\n", encoding="utf-8")

    def config(self, **changes: object) -> BuildConfig:
        values = dict(script=self.script, output_dir=self.root / "output", name="Hello")
        values.update(changes)
        return BuildConfig(**values)

    def test_valid_config(self) -> None:
        self.assertEqual(self.config(target="linux").validate(host="linux"), [])

    def test_normalized_paths_are_absolute_without_creating_output(self) -> None:
        with patch("os.getcwd", return_value=str(self.root)):
            config = self.config(
                script=Path("hello.py"), output_dir=Path("new output")
            ).normalized()
        self.assertTrue(config.script.is_absolute())
        self.assertTrue(config.output_dir.is_absolute())
        self.assertFalse(config.output_dir.exists())

    def test_normalization_does_not_hide_invalid_names(self) -> None:
        self.assertTrue(self.config(name="trailing ").normalized().validate())

    def test_stat_failure_becomes_actionable_error(self) -> None:
        with patch.object(Path, "stat", side_effect=PermissionError("denied")):
            self.assertTrue(self.config().validate())

    def test_oversized_hidden_import_list_rejected(self) -> None:
        self.assertTrue(self.config(hidden_imports=("json",) * 501).validate())

    def test_missing_script_has_actionable_error(self) -> None:
        errors = self.config(script=self.root / "missing.py").validate(host="linux")
        self.assertTrue(errors)
        self.assertIn("script", " ".join(errors).lower())

    def test_directory_cannot_be_script(self) -> None:
        self.assertTrue(self.config(script=self.root).validate(host="linux"))

    def test_cross_os_builds_rejected(self) -> None:
        for host in ("windows", "macos", "linux"):
            for target in ("windows", "macos", "linux"):
                with self.subTest(host=host, target=target):
                    errors = self.config(target=target).validate(host=host)
                    self.assertEqual(bool(errors), target != host)

    def test_unsafe_names_rejected(self) -> None:
        for name in (
            "",
            "..",
            "../escape",
            "a/b",
            "a\\b",
            "x\x00y",
            "bad\nname",
            "trailing.",
            "trailing ",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.config(name=name).validate(host="windows"))

    def test_windows_reserved_names_rejected_case_insensitively(self) -> None:
        for name in ("CON", "con", "NUL", "AUX", "PRN", "COM1", "LPT9", "con.txt"):
            with self.subTest(name=name):
                self.assertTrue(self.config(name=name).validate(host="windows"))

    def test_unknown_mode_target_and_invalid_timeout_rejected(self) -> None:
        for changes in (
            {"mode": "unknown"},
            {"target": "unknown"},
            {"timeout": 0},
            {"timeout": -1},
        ):
            with self.subTest(changes=changes):
                self.assertTrue(self.config(**changes).validate(host="linux"))

    def test_missing_icon_rejected(self) -> None:
        errors = self.config(target="windows", icon=self.root / "missing.ico").validate(
            host="windows"
        )
        self.assertTrue(errors)
        self.assertIn("icon", " ".join(errors).lower())

    def test_icon_extension_does_not_replace_signature_validation(self) -> None:
        icon = self.root / "fake.ico"
        icon.write_bytes(b"This is not an icon")
        self.assertTrue(self.config(target="windows", icon=icon).validate(host="windows"))

    def test_relative_icon_is_normalized(self) -> None:
        with patch("os.getcwd", return_value=str(self.root)):
            config = self.config(icon=Path("app.ico")).normalized()
        self.assertTrue(config.icon is not None and config.icon.is_absolute())

    def test_profile_roundtrip_preserves_all_user_options(self) -> None:
        profile = self.root / "profile.json"
        config = self.config(
            mode="onefile",
            console=False,
            version="2.3.4",
            description='A "quoted" description \\ with unicode: café',
            bundle_identifier="org.example.hello",
            hidden_imports=("pkg.plugin", "json"),
            timeout=37,
        ).normalized()
        save_profile(config, profile)
        self.assertEqual(load_profile(profile), config)
        self.assertIsInstance(json.loads(profile.read_text(encoding="utf-8")), dict)

    def test_missing_or_malformed_profiles_raise_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            load_profile(self.root / "missing.json")
        for content in ("{", "[]", '"hello"', '{"schema_version": 999}', '{"script": 3}'):
            profile = self.root / "bad.json"
            profile.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(ConfigError):
                load_profile(profile)

    def test_profile_cannot_overwrite_entry_source(self) -> None:
        original = self.script.read_bytes()
        with self.assertRaises(ConfigError):
            save_profile(self.config(), self.script)
        self.assertEqual(self.script.read_bytes(), original)

    def test_oversized_profile_rejected(self) -> None:
        profile = self.root / "big.json"
        profile.write_bytes(b" " * (128 * 1024 + 1))
        with self.assertRaises(ConfigError):
            load_profile(profile)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named pipes are a POSIX feature")
    def test_profile_named_pipe_rejected_without_blocking(self) -> None:
        profile = self.root / "pipe.json"
        os.mkfifo(profile)
        with self.assertRaises(ConfigError):
            load_profile(profile)

    def test_failed_atomic_profile_replace_preserves_existing_file(self) -> None:
        profile = self.root / "profile.json"
        save_profile(self.config().normalized(), profile)
        original = profile.read_bytes()
        with (
            patch("os.replace", side_effect=OSError("simulated disk failure")),
            self.assertRaises((ConfigError, OSError)),
        ):
            save_profile(self.config(name="Changed").normalized(), profile)
        self.assertEqual(profile.read_bytes(), original)
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()), ["hello.py", "profile.json"]
        )


class PlatformTests(unittest.TestCase):
    def test_auto_target_uses_host(self) -> None:
        for host in ("windows", "macos", "linux"):
            with self.subTest(host=host):
                self.assertEqual(resolve_target("auto", host=host), host)

    def test_cross_os_target_resolution_rejected(self) -> None:
        with self.assertRaises((ValueError, ConfigError)):
            resolve_target("windows", host="linux")

    def test_expected_artifacts_match_native_layout(self) -> None:
        root = Path("dist")
        for target, mode, console, expected in (
            ("windows", "onefile", True, root / "Hello.exe"),
            ("windows", "onedir", False, root / "Hello"),
            ("linux", "onefile", True, root / "Hello"),
            ("linux", "onedir", True, root / "Hello"),
            ("macos", "onedir", False, root / "Hello.app"),
            ("macos", "onefile", True, root / "Hello"),
        ):
            config = BuildConfig(
                script=Path("hello.py"),
                output_dir=root,
                name="Hello",
                target=target,
                mode=mode,
                console=console,
            )
            with self.subTest(target=target, mode=mode, console=console):
                self.assertEqual(expected_artifact(config, root), expected)


if __name__ == "__main__":
    unittest.main()
