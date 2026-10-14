"""Reviewed stdlib-only packaging fixture: no network, subprocesses or project imports."""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="A small, safe PyForge packaging example.")
    parser.add_argument("--name", default="World", help="Name to greet.")
    args = parser.parse_args()
    print(json.dumps({"message": f"Hello, {args.name}!", "marker": "PYFORGE_SMOKE_OK"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
