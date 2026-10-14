"""Build an explicitly UI-only frozen PyForge developer preview, never a release."""

from __future__ import annotations

import json
import platform
import tarfile
import zipfile
from pathlib import Path

from pyforge import __version__
from pyforge.build import BuildEngine
from pyforge.config import BuildConfig
from pyforge.platform import host_target


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    output = root / "artifacts" / "gui-preview"
    target = host_target()
    # A 0.x project version is invalid as CFBundleVersion. Record this preview's
    # compatibility bundle version separately; it is not a project release version.
    native_version = __version__
    if target == "macos":
        major, minor, patch = __version__.split(".")
        native_version = f"{max(1, int(major))}.{minor}.{patch}"
    config = BuildConfig(
        script=root / "src" / "pyforge" / "gui_entry.py",
        output_dir=output,
        name="PyForge-UI-Preview",
        target=target,
        console=False,
        mode="onedir",
        version=native_version,
        description=f"PyForge {__version__}: unsigned UI-only preview; builds require source/venv installation",
        bundle_identifier="org.example.pyforge.uipreview",
        timeout=1200,
    )
    result = BuildEngine().build(config, trusted=True)
    if not result.success or result.artifact is None:
        raise SystemExit(json.dumps(result.to_dict(), indent=2))
    artifact = Path(result.artifact)
    notice = output / "PREVIEW-NOTICE.txt"
    notice.write_text(
        "UNSIGNED UI-ONLY DEVELOPER PREVIEW. Not a public release or standalone build tool.\n"
        "Doctor blocks frozen packaging because the executable is not a Python interpreter.\n"
        "Install PyForge from source/in a virtual environment to package projects.\n"
        "Project/PyQt/Qt/dependency licensing must be resolved before redistribution.\n",
        encoding="utf-8",
    )
    manifest = output / "preview-environment.json"
    manifest.write_text(
        json.dumps(
            {
                "version": __version__,
                "native_bundle_version": native_version,
                "platform": platform.platform(),
                "target": config.target,
                "ui_only": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    archive_name = f"PyForge-{__version__}-{config.target}-UI-ONLY-UNSIGNED"
    if config.target == "windows":
        archive_path = output / f"{archive_name}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(artifact.rglob("*")):
                if item.is_file():
                    archive.write(item, Path(artifact.name) / item.relative_to(artifact))
            archive.write(notice, notice.name)
            archive.write(manifest, manifest.name)
    else:
        archive_path = output / f"{archive_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz", dereference=False) as archive:
            archive.add(artifact, arcname=artifact.name)
            archive.add(notice, arcname=notice.name)
            archive.add(manifest, arcname=manifest.name)
    print(f"UI-only unsigned preview: {archive_path}")


if __name__ == "__main__":
    main()
