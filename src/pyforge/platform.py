"""Native host capabilities; PyInstaller is never a cross-OS compiler."""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyforge.config import BuildConfig

TARGETS = ("windows", "macos", "linux")


def host_target() -> str:
    """Return the operating system which can actually run the build."""
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        _platform.system(), "unsupported"
    )


def resolve_target(target: str, host: str | None = None) -> str:
    current = host if host is not None else host_target()
    requested = current if target == "auto" else target
    if requested not in TARGETS:
        raise ValueError(f"Unsupported target {requested!r}; choose Windows, macOS or Linux.")
    if requested != current:
        raise ValueError(
            f"Cannot build {requested} artifacts on {current}. Run PyForge on a {requested} "
            "machine with the required Python environment; PyInstaller does not cross-compile."
        )
    return requested


def expected_artifact(config: BuildConfig, dist: Path) -> Path:
    target = config.target if config.target != "auto" else host_target()
    if target == "macos" and not config.console:
        return dist / f"{config.name}.app"
    if config.mode == "onedir":
        return dist / config.name
    suffix = ".exe" if target == "windows" else ""
    return dist / f"{config.name}{suffix}"
