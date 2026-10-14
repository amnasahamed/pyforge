"""Repository-root launchers must not shadow the package or silently start Qt."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_module_cli_from_checkout_without_qt() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pyforge", "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "inspect" in completed.stdout and "doctor" in completed.stdout
    assert "QApplication" not in completed.stderr


def test_package_import_from_checkout_without_qt() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pyforge; import pyforge.cli; assert pyforge.__version__ == '0.2.0'; assert 'PyQt5.QtWidgets' not in sys.modules; assert hasattr(pyforge, '__path__')",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
