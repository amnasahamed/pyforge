"""Bounded AST dependency inspection with no imports, installs or network lookups."""

from __future__ import annotations

import ast
import importlib.metadata
import io
import os
import stat
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pyforge.config import MAX_SCRIPT_BYTES

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".pyforge",
}
MAX_FILES = 500
MAX_DIRECTORIES = 2000
MAX_TOTAL_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str
    distributions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyReport:
    imports: list[Dependency]
    issues: list[str]
    files_scanned: int
    entry_inspected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_dependencies(script: Path) -> DependencyReport:
    """Scan entry script and sibling project files without executing Python code.

    Import-to-distribution mapping is from this interpreter's installed metadata only.
    Dynamic/optional imports and custom importers require human review.
    """
    try:
        script = script.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return DependencyReport([], [f"Entry script cannot be resolved: {exc}"], 0)
    root = script.parent
    issues: list[str] = []
    imports: set[str] = set()
    local: set[str] = set()
    files: list[Path] = []
    if not script.is_file():
        return DependencyReport([], [f"Entry script does not exist: {script}"], 0)
    try:
        for item in root.iterdir():
            if item.is_symlink():
                continue
            if item.suffix == ".py" and item.is_file():
                local.add(item.stem)
            elif item.is_dir() and item.name not in SKIP_DIRS and not item.name.startswith("."):
                local.add(item.name)
        for visited, (directory, dirs, names) in enumerate(
            os.walk(
                root,
                followlinks=False,
                onerror=lambda exc: issues.append(f"Cannot enumerate project files: {exc}"),
            ),
            start=1,
        ):
            if visited > MAX_DIRECTORIES:
                issues.append(
                    f"Inspection stopped at {MAX_DIRECTORIES} directories; narrow the project directory."
                )
                break
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in SKIP_DIRS
                and not d.startswith(".")
                and not (Path(directory) / d).is_symlink()
            )
            for name in sorted(names):
                candidate = Path(directory) / name
                if candidate.suffix == ".py" and not candidate.is_symlink():
                    if not stat.S_ISREG(candidate.lstat().st_mode):
                        issues.append(
                            f"Skipped non-regular Python path: {candidate.relative_to(root)}"
                        )
                        continue
                    files.append(candidate)
                    if len(files) >= MAX_FILES:
                        break
            if len(files) >= MAX_FILES:
                issues.append(
                    f"Inspection stopped at {MAX_FILES} files; narrow the project directory."
                )
                break
        # Always inspect the entry first, even if the directory exceeds the scan bound.
        files = [script, *(p for p in files if p != script)][:MAX_FILES]
    except OSError as exc:
        issues.append(f"Cannot enumerate project files: {exc}")
        files = [script]
    count = 0
    entry_inspected = False
    total_bytes = 0
    for path in files:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    issues.append(f"Skipped non-regular Python path: {path.relative_to(root)}")
                    continue
                if info.st_size > MAX_SCRIPT_BYTES:
                    issues.append(f"Skipped oversized Python file: {path.name}")
                    continue
                content = handle.read(MAX_SCRIPT_BYTES + 1)
            size = len(content)
            if size > MAX_SCRIPT_BYTES:
                issues.append(f"Skipped oversized Python file: {path.name}")
                continue
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                issues.append(
                    "Inspection stopped at the 32 MiB total source limit; narrow the project directory."
                )
                break
            encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
            source = content.decode(encoding)
            tree = ast.parse(source, filename=str(path))
            count += 1
            if path == script:
                entry_inspected = True
        except (OSError, UnicodeError, SyntaxError, LookupError, RecursionError, ValueError) as exc:
            issues.append(f"Cannot parse {path.relative_to(root)}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Name) and func.id == "__import__") or (
                    isinstance(func, ast.Attribute) and func.attr == "import_module"
                ):
                    issues.append(
                        f"Dynamic import in {path.relative_to(root)}:{node.lineno}; review hidden imports manually."
                    )
    try:
        distributions = importlib.metadata.packages_distributions()
    except (OSError, ValueError) as exc:
        distributions = {}
        issues.append(f"Installed package metadata unavailable: {exc}")
    stdlib = sys.stdlib_module_names | set(sys.builtin_module_names)
    for name in sorted(local & stdlib):
        issues.append(
            f"Local module {name!r} shadows a standard-library name; rename it to avoid packaging/import conflicts."
        )
    dependencies = []
    for name in sorted(imports):
        providers = tuple(sorted(distributions.get(name, [])))
        kind = (
            "local"
            if name in local
            else "stdlib"
            if name in stdlib
            else "installed"
            if providers
            else "unresolved"
        )
        dependencies.append(Dependency(name, kind, providers))
    return DependencyReport(dependencies, list(dict.fromkeys(issues)), count, entry_inspected)
