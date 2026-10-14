"""Build Doctor: read-only checks and actionable recovery guidance."""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pyforge.config import BuildConfig
from pyforge.dependencies import DependencyReport, inspect_dependencies
from pyforge.platform import host_target


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    recovery: str


@dataclass(frozen=True)
class DoctorReport:
    findings: list[Diagnostic]
    dependencies: DependencyReport

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "findings": [asdict(f) for f in self.findings],
            "dependencies": self.dependencies.to_dict(),
            "python": sys.executable,
            "host": platform.system(),
        }


def run_doctor(config: BuildConfig) -> DoctorReport:
    """Check configuration and interpreter metadata without invoking target code."""
    findings = [
        Diagnostic("error", "config", error, "Correct this setting and run Doctor again.")
        for error in config.validate()
    ]
    if getattr(sys, "frozen", False):
        findings.append(
            Diagnostic(
                "error",
                "frozen-runtime",
                "A frozen PyForge preview does not contain a Python build interpreter.",
                "Install and run PyForge in your project's reviewed Python virtual environment. External interpreter selection is not supported yet.",
            )
        )
    dependencies = inspect_dependencies(config.script)
    if not dependencies.entry_inspected:
        findings.append(
            Diagnostic(
                "error",
                "entry-not-inspected",
                "The entry script could not be statically inspected.",
                "Choose a readable, regular Python source file within the 2 MiB limit and fix its reported syntax/encoding errors.",
            )
        )
    for issue in dependencies.issues:
        severity = "error" if issue.startswith(("Cannot parse", "Entry script")) else "warning"
        findings.append(
            Diagnostic(
                severity,
                "inspection",
                issue,
                "Inspect the reported source; dynamic imports may need explicit hidden imports.",
            )
        )
    missing = [d.name for d in dependencies.imports if d.kind == "unresolved"]
    if missing:
        findings.append(
            Diagnostic(
                "warning",
                "dependencies",
                f"No installed distribution metadata found for: {', '.join(missing)}.",
                "Review optional/local imports, then install only trusted requirements in this interpreter's virtual environment. PyForge does not install them.",
            )
        )
    imports = {dep.name for dep in dependencies.imports}
    qt_bindings = sorted(imports & {"PyQt5", "PyQt6", "PySide2", "PySide6"})
    if len(qt_bindings) > 1:
        findings.append(
            Diagnostic(
                "warning",
                "qt-conflict",
                f"Multiple Qt bindings are imported: {', '.join(qt_bindings)}.",
                "PyInstaller rejects collecting multiple Qt bindings. Keep one binding per application/environment and review optional imports.",
            )
        )
    try:
        version = importlib.metadata.version("pyinstaller")
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1])
        if major != 6 or minor < 20:
            findings.append(
                Diagnostic(
                    "error",
                    "pyinstaller-version",
                    f"PyInstaller {version} is outside the supported range (>=6.20,<7).",
                    "Install the documented PyInstaller build extra in your virtual environment.",
                )
            )
        else:
            findings.append(
                Diagnostic(
                    "info",
                    "pyinstaller",
                    f"PyInstaller {version}; Python {platform.python_version()} at {sys.executable}",
                    "Use this same interpreter for reviewed project dependencies.",
                )
            )
    except importlib.metadata.PackageNotFoundError:
        findings.append(
            Diagnostic(
                "error",
                "pyinstaller-missing",
                "PyInstaller is not installed in the current Python environment.",
                f'Run "{sys.executable}" -m pip install "pyinstaller>=6.20,<7" in a virtual environment after reviewing the package.',
            )
        )
    except (ValueError, IndexError, OSError) as exc:
        findings.append(
            Diagnostic(
                "error",
                "pyinstaller-metadata",
                f"Cannot validate PyInstaller metadata: {exc}",
                "Repair the virtual environment and reinstall the documented build extra.",
            )
        )
    target = host_target() if config.target == "auto" else config.target
    if target == "linux" and not config.console:
        findings.append(
            Diagnostic(
                "warning",
                "linux-windowed",
                "PyInstaller ignores windowed mode on Linux.",
                "Use console mode or ensure your GUI handles terminal-free startup itself.",
            )
        )
    if target == "macos" and config.mode == "onefile" and not config.console:
        findings.append(
            Diagnostic(
                "warning",
                "macos-onefile",
                "Onefile .app bundles extract on each launch and are not suitable for sandboxed Mac App Store distribution.",
                "Prefer onedir for macOS .app bundles.",
            )
        )
    try:
        ancestor: Path = config.output_dir.expanduser().resolve()
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        free = shutil.disk_usage(ancestor).free
        if free < 512 * 1024 * 1024:
            findings.append(
                Diagnostic(
                    "warning",
                    "disk-space",
                    f"Only {free // (1024 * 1024)} MiB free in the output filesystem.",
                    "Free disk space or choose another output directory; large dependencies may need several GiB.",
                )
            )
    except (OSError, RuntimeError) as exc:
        findings.append(
            Diagnostic(
                "warning",
                "disk-space",
                f"Cannot check free disk space: {exc}",
                "Check the output filesystem manually.",
            )
        )
    return DoctorReport(findings, dependencies)
