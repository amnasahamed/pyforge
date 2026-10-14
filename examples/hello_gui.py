"""Reviewed Qt fixture: a label, an optional smoke marker, and no network calls.

Only --marker-file explicitly writes a file, and only in --smoke-test mode.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


def main() -> int:
    parser = argparse.ArgumentParser(description="A small PyForge Qt packaging example.")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Exit after a short UI smoke test."
    )
    parser.add_argument("--marker-file", type=Path, help="Explicit smoke-test output file.")
    args = parser.parse_args()
    if args.marker_file and not args.smoke_test:
        parser.error("--marker-file requires --smoke-test")

    app = QApplication([sys.argv[0]])
    window = QWidget()
    window.setWindowTitle("Hello from PyForge")
    window.resize(420, 180)
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Hello from a packaged Python application!"))
    window.show()

    def complete_smoke_test() -> None:
        marker = "PYFORGE_GUI_SMOKE_OK"
        try:
            if args.marker_file:
                args.marker_file.write_text(marker + "\n", encoding="utf-8")
            if sys.stdout is not None:
                print(marker, flush=True)
        except OSError:
            app.exit(1)
            return
        app.quit()

    if args.smoke_test:
        QTimer.singleShot(150, complete_smoke_test)
    return int(app.exec_())


if __name__ == "__main__":
    raise SystemExit(main())
