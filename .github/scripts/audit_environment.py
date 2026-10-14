"""Export complete installed third-party pins; omit only the tested editable PyForge."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def export_requirements(output: Path) -> None:
    editable = json.loads(
        subprocess.check_output(
            [sys.executable, "-m", "pip", "list", "--editable", "--format=json"], text=True
        )
    )
    editable_names = {re.sub(r"[-_.]+", "-", item["name"]).lower() for item in editable}
    if editable_names != {"pyforge-tool"}:
        raise SystemExit(
            "Audit export requires only pyforge-tool as an editable project; unexpected/missing "
            f"editable distributions: {sorted(editable_names)}. Do not silently skip them."
        )
    requirements = subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze", "--all", "--exclude-editable"], text=True
    )
    lines = [line.strip() for line in requirements.splitlines() if line.strip()]
    if not lines or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][A-Za-z0-9.!+_-]*", line)
        for line in lines
    ):
        raise SystemExit("Expected only exact installed name==version pins, not URLs/local paths.")
    if any(
        re.sub(r"[-_.]+", "-", line.split("==", 1)[0]).lower() == "pyforge-tool" for line in lines
    ):
        raise SystemExit("Own editable package was unexpectedly included in third-party pins.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"Exported {len(lines)} third-party pins to {output}; only editable pyforge-tool omitted."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, nargs="?", default=Path("artifacts/audit-requirements.txt")
    )
    export_requirements(parser.parse_args().output)


if __name__ == "__main__":
    main()
