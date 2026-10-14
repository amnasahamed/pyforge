"""Validated build settings and inert, versioned JSON profiles."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from pyforge.platform import resolve_target

PROFILE_SCHEMA = 1
MAX_PROFILE_BYTES = 128 * 1024
MAX_SCRIPT_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}\Z")
_VERSION = re.compile(r"\d{1,5}(?:\.\d{1,5}){0,3}\Z")
_MODULE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z", re.ASCII)
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{x}" for x in range(1, 10)),
    *(f"LPT{x}" for x in range(1, 10)),
}


class ConfigError(ValueError):
    """An input or profile cannot be safely used."""


@dataclass(frozen=True)
class BuildConfig:
    script: Path
    output_dir: Path
    name: str
    target: str = "auto"
    mode: str = "onedir"
    console: bool = True
    icon: Path | None = None
    version: str = "1.0.0"
    description: str = ""
    bundle_identifier: str = ""
    hidden_imports: tuple[str, ...] = ()
    timeout: int = 600

    def normalized(self) -> BuildConfig:
        try:
            target = resolve_target(self.target)
            return replace(
                self,
                script=self.script.expanduser().resolve(),
                output_dir=self.output_dir.expanduser().resolve(),
                icon=self.icon.expanduser().resolve() if self.icon else None,
                target=target,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            raise ConfigError(str(exc)) from exc

    def validate(self, host: str | None = None) -> list[str]:
        errors: list[str] = []
        try:
            target = resolve_target(self.target, host)
        except ValueError as exc:
            errors.append(str(exc))
            target = self.target
        try:
            if not self.script.is_file() or self.script.suffix.lower() != ".py":
                errors.append(
                    "Choose an existing .py entry script; .spec files are executable code and are not accepted."
                )
            elif self.script.stat().st_size > MAX_SCRIPT_BYTES:
                errors.append(
                    "Entry script exceeds the 2 MiB inspection limit; choose a smaller entry script."
                )
        except OSError as exc:
            errors.append(f"Cannot read entry script: {exc}")
        if not _NAME.fullmatch(self.name) or self.name.endswith((".", " ")):
            errors.append(
                "App name must be 1–80 ASCII letters/numbers/spaces/dots/dashes/underscores, start with a letter or number, and not end in a dot or space."
            )
        elif self.name.split(".")[0].upper() in _RESERVED:
            errors.append("App name is reserved by Windows; choose another name.")
        if self.mode not in ("onefile", "onedir"):
            errors.append("Bundle mode must be onefile or onedir.")
        if type(self.console) is not bool:
            errors.append("Console setting must be a boolean.")
        if type(self.timeout) is not int or not 10 <= self.timeout <= 86400:
            errors.append("Build timeout must be an integer from 10 to 86400 seconds.")
        if not _VERSION.fullmatch(self.version) or any(
            int(x) > 65535 for x in self.version.split(".")
        ):
            errors.append(
                "Version must contain 1–4 numeric parts from 0 to 65535 (for example 1.2.0)."
            )
        elif target == "macos" and not self.console:
            parts = self.version.split(".")
            if len(parts) != 3 or not (
                1 <= int(parts[0]) <= 9999 and int(parts[1]) <= 99 and int(parts[2]) <= 99
            ):
                errors.append(
                    "A macOS .app version must have three numeric parts: major 1–9999, minor/patch 0–99 (for example 1.2.0)."
                )
        if len(self.description) > 500 or any(
            ord(c) < 32 and c not in "\n\t" for c in self.description
        ):
            errors.append("Description must be at most 500 characters without control characters.")
        if self.bundle_identifier and not re.fullmatch(
            r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", self.bundle_identifier
        ):
            errors.append(
                "Bundle identifier must be reverse DNS style, for example com.example.myapp."
            )
        if any(not _MODULE.fullmatch(x) for x in self.hidden_imports):
            errors.append("Hidden imports must be Python module names, not commands or file paths.")
        if len(self.hidden_imports) > 500:
            errors.append("At most 500 hidden imports are supported; narrow the dependency list.")
        try:
            if self.output_dir.exists() and not self.output_dir.is_dir():
                errors.append("Output path exists and is not a directory.")
            ancestor = self.output_dir.expanduser().resolve()
            while not ancestor.exists() and ancestor.parent != ancestor:
                ancestor = ancestor.parent
            if not os.access(ancestor, os.W_OK):
                errors.append(
                    "Output directory is not writable; choose a location you can write to."
                )
        except (OSError, RuntimeError) as exc:
            errors.append(f"Cannot access output directory: {exc}")
        if self.icon:
            expected = {"windows": ".ico", "macos": ".icns", "linux": ".png"}.get(target)
            try:
                if not self.icon.is_file() or self.icon.suffix.lower() != expected:
                    errors.append(f"Choose an existing {expected or 'native'} icon for {target}.")
                elif self.icon.stat().st_size > 16 * 1024 * 1024:
                    errors.append("Icon exceeds the 16 MiB limit; export a smaller native icon.")
                else:
                    with self.icon.open("rb") as handle:
                        signature = handle.read(8)
                    prefixes = {
                        ".ico": b"\x00\x00\x01\x00",
                        ".icns": b"icns",
                        ".png": b"\x89PNG\r\n\x1a\n",
                    }
                    if not signature.startswith(prefixes[self.icon.suffix.lower()]):
                        errors.append(
                            "Icon contents do not match its file extension; export a valid native icon."
                        )
            except OSError as exc:
                errors.append(f"Cannot read icon: {exc}")
        return errors


def _profile_data(config: BuildConfig) -> dict[str, Any]:
    result: dict[str, Any] = asdict(config)
    result["script"] = str(config.script)
    result["output_dir"] = str(config.output_dir)
    result["icon"] = str(config.icon) if config.icon else None
    result["hidden_imports"] = list(config.hidden_imports)
    return {"schema_version": PROFILE_SCHEMA, "config": result}


def save_profile(config: BuildConfig, path: Path) -> None:
    """Atomically save settings only; profiles never contain commands or credentials."""
    normalized = config.normalized()
    errors = normalized.validate()
    if errors:
        raise ConfigError("\n".join(errors))
    path = path.expanduser().resolve()
    if path.suffix.lower() != ".json":
        raise ConfigError(
            "Build profiles must use a .json filename; source files are never overwritten."
        )
    if path in (normalized.script, normalized.icon):
        raise ConfigError("A profile cannot replace its entry script or icon.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".pyforge-profile-", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(_profile_data(normalized), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise ConfigError(f"Could not save profile: {exc}") from exc
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def load_profile(path: Path) -> BuildConfig:
    """Load strict JSON with paths resolved relative to the profile file."""
    try:
        path = path.expanduser().resolve()
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ConfigError("Profile must be a regular JSON file, not a pipe or device.")
            content = handle.read(MAX_PROFILE_BYTES + 1)
        if len(content) > MAX_PROFILE_BYTES:
            raise ConfigError("Profile exceeds the 128 KiB limit.")
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema_version", "config"}:
            raise ConfigError("Profile must contain only schema_version and config.")
        if type(data["schema_version"]) is not int or data["schema_version"] != PROFILE_SCHEMA:
            raise ConfigError("Unsupported profile schema version.")
        values = data["config"]
        allowed = {f.name for f in fields(BuildConfig)}
        if (
            not isinstance(values, dict)
            or set(values) - allowed
            or not {"script", "output_dir", "name"} <= set(values)
        ):
            raise ConfigError("Profile contains unknown or missing configuration fields.")
        for key in (
            "script",
            "output_dir",
            "name",
            "target",
            "mode",
            "version",
            "description",
            "bundle_identifier",
        ):
            if key in values and not isinstance(values[key], str):
                raise ConfigError(f"Profile {key} must be a string.")
        if "console" in values and type(values["console"]) is not bool:
            raise ConfigError("Profile console must be a boolean.")
        if "timeout" in values and type(values["timeout"]) is not int:
            raise ConfigError("Profile timeout must be an integer.")
        imports = values.get("hidden_imports", [])
        if not isinstance(imports, list) or not all(isinstance(x, str) for x in imports):
            raise ConfigError("Profile hidden_imports must be a list of module names.")
        values["hidden_imports"] = tuple(imports)
        for key in ("script", "output_dir", "icon"):
            value = values.get(key)
            if key == "icon" and value is None:
                continue
            if not isinstance(value, str):
                raise ConfigError(f"Profile {key} must be a path string.")
            candidate = Path(value).expanduser()
            values[key] = (
                (path.parent / candidate).resolve()
                if not candidate.is_absolute()
                else candidate.resolve()
            )
        return BuildConfig(**values)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"Could not load profile: {exc}") from exc
