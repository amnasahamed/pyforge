"""Headless inspect/doctor/profile workflows and explicitly trusted builds."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

from pyforge.build import BuildEngine, BuildEvent
from pyforge.config import BuildConfig, ConfigError, load_profile, save_profile
from pyforge.dependencies import inspect_dependencies
from pyforge.diagnostics import run_doctor


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ConfigError(message)


def _config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "script", nargs="?", type=Path, help="Existing Python entry script (not an executable spec)"
    )
    parser.add_argument(
        "--profile", type=Path, help="Load inert JSON settings; trust is never stored"
    )
    parser.add_argument("--name")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--target", choices=("auto", "windows", "macos", "linux"))
    parser.add_argument("--mode", choices=("onedir", "onefile"))
    console = parser.add_mutually_exclusive_group()
    console.add_argument("--console", dest="console", action="store_true", default=None)
    console.add_argument("--no-console", dest="console", action="store_false")
    parser.add_argument("--icon", type=Path)
    parser.add_argument("--version", help="Application version, not the PyForge version")
    parser.add_argument("--description")
    parser.add_argument("--bundle-identifier")
    parser.add_argument("--hidden-import", action="append", dest="hidden_imports")
    parser.add_argument("--timeout", type=int, help="Timeout in seconds (10–86400)")
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable JSON object")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pyforge",
        description="Inspect and package trusted Python projects. Builds may execute project code and hooks; PyForge never installs project dependencies.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect", help="Read-only AST dependency inspection; never imports the project"
    )
    inspect.add_argument("script", type=Path)
    inspect.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Read-only configuration and environment diagnosis")
    _config_arguments(doctor)
    build = commands.add_parser("build", help="Package explicitly reviewed, trusted code")
    _config_arguments(build)
    build.add_argument(
        "--trust-code",
        action="store_true",
        help="Acknowledge that project code and PyInstaller hooks may execute",
    )
    profile = commands.add_parser("profile", help="Manage inert, versioned JSON configuration")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    save = profile_commands.add_parser("save", help="Save validated settings without building")
    save.add_argument("profile_path", type=Path)
    _config_arguments(save)
    return parser


def _configuration(args: argparse.Namespace, *, validate: bool = True) -> BuildConfig:
    if args.profile and args.script:
        raise ConfigError("Choose either an entry script or --profile, not both.")
    if args.profile:
        config = load_profile(args.profile)
    elif args.script:
        script = args.script.expanduser().resolve()
        config = BuildConfig(script=script, output_dir=script.parent / "dist", name=script.stem)
    else:
        raise ConfigError("Provide an entry script or --profile.")
    changes = {
        key: value
        for key in (
            "name",
            "output_dir",
            "target",
            "mode",
            "console",
            "icon",
            "version",
            "description",
            "bundle_identifier",
            "hidden_imports",
            "timeout",
        )
        if (value := getattr(args, key)) is not None
    }
    if "hidden_imports" in changes:
        changes["hidden_imports"] = tuple(changes["hidden_imports"])
    config = replace(config, **changes)
    if not validate:
        return config
    errors = config.validate()
    if errors:
        raise ConfigError("\n".join(errors))
    return config.normalized()


def _output(data: dict[str, Any], *, as_json: bool, lines: list[str]) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("\n".join(lines))


def main(argv: Sequence[str] | None = None) -> int:
    """Return a process status; importing this module does not start a GUI/build."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    as_json = "--json" in arguments
    try:
        args = _parser().parse_args(arguments)
        if args.command == "inspect":
            report = inspect_dependencies(args.script)
            failed = not report.entry_inspected or any(
                issue.startswith(("Entry script", "Cannot parse", "Cannot enumerate"))
                for issue in report.issues
            )
            data = {"ok": not failed, **report.to_dict()}
            lines = [
                f"Inspected {report.files_scanned} Python files without executing project code.",
                *(
                    f"{item.name}: {item.kind}"
                    + (f" ({', '.join(item.distributions)})" if item.distributions else "")
                    for item in report.imports
                ),
                *(f"Warning: {issue}" for issue in report.issues),
            ]
            _output(data, as_json=args.json, lines=lines)
            return 1 if failed else 0
        config = _configuration(args, validate=args.command != "doctor")
        if args.command == "doctor":
            doctor = run_doctor(config)
            lines = [
                "Build Doctor: " + ("ready" if doctor.ok else "needs attention"),
                *(
                    f"{finding.severity.upper()}: {finding.message}\n  {finding.recovery}"
                    for finding in doctor.findings
                ),
            ]
            _output(doctor.to_dict(), as_json=args.json, lines=lines)
            return 0 if doctor.ok else 1
        if args.command == "profile":
            save_profile(config, args.profile_path)
            path = args.profile_path.expanduser().resolve()
            _output(
                {"ok": True, "profile": str(path)},
                as_json=args.json,
                lines=[
                    f"Saved settings: {path}",
                    "No project code executed. Trust must be granted separately for each build.",
                ],
            )
            return 0

        def on_event(event: BuildEvent) -> None:
            if not args.json and event.kind in ("stage", "log"):
                print(event.message, file=sys.stderr)

        engine = BuildEngine()
        result = engine.build(config, trusted=args.trust_code, on_event=on_event)
        lines = [f"Build: {result.status}"]
        if result.artifact:
            lines.append(f"Artifact: {result.artifact}")
        if result.report_path:
            lines.append(f"Report: {result.report_path}")
        lines.extend(f"Error: {error}" for error in result.errors)
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
        _output(result.to_dict(), as_json=args.json, lines=lines)
        return {"success": 0, "cancelled": 130, "timeout": 124, "untrusted": 2, "invalid": 2}.get(
            result.status, 1
        )
    except (ConfigError, OSError, ValueError) as exc:
        _output(
            {"ok": False, "status": "invalid", "errors": [str(exc)]},
            as_json=as_json,
            lines=[f"Error: {exc}"],
        )
        return 2
    except KeyboardInterrupt:
        _output(
            {"ok": False, "status": "cancelled", "errors": ["Interrupted."]},
            as_json=as_json,
            lines=["Interrupted."],
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
