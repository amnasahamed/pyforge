"""Capture the actual Qt GUI and read-only Doctor. Building is optional and explicit.

Run after installing the GUI/build extras:
    QT_QPA_PLATFORM=offscreen python tools/capture_screenshots.py
Add --build-reviewed-example to also package the repository's reviewed CLI
fixture and capture actual result/log views. The artifact is never launched.
No mock UI, rendered HTML or generated imagery is used.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from pyforge.config import BuildConfig  # noqa: E402
from pyforge.gui import PyForgeWindow  # noqa: E402


def _wait_until_idle(app: QApplication, window: PyForgeWindow, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    exceeded = False
    while window.is_busy:
        app.processEvents()
        time.sleep(0.01)
        if time.monotonic() >= deadline:
            exceeded = True
            # Cancellation cleans the process tree. Read-only Doctor has no
            # unsafe terminate operation; keep its window alive until it exits.
            if window._build_worker is not None:
                window.cancel_build()
    app.processEvents()
    if exceeded:
        raise RuntimeError("Operation exceeded screenshot deadline; workers were drained safely")


def capture(output: Path, script: Path, *, build_reviewed_example: bool = False) -> list[Path]:
    if (
        build_reviewed_example
        and script.resolve() != (ROOT / "examples" / "hello_cli.py").resolve()
    ):
        raise ValueError(
            "Build captures only support the repository's reviewed hello_cli.py fixture"
        )
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = PyForgeWindow()
    window.resize(1280, 1020)
    window.set_config(
        BuildConfig(
            script=script.resolve(),
            output_dir=ROOT / "dist",
            name="HelloPyForge",
            version="1.0.0",
            description="A reviewed native Python example",
        )
    )
    window.show()
    output.mkdir(parents=True, exist_ok=True)
    screenshots: list[Path] = []
    for theme in ("light", "dark"):
        window.theme_combo.setCurrentText(theme.capitalize())
        app.processEvents()
        path = output / f"configure-{theme}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Failed to save {path}")
        screenshots.append(path)
    window.start_doctor()
    _wait_until_idle(app, window, 60)
    for theme in ("light", "dark"):
        window.theme_combo.setCurrentText(theme.capitalize())
        app.processEvents()
        path = output / f"doctor-{theme}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Failed to save {path}")
        screenshots.append(path)
    if build_reviewed_example:
        # This opt-in applies only to the fixed, reviewed repository fixture.
        window.trust_check.setChecked(True)
        window.start_build()
        _wait_until_idle(app, window, 660)
        if window._last_result is None or not window._last_result.success:
            raise RuntimeError(f"Reviewed example build failed: {window.result_detail.text()}")
        for page, name in ((3, "result"), (2, "log")):
            window.show_page(page)
            for theme in ("light", "dark"):
                window.theme_combo.setCurrentText(theme.capitalize())
                app.processEvents()
                path = output / f"{name}-{theme}.png"
                if not window.grab().save(str(path)):
                    raise RuntimeError(f"Failed to save {path}")
                screenshots.append(path)
        print(f"Verified real GUI build: {window.artifact_edit.text()}")
    window.close()
    app.processEvents()
    return screenshots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "screenshots")
    parser.add_argument("--script", type=Path, default=ROOT / "examples" / "hello_cli.py")
    parser.add_argument(
        "--build-reviewed-example",
        action="store_true",
        help="Explicitly package only the reviewed hello_cli.py fixture; never launch it",
    )
    args = parser.parse_args()
    if not args.script.is_file():
        parser.error(f"Entry script does not exist: {args.script}")
    for path in capture(
        args.output, args.script, build_reviewed_example=args.build_reviewed_example
    ):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
