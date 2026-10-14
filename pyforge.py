"""Compatibility launcher for source checkouts; prefer python -m pyforge."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from pyforge.gui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
