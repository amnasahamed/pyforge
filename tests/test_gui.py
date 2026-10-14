"""Offscreen lifecycle and safety regression tests for the optional Qt GUI."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")
from PyQt5.QtCore import Qt, QThread  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from pyforge.config import BuildConfig  # noqa: E402
from pyforge.dependencies import Dependency, DependencyReport  # noqa: E402
from pyforge.diagnostics import Diagnostic, DoctorReport, run_doctor  # noqa: E402
from pyforge.gui import MAX_LOG_BLOCKS, MAX_LOG_LINE, PyForgeWindow  # noqa: E402
from pyforge.platform import host_target  # noqa: E402


def result(status="success", **kwargs):
    values = dict(
        success=status == "success",
        status=status,
        artifact=None,
        run_dir=None,
        report_path=None,
        elapsed_seconds=0.1,
        errors=(),
        warnings=(),
    )
    values.update(kwargs)
    return SimpleNamespace(**values)


class ControlledEngine:
    def __init__(self, *, hold=True, build_result=None, error=None):
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.calls = 0
        self.cancel_calls = 0
        self.hold = hold
        self.build_result = build_result or result()
        self.error = error
        self.config = None
        self.thread_id = None

    def build(self, config, *, trusted=False, on_event=None):
        assert trusted is True
        self.calls += 1
        self.config = config
        self.thread_id = threading.get_ident()
        self.started.set()
        if on_event:
            on_event(
                SimpleNamespace(kind="stage", message="Packaging the reviewed example", progress=35)
            )
        if self.hold:
            self.release.wait(5)
        if self.error:
            raise self.error
        return result("cancelled") if self.cancelled.is_set() else self.build_result

    def cancel(self):
        self.cancel_calls += 1
        self.cancelled.set()
        self.release.set()


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    application.setStyle("Fusion")
    return application


def wait_for(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            pytest.fail("Qt operation did not reach its expected state")
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def script(tmp_path):
    entry = tmp_path / "hello.py"
    entry.write_text('print("reviewed example")\n', encoding="utf-8")
    return entry


@pytest.fixture
def window(app, script, tmp_path, monkeypatch):
    engines = []

    def factory():
        engine = ControlledEngine()
        engines.append(engine)
        return engine

    win = PyForgeWindow(engine_factory=factory)
    win.set_config(BuildConfig(script, tmp_path / "output", "HelloApp"))
    win.errors_seen = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: win.errors_seen.append((title, message)),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    win.show()
    app.processEvents()
    yield win, engines
    if win._build_worker is not None:
        win.cancel_build()
    wait_for(app, lambda: not win.is_busy)
    win.close()
    app.processEvents()


def test_initial_trust_disabled_and_no_automatic_work(window):
    win, engines = window
    assert not win.build_button.isEnabled()
    assert not win.trust_check.isChecked()
    assert not win.is_busy
    assert not engines
    assert win.log_edit.toPlainText() == ""


def test_build_requires_explicit_trust_even_direct_invocation(window):
    win, engines = window
    win.start_build()
    assert not engines
    assert not win.is_busy
    assert "sandbox" in win.message_label.text()
    assert win.pages.currentIndex() == 0


def test_repeated_build_clicks_create_exactly_one_worker(window, app):
    win, engines = window
    win.trust_check.setChecked(True)
    for _ in range(8):
        win.start_build()
    wait_for(app, lambda: engines[0].started.is_set())
    assert len(engines) == 1
    assert engines[0].calls == 1
    assert win.is_busy
    assert not win.load_profile_button.isEnabled()
    assert not win.save_profile_button.isEnabled()
    assert not win.doctor_button.isEnabled()
    assert not win.build_button.isEnabled()
    assert not win.script_edit.isEnabled()
    engines[0].release.set()
    wait_for(app, lambda: not win.is_busy)
    assert win._last_result.success
    assert win.result_title.text() == "Build complete"
    assert win.build_button.isEnabled()
    assert win.findChildren(QThread) == []


def test_cancellation_is_real_and_idempotent(window, app):
    win, engines = window
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: engines[0].started.is_set())
    win.cancel_build()
    win.cancel_build()
    assert engines[0].cancel_calls == 1
    wait_for(app, lambda: not win.is_busy)
    assert win._last_result.status == "cancelled"
    assert not win.cancel_button.isEnabled()
    assert win.result_title.text() == "Build cancelled"


def test_cancel_before_worker_starts_does_not_execute_build(app, script, tmp_path):
    from pyforge.gui import _BuildWorker

    win = PyForgeWindow()
    engine = ControlledEngine()
    worker = _BuildWorker(BuildConfig(script, tmp_path / "out", "Example"), engine, win)
    completed = []
    worker.job_completed.connect(completed.append)
    worker.cancel()
    worker.start()
    wait_for(app, lambda: worker.isFinished())
    assert engine.calls == 0
    assert completed[0].status == "cancelled"
    worker.deleteLater()
    win.close()
    app.processEvents()


def test_can_rebuild_after_completion(window, app):
    win, engines = window
    win.trust_check.setChecked(True)
    for count in (1, 2):
        win.start_build()
        wait_for(
            app, lambda expected=count: len(engines) == expected and engines[-1].started.is_set()
        )
        engines[-1].release.set()
        wait_for(app, lambda: not win.is_busy)
    assert len(engines) == 2
    assert win.findChildren(QThread) == []


def test_ui_receives_worker_events_on_main_thread(window, app):
    win, engines = window
    received = []
    original = win._append_log

    def record(text):
        received.append(threading.get_ident())
        original(text)

    win._append_log = record
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: "Packaging the reviewed example" in win.log_edit.toPlainText())
    assert received
    assert set(received) == {threading.get_ident()}
    assert engines[0].thread_id != threading.get_ident()
    win.cancel_build()
    wait_for(app, lambda: not win.is_busy)


def test_worker_exception_is_a_failed_job_not_a_dead_thread(window, app):
    win, _ = window
    win.engine_factory = lambda: ControlledEngine(
        hold=False, error=RuntimeError("controlled failure")
    )
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: not win.is_busy)
    assert win._last_result.status == "failed"
    assert "controlled failure" in win.result_detail.text()
    assert win.build_button.isEnabled()
    assert win.findChildren(QThread) == []


def test_close_running_build_decline_then_cancel(window, app, monkeypatch):
    win, engines = window
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: engines[0].started.is_set())
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    win.close()
    app.processEvents()
    assert win.isVisible()
    assert win.is_busy
    assert not engines[0].cancelled.is_set()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    win.close()
    wait_for(app, lambda: not win.is_busy and not win.isVisible())
    assert engines[0].cancelled.is_set()
    assert win.findChildren(QThread) == []


def test_close_waits_for_read_only_doctor_without_terminating_thread(window, app):
    win, _ = window
    started, release = threading.Event(), threading.Event()

    def doctor(config):
        started.set()
        release.wait(3)
        return DoctorReport([], DependencyReport([], [], 1))

    win.doctor = doctor
    win.start_doctor()
    wait_for(app, started.is_set)
    win.close()
    assert win.isVisible()
    assert win._close_pending
    assert not win.build_button.isEnabled()
    release.set()
    wait_for(app, lambda: not win.is_busy and not win.isVisible())
    assert win.findChildren(QThread) == []


def test_doctor_repeated_requests_run_once_and_populate_tables(window, app):
    win, engines = window
    started, release = threading.Event(), threading.Event()
    calls = []

    def doctor(config):
        calls.append(config)
        started.set()
        release.wait(3)
        return DoctorReport(
            [Diagnostic("warning", "dynamic", "Review dynamic imports", "Add hidden imports")],
            DependencyReport([Dependency("json", "stdlib")], [], 2),
        )

    win.doctor = doctor
    for _ in range(5):
        win.start_doctor()
    wait_for(app, started.is_set)
    assert len(calls) == 1
    assert not engines
    assert not win.trust_check.isChecked()
    release.set()
    wait_for(app, lambda: not win.is_busy)
    assert win.findings_table.rowCount() == 1
    assert win.dependencies_table.item(0, 0).text() == "json"
    assert "2 files" in win.doctor_summary.text()


def test_inspection_error_recovers_controls(window, app):
    win, _ = window

    def doctor(config):
        raise RuntimeError("cannot inspect")

    win.doctor = doctor
    win.start_doctor()
    wait_for(app, lambda: not win.is_busy)
    assert win.doctor_summary.text() == "Inspection failed"
    assert "cannot inspect" in win.message_label.text()
    assert win.doctor_button.isEnabled()


def test_real_doctor_does_not_import_or_execute_entry(window, app, tmp_path):
    win, engines = window
    marker = tmp_path / "must-not-exist.txt"
    entry = tmp_path / "evil.py"
    entry.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
    win.script_edit.setText(str(entry))
    win.doctor = run_doctor
    win.start_doctor()
    wait_for(app, lambda: not win.is_busy, timeout=15)
    assert not marker.exists()
    assert not engines
    assert win._doctor_report is not None
    assert win._doctor_report.dependencies.files_scanned >= 1


def test_validation_cannot_start_engine(window, tmp_path):
    win, engines = window
    win.script_edit.setText(str(tmp_path / "missing.py"))
    win.trust_check.setChecked(True)
    win.start_build()
    assert not engines
    assert win.errors_seen
    assert not win.is_busy


@pytest.mark.parametrize("name", ["../../escape", "CON", "Trailing ", "bad;command"])
def test_name_validation_not_silently_normalized(window, name):
    win, engines = window
    win.name_edit.setText(name)
    win.trust_check.setChecked(True)
    win.start_build()
    assert not engines
    assert win.errors_seen


def test_foreign_target_rejected_with_actionable_message(window):
    win, engines = window
    foreign = "windows" if host_target() != "windows" else "linux"
    win.target_combo.setCurrentIndex(win.target_combo.findData(foreign))
    win.trust_check.setChecked(True)
    win.start_build()
    assert not engines
    assert "does not cross-compile" in win.errors_seen[-1][1]


def test_any_settings_change_revokes_trust(window):
    win, _ = window
    for field, value in (
        (win.description_edit, "Updated"),
        (win.imports_edit, "json"),
        (win.name_edit, "OtherApp"),
    ):
        win.trust_check.setChecked(True)
        assert win.build_button.isEnabled()
        field.setText(value)
        assert not win.trust_check.isChecked()
        assert not win.build_button.isEnabled()


def test_profiles_round_trip_all_options_and_never_restore_trust(window, tmp_path):
    win, _ = window
    win.name_edit.setText("ProfileApp")
    win.version_edit.setText("2.3.4")
    win.description_edit.setText("Profile description")
    win.bundle_edit.setText("com.example.profile")
    win.imports_edit.setText("json, xml.etree json")
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("onefile"))
    win.console_check.setChecked(False)
    win.timeout_spin.setValue(123)
    win.trust_check.setChecked(True)
    profile = tmp_path / "settings.json"
    assert win.save_profile_path(profile)
    data = json.loads(profile.read_text())
    assert "trusted" not in data["config"]
    assert "trust" not in data["config"]
    win.name_edit.setText("ChangedApp")
    win.trust_check.setChecked(True)
    assert win.load_profile_path(profile)
    config = win.config_from_ui()
    assert config.name == "ProfileApp"
    assert config.version == "2.3.4"
    assert config.description == "Profile description"
    assert config.bundle_identifier == "com.example.profile"
    assert config.hidden_imports == ("json", "xml.etree")
    assert config.mode == "onefile"
    assert config.console is False
    assert config.timeout == 123
    assert not win.trust_check.isChecked()


def test_invalid_profile_does_not_partially_replace_settings(window, tmp_path):
    win, _ = window
    before = win.config_from_ui()
    profile = tmp_path / "invalid.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "config": {
                    "script": str(before.script),
                    "output_dir": str(before.output_dir),
                    "name": "NewApp",
                    "timeout": 2,
                },
            }
        )
    )
    assert not win.load_profile_path(profile)
    assert win.config_from_ui() == before
    assert win.errors_seen


def test_log_buffer_bounded_and_long_lines_truncated(window):
    win, _ = window
    win._append_log("x" * (MAX_LOG_LINE + 100))
    assert "[line truncated]" in win.log_edit.toPlainText()
    assert len(win.log_edit.toPlainText()) < MAX_LOG_LINE + 100
    win._append_log("\n".join(str(i) for i in range(MAX_LOG_BLOCKS + 20)))
    assert win.log_edit.blockCount() == MAX_LOG_BLOCKS


def test_result_never_auto_launches_artifact_and_folder_button_only_opens_folder(
    window, app, tmp_path, monkeypatch
):
    from pyforge.gui import QDesktopServices

    win, _ = window
    artifact = tmp_path / "out" / "HelloApp"
    artifact.parent.mkdir()
    artifact.write_bytes(b"artifact, not executed")
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True
    )
    win.engine_factory = lambda: ControlledEngine(
        hold=False, build_result=result(artifact=artifact, run_dir=artifact.parent)
    )
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: not win.is_busy)
    assert not opened
    assert win.copy_artifact_button.isEnabled()
    win.open_folder_button.click()
    # QUrl uses forward slashes on Windows; compare native path semantics while
    # still requiring exactly one folder open and never an artifact launch.
    assert [Path(path) for path in opened] == [artifact.parent]


def test_resize_theme_keyboard_navigation_and_shortcut_guard(window, app):
    win, engines = window
    win.resize(900, 660)
    win.theme_combo.setCurrentText("Dark")
    app.processEvents()
    assert win._theme == "dark"
    assert win.minimumWidth() == 900
    assert win.width() == 900
    assert win._config_grid.itemAtPosition(1, 0).widget() is win._packaging_card
    assert win.page_title.wordWrap()
    win.nav_buttons[1].click()
    assert win.pages.currentIndex() == 1
    assert win.nav_buttons[1].isChecked()
    assert not win.nav_buttons[0].isChecked()
    QTest.keyClick(win, Qt.Key_Return, Qt.ControlModifier)
    app.processEvents()
    assert not engines
    assert win.pages.currentIndex() == 0
    assert win.trust_check.accessibleName() == "Trust project before build"


def test_frozen_gui_fails_preflight_without_starting_another_process(window, app, monkeypatch):
    import sys

    from pyforge import build

    win, _ = window
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def unexpected_process(*args, **kwargs):
        raise AssertionError("A frozen GUI must not invoke itself as a Python interpreter")

    monkeypatch.setattr(build.subprocess, "Popen", unexpected_process)
    win.engine_factory = build.BuildEngine
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: not win.is_busy)
    assert win._last_result.status == "preflight_failed"
    assert any(
        "frozen" in error.lower() or "packaged" in error.lower()
        for error in win._last_result.errors
    )
    assert win.findChildren(QThread) == []


def test_direct_qt_shutdown_drains_workers_when_close_event_is_bypassed(window, app):
    win, engines = window
    win.trust_check.setChecked(True)
    win.start_build()
    wait_for(app, lambda: engines[0].started.is_set())
    owned = win._build_worker
    win.shutdown()
    assert engines[0].cancelled.is_set()
    assert owned.isFinished()
    assert not win.is_busy
    app.processEvents()
    assert win._last_result.status == "cancelled"
    assert all(child.isFinished() for child in win.findChildren(QThread))


def test_missing_gui_extra_is_actionable(tmp_path):
    """Load GUI with Qt deliberately unavailable, independently of this session."""
    import subprocess
    import sys

    code = """
import importlib.abc
import sys
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PyQt5" or fullname.startswith("PyQt5."):
            raise ImportError("Qt unavailable for regression test")
sys.meta_path.insert(0, BlockQt())
from pyforge.gui import main
raise SystemExit(main([]))
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "pyforge-tool[gui,build]" in completed.stderr
    assert "source checkout" in completed.stderr
