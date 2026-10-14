"""Read built archives without extracting/executing their contents."""

from __future__ import annotations

import configparser
import email
import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    wheels = list(Path("dist").glob("*.whl"))
    sdists = list(Path("dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("Expected exactly one source distribution and one wheel in dist/.")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        required = {"pyforge/__init__.py", "pyforge/cli.py", "pyforge/gui.py", "pyforge/py.typed"}
        if not required <= set(names):
            raise SystemExit("Wheel is missing required package modules/type marker.")
        if any(Path(name).name in {"forge.ico", "forge.icns", "forge.png"} for name in names):
            raise SystemExit("Uncleared original forge assets must not be bundled.")
        entrypoint = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entrypoint).decode("utf-8"))
        if parser["console_scripts"]["pyforge"] != "pyforge.cli:main":
            raise SystemExit("Missing or incorrect Qt-free CLI entry point.")
        if parser["gui_scripts"]["pyforge-gui"] != "pyforge.gui:main":
            raise SystemExit("Missing or incorrect GUI entry point.")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
        if metadata["Requires-Python"] != ">=3.10":
            raise SystemExit("Wheel Python baseline disagrees with documented support.")
        if not {"gui", "build", "dev"} <= set(metadata.get_all("Provides-Extra", [])):
            raise SystemExit("Wheel is missing documented optional extras.")
    with tarfile.open(sdists[0], "r:gz") as archive:
        names = archive.getnames()
        if any(
            Path(name).name in {"forge.ico", "forge.icns", "forge.png", "ignore"} for name in names
        ):
            raise SystemExit("Historical/uncleared assets must not be in the sdist.")
        required_suffixes = {"/README.md", "/docs/LICENSING.md", "/examples/hello_cli.py"}
        if any(not any(name.endswith(suffix) for name in names) for suffix in required_suffixes):
            raise SystemExit("Source distribution is missing documentation/reviewed examples.")
    print(
        f"Verified {wheels[0].name} and {sdists[0].name}: package layout, entry points, extras, asset exclusions."
    )


if __name__ == "__main__":
    main()
