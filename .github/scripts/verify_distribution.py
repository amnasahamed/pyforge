"""Read built archives without extracting/executing their contents."""

from __future__ import annotations

import configparser
import email
import re
import stat
import tarfile
import zipfile
from collections.abc import Mapping
from email.message import Message
from pathlib import Path

LICENSE_FILES = ("LICENSE", "NOTICE", "docs/LICENSING.md")


def verify_license_metadata(metadata: Message, label: str) -> None:
    """Check declared archive terms/notices, not ownership or legal clearance."""
    version = metadata.get("Metadata-Version", "")
    if not re.fullmatch(r"\d+\.\d+", version) or tuple(map(int, version.split("."))) < (2, 4):
        raise SystemExit(f"{label} must use PEP 639-compatible core metadata (2.4 or newer).")
    if metadata.get_all("License-Expression", []) != ["MIT"]:
        raise SystemExit(f"{label} must declare exactly one License-Expression: MIT.")
    if metadata.get_all("License", []):
        raise SystemExit(f"{label} must not mix legacy License and License-Expression fields.")
    license_files = metadata.get_all("License-File", [])
    if len(license_files) != len(LICENSE_FILES) or set(license_files) != set(LICENSE_FILES):
        raise SystemExit(
            f"{label} must declare exactly these License-File headers: {LICENSE_FILES}."
        )


def verify_license_payloads(
    archived_files: Mapping[str, bytes], expected_files: Mapping[str, bytes], label: str
) -> None:
    """Require byte-for-byte copies of the checkout's grant and scope notices."""
    if set(archived_files) != set(LICENSE_FILES) or set(expected_files) != set(LICENSE_FILES):
        raise SystemExit(f"{label} is missing required project grant/scope files.")
    for name in LICENSE_FILES:
        if archived_files[name] != expected_files[name]:
            raise SystemExit(f"{label} legal file {name} differs from the reviewed checkout.")


def read_wheel_file(archive: zipfile.ZipFile, name: str) -> bytes:
    if archive.namelist().count(name) != 1:
        raise SystemExit(f"Wheel must contain exactly one regular file at {name}.")
    member = archive.getinfo(name)
    mode = member.external_attr >> 16
    if member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
        raise SystemExit(f"Wheel member {name} must be a regular file, not a link/directory.")
    return archive.read(member)


def read_sdist_file(archive: tarfile.TarFile, name: str) -> bytes:
    if archive.getnames().count(name) != 1:
        raise SystemExit(f"Source distribution must contain exactly one regular file at {name}.")
    member = archive.getmember(name)
    if not member.isfile():
        raise SystemExit(f"Source distribution member {name} must be a regular file.")
    handle = archive.extractfile(member)
    if handle is None:
        raise SystemExit(f"Cannot read required source distribution file {name}.")
    with handle:
        return handle.read()


def main() -> None:
    expected_files = {}
    for name in LICENSE_FILES:
        path = Path(name)
        if not path.is_file():
            raise SystemExit(f"Checkout is missing required project grant/scope file {name}.")
        expected_files[name] = path.read_bytes()
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
        metadata_names = [
            name for name in names if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise SystemExit("Wheel must contain exactly one root .dist-info/METADATA file.")
        metadata_name = metadata_names[0]
        metadata = email.message_from_bytes(read_wheel_file(archive, metadata_name))
        verify_license_metadata(metadata, "Wheel")
        info_prefix = metadata_name.removesuffix("METADATA")
        verify_license_payloads(
            {
                name: read_wheel_file(archive, f"{info_prefix}licenses/{name}")
                for name in LICENSE_FILES
            },
            expected_files,
            "Wheel",
        )
        entrypoint = f"{info_prefix}entry_points.txt"
        parser = configparser.ConfigParser()
        parser.read_string(read_wheel_file(archive, entrypoint).decode("utf-8"))
        if parser["console_scripts"]["pyforge"] != "pyforge.cli:main":
            raise SystemExit("Missing or incorrect Qt-free CLI entry point.")
        if parser["gui_scripts"]["pyforge-gui"] != "pyforge.gui:main":
            raise SystemExit("Missing or incorrect GUI entry point.")
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
        metadata_names = [
            name for name in names if name.count("/") == 1 and name.endswith("/PKG-INFO")
        ]
        if len(metadata_names) != 1:
            raise SystemExit("Source distribution must contain exactly one root PKG-INFO file.")
        metadata_name = metadata_names[0]
        metadata = email.message_from_bytes(read_sdist_file(archive, metadata_name))
        verify_license_metadata(metadata, "Source distribution")
        source_prefix = metadata_name.removesuffix("PKG-INFO")
        verify_license_payloads(
            {name: read_sdist_file(archive, f"{source_prefix}{name}") for name in LICENSE_FILES},
            expected_files,
            "Source distribution",
        )
    print(
        f"Verified {wheels[0].name} and {sdists[0].name}: package layout, entry points, extras, "
        "MIT archive metadata/grant/scope notices, asset exclusions; no legal clearance implied."
    )


if __name__ == "__main__":
    main()
