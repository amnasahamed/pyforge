"""Fail-closed manual release input/license/version gate; not legal verification."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import tomllib


def main() -> None:
    requested_commit = os.environ.get("RELEASE_COMMIT", "")
    version = os.environ.get("RELEASE_VERSION", "")
    if not re.fullmatch(r"[0-9a-f]{40}", requested_commit):
        raise SystemExit("RELEASE_COMMIT must be an exact lowercase 40-character commit SHA.")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("RELEASE_VERSION must be a numeric major.minor.patch candidate version.")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if current != requested_commit:
        raise SystemExit("Checked-out commit does not match the requested release candidate.")
    for key in ("PROJECT_LICENSE_ATTESTED", "DEPENDENCY_DISTRIBUTION_ATTESTED"):
        if os.environ.get(key) != "true":
            raise SystemExit(f"{key} must be explicitly affirmed after the release checklist.")
    license_path = Path("LICENSE")
    if not license_path.is_file():
        raise SystemExit(
            "Public release blocked: the project LICENSE grant has not been established."
        )
    grant = license_path.read_text(encoding="utf-8")
    if len(grant.strip()) < 100 or re.search(r"\b(?:TODO|TBD|placeholder)\b", grant, re.IGNORECASE):
        raise SystemExit("LICENSE must contain the actual, reviewed grant, not a placeholder.")
    normalized = " ".join(grant.split())
    if not normalized.startswith("MIT License Copyright") or any(
        required not in normalized
        for required in (
            "Permission is hereby granted, free of charge, to any person obtaining a copy",
            "The above copyright notice and this permission notice shall be included",
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
        )
    ):
        raise SystemExit("LICENSE does not have the reviewed MIT grant structure.")
    with Path("pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)["project"]
    if metadata.get("license") != "MIT":
        raise SystemExit("Package license metadata must match the reviewed MIT project grant.")
    legal_files = {"LICENSE", "NOTICE", "docs/LICENSING.md"}
    if not legal_files <= set(metadata.get("license-files", [])):
        raise SystemExit("Package license-files must preserve LICENSE and scope/legal notices.")
    if any(not Path(name).is_file() for name in legal_files):
        raise SystemExit("Project scope/legal notices are missing from the release candidate.")
    package_version = metadata["version"]
    if package_version != version:
        raise SystemExit("Requested version disagrees with pyproject.toml.")
    print(
        f"Manual inputs/MIT metadata and notices accepted for {version} at {current}; rights remain maintainer-attested."
    )


if __name__ == "__main__":
    main()
