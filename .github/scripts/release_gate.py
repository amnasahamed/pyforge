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
    with Path("pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]
    if package_version != version:
        raise SystemExit("Requested version disagrees with pyproject.toml.")
    print(
        f"Manual inputs/license presence accepted for {version} at {current}; rights remain maintainer-attested."
    )


if __name__ == "__main__":
    main()
