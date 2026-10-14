"""Accessible PyQt5 build studio for trusted, native Python projects.

The GUI is optional. Source inspection never imports a project; packaging is an
explicitly trusted operation and does not provide a sandbox.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyforge.config import BuildConfig, ConfigError, load_profile, save_profile
from pyforge.diagnostics import DoctorReport, run_doctor
from pyforge.platform import host_target

try:
    from PyQt5.QtCore import QPoint, Qt, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
    from PyQt5.QtGui import (
        QColor,
        QDesktopServices,
        QFont,
        QKeySequence,
        QPainter,
        QPalette,
        QPolygon,
    )
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QShortcut,
        QSpinBox,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True

MAX_LOG_BLOCKS = 2000
MAX_LOG_LINE = 8000


@dataclass(frozen=True)
class _WorkerFailure:
    """Surface an unexpected worker failure without losing lifecycle signals."""

    success: bool = False
    status: str = "failed"
    artifact: Path | None = None
    run_dir: Path | None = None
    report_path: Path | None = None
    elapsed_seconds: float = 0.0
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _default_engine() -> Any:
    from pyforge.build import BuildEngine

    return BuildEngine()


if QT_AVAILABLE:

    class _ComboBox(QComboBox):
        """A code-drawn chevron remains visible with both custom palettes."""

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.palette().color(QPalette.Text))
            x, y = self.width() - 15, self.height() // 2
            painter.drawPolygon(
                QPolygon([QPoint(x - 4, y - 2), QPoint(x + 4, y - 2), QPoint(x, y + 3)])
            )

    class _CheckBox(QCheckBox):
        """Keep unchecked boxes visible without shipping external icon assets."""

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            box_y = (self.height() - 17) // 2
            painter.setPen(self.palette().color(QPalette.Text))
            painter.setBrush(self.palette().color(QPalette.Base))
            painter.drawRoundedRect(1, box_y, 16, 16, 3, 3)
            if self.isChecked():
                pen = painter.pen()
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(5, box_y + 8, 8, box_y + 11)
                painter.drawLine(8, box_y + 11, 14, box_y + 5)

    class _BuildWorker(QThread):
        """Translate engine callbacks into queued Qt signals, never UI calls."""

        event_received = pyqtSignal(object)
        job_completed = pyqtSignal(object)

        def __init__(self, config: BuildConfig, engine: Any, parent: QWidget) -> None:
            super().__init__(parent)
            self.config = config
            self.engine = engine
            self.cancel_requested = threading.Event()
            self.result: Any = None

        def cancel(self) -> None:
            self.cancel_requested.set()
            self.engine.cancel()

        def run(self) -> None:
            try:
                if self.cancel_requested.is_set():
                    self.result = _WorkerFailure(status="cancelled")
                else:
                    self.result = self.engine.build(
                        self.config, trusted=True, on_event=self.event_received.emit
                    )
            except Exception as exc:
                self.result = _WorkerFailure(errors=(f"Build worker failed: {exc}",))
            self.job_completed.emit(self.result)

    class _DoctorWorker(QThread):
        job_completed = pyqtSignal(object)

        def __init__(
            self,
            config: BuildConfig,
            doctor: Callable[[BuildConfig], DoctorReport],
            parent: QWidget,
        ) -> None:
            super().__init__(parent)
            self.config = config
            self.doctor = doctor
            self.result: Any = None

        def run(self) -> None:
            try:
                self.result = self.doctor(self.config)
            except Exception as exc:
                self.result = _WorkerFailure(errors=(f"Read-only inspection failed: {exc}",))
            self.job_completed.emit(self.result)

    class PyForgeWindow(QMainWindow):
        """One-window workflow with explicit trust and guarded worker ownership."""

        def __init__(
            self,
            *,
            engine_factory: Callable[[], Any] = _default_engine,
            doctor: Callable[[BuildConfig], DoctorReport] = run_doctor,
        ) -> None:
            super().__init__()
            self.engine_factory = engine_factory
            self.doctor = doctor
            self._build_worker: _BuildWorker | None = None
            self._doctor_worker: _DoctorWorker | None = None
            self._close_pending = False
            self._last_result: Any = None
            self._doctor_report: DoctorReport | None = None
            self._theme = "light"
            self._profile_path: Path | None = None
            self._build_config: BuildConfig | None = None
            self.setWindowTitle("PyForge · Build studio")
            self.resize(1220, 900)
            self.setMinimumSize(900, 660)
            self._create_ui()
            self.apply_theme("light")
            self._wire_changes()
            self._update_summary()
            self._update_actions()

        @property
        def is_busy(self) -> bool:
            # Worker ownership, not isRunning(), guards the start/finish race.
            return self._build_worker is not None or self._doctor_worker is not None

        def _create_ui(self) -> None:
            root = QWidget()
            root.setObjectName("root")
            self.setCentralWidget(root)
            outer = QHBoxLayout(root)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            sidebar = QFrame()
            sidebar.setObjectName("sidebar")
            sidebar.setFixedWidth(212)
            side = QVBoxLayout(sidebar)
            side.setContentsMargins(24, 28, 20, 24)
            badge = QLabel("P / F")
            badge.setObjectName("brandMark")
            badge.setFixedSize(65, 54)
            badge.setAlignment(Qt.AlignCenter)
            side.addWidget(badge)
            brand = QLabel("PYFORGE")
            brand.setObjectName("brand")
            side.addWidget(brand)
            tagline = QLabel("BUILD STUDIO")
            tagline.setObjectName("sideKicker")
            side.addWidget(tagline)
            side.addSpacing(36)
            self.nav_buttons: list[QPushButton] = []
            for index, text in enumerate(
                ("01   Configure", "02   Build Doctor", "03   Build log", "04   Results")
            ):
                button = QPushButton(text)
                button.setObjectName("navButton")
                button.setCheckable(True)
                button.setMinimumHeight(48)
                button.clicked.connect(lambda checked=False, page=index: self.show_page(page))
                side.addWidget(button)
                self.nav_buttons.append(button)
            side.addStretch()
            side.addWidget(self._label("NATIVE BY DESIGN", "sideKicker"))
            self.host_label = self._label(
                f"{host_target().capitalize()} host\nPython {sys.version_info.major}.{sys.version_info.minor}",
                "sideMeta",
            )
            side.addWidget(self.host_label)
            side.addSpacing(16)
            side.addWidget(self._label("Review. Diagnose. Package.", "sideMeta"))
            outer.addWidget(sidebar)

            workspace = QWidget()
            work = QVBoxLayout(workspace)
            work.setContentsMargins(30, 25, 30, 22)
            work.setSpacing(18)
            header = QHBoxLayout()
            heading = QVBoxLayout()
            heading.setSpacing(3)
            heading.addWidget(self._label("REVIEW. DIAGNOSE. BUILD.", "kicker"))
            self.page_title = self._label("Configure your app", "pageTitle")
            self.page_title.setWordWrap(True)
            heading.addWidget(self.page_title)
            header.addLayout(heading)
            header.addStretch()
            self.load_profile_button = QPushButton("Load profile")
            self.load_profile_button.setToolTip(
                "Load inert JSON settings. Loading never grants build trust."
            )
            self.load_profile_button.clicked.connect(self._choose_load_profile)
            self.save_profile_button = QPushButton("Save profile")
            self.save_profile_button.clicked.connect(self._choose_save_profile)
            self.theme_combo = _ComboBox()
            self.theme_combo.addItems(["Light", "Dark"])
            self.theme_combo.setAccessibleName("Color theme")
            self.theme_combo.currentTextChanged.connect(
                lambda value: self.apply_theme(value.lower())
            )
            for widget in (self.load_profile_button, self.save_profile_button, self.theme_combo):
                header.addWidget(widget)
            work.addLayout(header)
            self.pages = QStackedWidget()
            self.pages.addWidget(self._configure_page())
            self.pages.addWidget(self._doctor_page())
            self.pages.addWidget(self._logs_page())
            self.pages.addWidget(self._results_page())
            work.addWidget(self.pages, 1)
            self.message_label = self._label(
                "Choose a Python entry script to begin.", "statusMessage"
            )
            self.message_label.setWordWrap(True)
            self.message_label.setAccessibleName("Workflow status")
            work.addWidget(self.message_label)
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(5)
            self.progress.setAccessibleName("Build progress")
            work.addWidget(self.progress)
            footer = QHBoxLayout()
            self.footer_note = self._label(
                "No automatic installs. Trusted builds only. No automatic app launch.", "muted"
            )
            self.footer_note.setWordWrap(True)
            footer.addWidget(self.footer_note, 1)
            self.doctor_button = QPushButton("Run Build Doctor")
            self.doctor_button.setMinimumHeight(43)
            self.doctor_button.clicked.connect(self.start_doctor)
            self.cancel_button = QPushButton("Cancel build")
            self.cancel_button.setMinimumHeight(43)
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_build)
            self.build_button = QPushButton("Build app")
            self.build_button.setObjectName("primary")
            self.build_button.setMinimumSize(138, 43)
            self.build_button.clicked.connect(self.start_build)
            footer.addWidget(self.doctor_button)
            footer.addWidget(self.cancel_button)
            footer.addWidget(self.build_button)
            work.addLayout(footer)
            outer.addWidget(workspace, 1)
            self.show_page(0)
            self._shortcuts: list[QShortcut] = []
            for sequence, callback in (
                ("Ctrl+O", self._choose_script),
                ("Ctrl+Shift+O", self._choose_load_profile),
                ("Ctrl+S", self._choose_save_profile),
                ("Ctrl+Return", self.start_build),
                ("Escape", self.cancel_build),
            ):
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)

        @staticmethod
        def _label(text: str, name: str = "") -> QLabel:
            label = QLabel(text)
            label.setTextFormat(Qt.PlainText)
            label.setObjectName(name)
            return label

        @staticmethod
        def _card(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(21, 18, 21, 20)
            layout.setSpacing(12)
            layout.addWidget(PyForgeWindow._label(title, "cardTitle"))
            if subtitle:
                label = PyForgeWindow._label(subtitle, "muted")
                label.setWordWrap(True)
                layout.addWidget(label)
            return card, layout

        @staticmethod
        def _field(placeholder: str, accessible_name: str) -> QLineEdit:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setAccessibleName(accessible_name)
            edit.setMinimumHeight(36)
            return edit

        @staticmethod
        def _path_row(edit: QLineEdit, button: QPushButton) -> QWidget:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(edit, 1)
            layout.addWidget(button)
            return row

        @staticmethod
        def _form() -> QFormLayout:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(11)
            return form

        def _configure_page(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setObjectName("pageScroll")
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(0, 0, 2, 0)
            layout.setSpacing(15)
            self.summary_label = self._label("", "summaryBanner")
            self.summary_label.setWordWrap(True)
            layout.addWidget(self.summary_label)
            grid = QGridLayout()
            grid.setHorizontalSpacing(15)
            grid.setVerticalSpacing(15)
            source, source_layout = self._card(
                "01  Source & destination", "Start with a trusted .py entry script."
            )
            source_form = self._form()
            self.script_edit = self._field("Choose your entry script…", "Python entry script")
            self.script_edit.setToolTip(
                "Only .py entry scripts are accepted. Inspection reads source without executing it."
            )
            self.browse_script_button = QPushButton("Browse…")
            self.browse_script_button.clicked.connect(self._choose_script)
            source_form.addRow(
                "&Entry script", self._path_row(self.script_edit, self.browse_script_button)
            )
            source_form.labelForField(
                source_form.itemAt(0, QFormLayout.FieldRole).widget()
            ).setBuddy(self.script_edit)
            self.output_edit = self._field("Build output directory", "Build output directory")
            self.output_edit.setText(str(Path.cwd() / "dist"))
            self.browse_output_button = QPushButton("Browse…")
            self.browse_output_button.clicked.connect(self._choose_output)
            source_form.addRow(
                "&Output folder", self._path_row(self.output_edit, self.browse_output_button)
            )
            source_form.labelForField(
                source_form.itemAt(1, QFormLayout.FieldRole).widget()
            ).setBuddy(self.output_edit)
            self.name_edit = self._field("MyApp", "App name")
            source_form.addRow("App &name", self.name_edit)
            self.version_edit = self._field("1.0.0", "App version")
            self.version_edit.setText("1.0.0")
            source_form.addRow("&Version", self.version_edit)
            source_layout.addLayout(source_form)
            source_layout.addStretch()
            grid.addWidget(source, 0, 0)

            packaging, pack_layout = self._card(
                "02  Native packaging", "Built on this machine, for this operating system."
            )
            pack_form = self._form()
            self.target_combo = _ComboBox()
            self.target_combo.setAccessibleName("Native target")
            self.target_combo.addItem(f"Automatic · {host_target().capitalize()}", "auto")
            for target in ("windows", "macos", "linux"):
                self.target_combo.addItem(target.capitalize(), target)
            self.target_combo.setToolTip(
                "Cross-OS compilation is not supported. Use a matching host for Windows, macOS or Linux."
            )
            pack_form.addRow("&Target", self.target_combo)
            self.mode_combo = _ComboBox()
            self.mode_combo.setAccessibleName("Bundle mode")
            self.mode_combo.addItem("Folder bundle · recommended", "onedir")
            self.mode_combo.addItem("Single executable", "onefile")
            pack_form.addRow("Bundle &mode", self.mode_combo)
            self.console_check = _CheckBox("Keep console window")
            self.console_check.setChecked(True)
            self.console_check.setToolTip(
                "For command-line apps. Windowed mode is ignored by PyInstaller on Linux."
            )
            pack_form.addRow("Startup", self.console_check)
            self.description_edit = self._field(
                "A short description of your app", "App description"
            )
            self.description_edit.setMaxLength(500)
            pack_form.addRow("&Description", self.description_edit)
            pack_layout.addLayout(pack_form)
            native_note = self._label(
                "Windows: .exe   ·   macOS: native app   ·   Linux: executable\nSigning and notarization remain separate release steps.",
                "muted",
            )
            native_note.setWordWrap(True)
            pack_layout.addWidget(native_note)
            pack_layout.addStretch()
            grid.addWidget(packaging, 0, 1)
            self._config_grid = grid
            self._packaging_card = packaging
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)

            advanced, advanced_layout = self._card(
                "03  Advanced settings",
                "Optional metadata and explicit imports. Nothing is installed automatically.",
            )
            advanced_form = self._form()
            self.icon_edit = self._field(
                "Optional native icon (.ico / .icns / .png)", "Native app icon"
            )
            self.browse_icon_button = QPushButton("Browse…")
            self.browse_icon_button.clicked.connect(self._choose_icon)
            advanced_form.addRow(
                "App &icon", self._path_row(self.icon_edit, self.browse_icon_button)
            )
            advanced_form.labelForField(
                advanced_form.itemAt(0, QFormLayout.FieldRole).widget()
            ).setBuddy(self.icon_edit)
            self.bundle_edit = self._field("com.example.myapp (optional)", "Bundle identifier")
            advanced_form.addRow("Bundle identifier", self.bundle_edit)
            self.imports_edit = self._field("package.module, another.module", "Hidden imports")
            self.imports_edit.setToolTip(
                "Comma- or whitespace-separated Python module names. Dynamic imports need manual review."
            )
            advanced_form.addRow("Hidden imports", self.imports_edit)
            self.timeout_spin = QSpinBox()
            self.timeout_spin.setRange(10, 86400)
            self.timeout_spin.setValue(600)
            self.timeout_spin.setSuffix(" seconds")
            self.timeout_spin.setAccessibleName("Build timeout")
            advanced_form.addRow("Timeout", self.timeout_spin)
            advanced_layout.addLayout(advanced_form)
            layout.addWidget(advanced)
            trust, trust_layout = self._card("Trust comes before packaging")
            trust.setObjectName("trustCard")
            self.trust_check = _CheckBox(
                "I trust this project, its dependencies and its PyInstaller hooks."
            )
            self.trust_check.setAccessibleName("Trust project before build")
            trust_layout.addWidget(self.trust_check)
            warning = self._label(
                "Building may execute hooks and project code with your account’s permissions. PyForge is not a sandbox. Only build reviewed projects. This trust choice is never saved in a profile.",
                "muted",
            )
            warning.setWordWrap(True)
            trust_layout.addWidget(warning)
            layout.addWidget(trust)
            layout.addStretch()
            scroll.setWidget(content)
            self._config_content = content
            self._config_scroll = scroll
            return scroll

        def _doctor_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(15)
            banner = self._label(
                "READ-ONLY CHECKUP  ·  Source is parsed, never imported. No package installs or network lookups.",
                "summaryBanner",
            )
            banner.setWordWrap(True)
            layout.addWidget(banner)
            card, card_layout = self._card(
                "Build readiness",
                "Run Build Doctor to validate configuration, interpreter and dependencies.",
            )
            self.doctor_summary = self._label("Not inspected yet", "cardTitle")
            card_layout.addWidget(self.doctor_summary)
            self.findings_table = self._table(["Level", "Finding", "Recovery"])
            self.findings_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeToContents
            )
            card_layout.addWidget(self.findings_table, 1)
            layout.addWidget(card, 3)
            deps, deps_layout = self._card(
                "Dependency overview",
                "Installed metadata is a clue, not a complete requirements lockfile. Review dynamic and optional imports.",
            )
            self.dependencies_table = self._table(
                ["Import", "Classification", "Installed distribution"]
            )
            deps_layout.addWidget(self.dependencies_table, 1)
            layout.addWidget(deps, 2)
            return page

        @staticmethod
        def _table(headers: list[str]) -> QTableWidget:
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setAlternatingRowColors(True)
            table.setWordWrap(True)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setMinimumHeight(120)
            return table

        def _logs_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            card, card_layout = self._card(
                "Live build output",
                "The latest 2,000 lines are shown here. A bounded build record is saved with the result.",
            )
            actions = QHBoxLayout()
            self.log_state = self._label("Waiting for a build", "muted")
            actions.addWidget(self.log_state, 1)
            copy = QPushButton("Copy visible log")
            copy.clicked.connect(
                lambda: QApplication.clipboard().setText(self.log_edit.toPlainText())
            )
            actions.addWidget(copy)
            self.clear_log_button = QPushButton("Clear view")
            self.clear_log_button.clicked.connect(
                lambda: self.log_edit.clear() if not self.is_busy else None
            )
            actions.addWidget(self.clear_log_button)
            card_layout.addLayout(actions)
            self.log_edit = QPlainTextEdit()
            self.log_edit.setReadOnly(True)
            self.log_edit.setMaximumBlockCount(MAX_LOG_BLOCKS)
            self.log_edit.setAccessibleName("Build log")
            self.log_edit.setObjectName("buildLog")
            self.log_edit.setFont(QFont("monospace", 10))
            card_layout.addWidget(self.log_edit, 1)
            layout.addWidget(card, 1)
            return page

        def _results_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(15)
            card, card_layout = self._card(
                "Your build record", "Artifacts are never opened or run automatically."
            )
            self.result_title = self._label("Nothing built yet", "resultTitle")
            self.result_title.setWordWrap(True)
            card_layout.addWidget(self.result_title)
            self.result_detail = self._label(
                "Complete a trusted build to see its status, artifact location and reproducible build record.",
                "muted",
            )
            self.result_detail.setWordWrap(True)
            card_layout.addWidget(self.result_detail)
            form = self._form()
            self.artifact_edit = self._field("Artifact path appears here", "Built artifact path")
            self.artifact_edit.setReadOnly(True)
            form.addRow("Artifact", self.artifact_edit)
            self.report_edit = self._field("Build report path appears here", "Build report path")
            self.report_edit.setReadOnly(True)
            form.addRow("Build report", self.report_edit)
            self.run_edit = self._field(
                "Isolated run directory appears here", "Build run directory"
            )
            self.run_edit.setReadOnly(True)
            form.addRow("Run directory", self.run_edit)
            card_layout.addLayout(form)
            actions = QHBoxLayout()
            self.open_folder_button = QPushButton("Open output folder")
            self.open_folder_button.setEnabled(False)
            self.open_folder_button.clicked.connect(self.open_output_folder)
            self.copy_artifact_button = QPushButton("Copy artifact path")
            self.copy_artifact_button.setEnabled(False)
            self.copy_artifact_button.clicked.connect(
                lambda: QApplication.clipboard().setText(self.artifact_edit.text())
            )
            actions.addWidget(self.open_folder_button)
            actions.addWidget(self.copy_artifact_button)
            actions.addStretch()
            card_layout.addLayout(actions)
            layout.addWidget(card)
            release, release_layout = self._card("Before you distribute")
            note = self._label(
                "Test the artifact in a clean environment on the matching OS. Review bundled dependencies and their licenses. Sign Windows apps or sign and notarize macOS apps separately. PyForge does not claim your app is safe or ready for distribution.",
                "muted",
            )
            note.setWordWrap(True)
            release_layout.addWidget(note)
            layout.addWidget(release)
            layout.addStretch()
            return page

        def _wire_changes(self) -> None:
            for edit in (
                self.script_edit,
                self.output_edit,
                self.name_edit,
                self.version_edit,
                self.icon_edit,
                self.bundle_edit,
                self.description_edit,
                self.imports_edit,
            ):
                edit.textChanged.connect(self._configuration_changed)
            for combo in (self.target_combo, self.mode_combo):
                combo.currentIndexChanged.connect(self._configuration_changed)
            self.console_check.toggled.connect(self._configuration_changed)
            self.timeout_spin.valueChanged.connect(self._configuration_changed)
            self.trust_check.toggled.connect(self._update_actions)

        @pyqtSlot()
        def _configuration_changed(self) -> None:
            # Re-affirm trust when any build input changes, not just the entry path.
            self.trust_check.setChecked(False)
            self._doctor_report = None
            self.doctor_summary.setText("Settings changed · run Doctor again")
            self._update_summary()
            self._update_actions()

        def _update_summary(self) -> None:
            name = self.name_edit.text().strip() or "Your app"
            target = self.target_combo.currentData()
            target = host_target() if target == "auto" else target
            mode = (
                "folder bundle"
                if self.mode_combo.currentData() == "onedir"
                else "single executable"
            )
            self.summary_label.setText(
                f"{name}  /  {str(target).capitalize()}  /  {mode}   ·   Native builds only"
            )

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            if hasattr(self, "_config_grid"):
                # The form becomes a single column on smaller laptop windows.
                # It remains vertically scrollable instead of clipping fields.
                self._config_grid.removeWidget(self._packaging_card)
                if self.width() < 1120:
                    self._config_grid.addWidget(self._packaging_card, 1, 0)
                    self._config_grid.setColumnStretch(1, 0)
                else:
                    self._config_grid.addWidget(self._packaging_card, 0, 1)
                    self._config_grid.setColumnStretch(1, 1)

        def show_page(self, page: int) -> None:
            self.pages.setCurrentIndex(page)
            for index, button in enumerate(self.nav_buttons):
                button.setChecked(index == page)
            self.page_title.setText(
                (
                    "Configure your app",
                    "Understand build readiness",
                    "Follow your build",
                    "Review the result",
                )[page]
            )

        def apply_theme(self, theme: str) -> None:
            self._theme = "dark" if theme == "dark" else "light"
            dark = self._theme == "dark"
            c = {
                "bg": "#101720" if dark else "#f3f5f8",
                "card": "#192330" if dark else "#ffffff",
                "text": "#edf2f8" if dark else "#182537",
                "muted": "#a8b7ca" if dark else "#57677d",
                "border": "#334356" if dark else "#dce3ec",
                "input": "#111b27" if dark else "#fbfcfe",
                "accent": "#73d9c6" if dark else "#126e61",
                "banner": "#153c39" if dark else "#e5f3ee",
                "alt": "#202d3c" if dark else "#f5f7fa",
            }
            palette = QPalette()
            for role, color in (
                (QPalette.Window, c["bg"]),
                (QPalette.WindowText, c["text"]),
                (QPalette.Base, c["input"]),
                (QPalette.AlternateBase, c["alt"]),
                (QPalette.Text, c["text"]),
                (QPalette.Button, c["card"]),
                (QPalette.ButtonText, c["text"]),
                (QPalette.Highlight, "#177968"),
                (QPalette.HighlightedText, "#ffffff"),
                (QPalette.ToolTipBase, c["card"]),
                (QPalette.ToolTipText, c["text"]),
            ):
                palette.setColor(role, QColor(color))
            self.setPalette(palette)
            self.setStyleSheet(f"""
                QWidget {{ color: {c["text"]}; font-family: 'DejaVu Sans', 'Segoe UI', sans-serif; font-size: 12px; }}
                QWidget#root, QStackedWidget, QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget {{ background: {c["bg"]}; }}
                QFrame#sidebar {{ background: #111e30; border: none; }}
                QFrame#sidebar QLabel {{ color: #bbc9dc; background: transparent; }}
                QLabel#brandMark {{ color: #9be8d8; background: #20354a; border: 1px solid #385366; border-radius: 12px; font-size: 23px; font-weight: 700; }}
                QLabel#brand {{ color: #ffffff; font-size: 23px; font-weight: 700; letter-spacing: 2px; padding-top: 14px; }}
                QLabel#sideKicker {{ font-size: 10px; font-weight: 700; letter-spacing: 1px; color: #87a2be; }}
                QLabel#sideMeta {{ font-size: 11px; line-height: 1.5; }}
                QPushButton#navButton {{ text-align: left; border: none; background: transparent; color: #b6c5d9; border-radius: 7px; padding: 9px 12px; font-weight: 600; }}
                QPushButton#navButton:hover {{ background: #233348; color: #ffffff; }}
                QPushButton#navButton:checked {{ background: #25473f; color: #a3eedc; }}
                QLabel#kicker {{ color: {c["accent"]}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
                QLabel#pageTitle {{ font-size: 26px; font-weight: 700; }}
                QFrame#card, QFrame#trustCard {{ background: {c["card"]}; border: 1px solid {c["border"]}; border-radius: 11px; }}
                QFrame#trustCard {{ border-color: {c["accent"]}; }}
                QFrame#card QLabel, QFrame#trustCard QLabel, QFrame#card QWidget, QFrame#trustCard QWidget {{ background: transparent; }}
                QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
                QLabel#resultTitle {{ font-size: 25px; font-weight: 700; color: {c["accent"]}; padding: 8px 0; }}
                QLabel#muted, QLabel#statusMessage {{ color: {c["muted"]}; font-size: 11px; }}
                QLabel#summaryBanner {{ color: {c["accent"]}; background: {c["banner"]}; border: 1px solid {c["border"]}; border-radius: 8px; padding: 12px 15px; font-size: 11px; font-weight: 600; }}
                QLineEdit, QComboBox, QSpinBox {{ background: {c["input"]}; border: 1px solid {c["border"]}; border-radius: 6px; padding: 7px 9px; min-height: 19px; selection-background-color: #177968; selection-color: #ffffff; }}
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPushButton:focus, QCheckBox:focus {{ border: 2px solid {c["accent"]}; }}
                QComboBox::drop-down {{ border: none; width: 22px; }}
                QComboBox QAbstractItemView {{ background: {c["card"]}; color: {c["text"]}; selection-background-color: #177968; selection-color: #ffffff; }}
                QPushButton {{ background: {c["card"]}; color: {c["text"]}; border: 1px solid {c["border"]}; border-radius: 6px; padding: 8px 12px; font-weight: 600; }}
                QPushButton:hover {{ border-color: {c["accent"]}; background: {c["banner"]}; }}
                QPushButton:disabled {{ color: {c["muted"]}; background: {c["alt"]}; }}
                QPushButton#primary {{ color: #ffffff; background: #147b67; border-color: #147b67; }}
                QPushButton#primary:hover {{ background: #106753; }}
                QPushButton#primary:disabled {{ color: {c["muted"]}; background: {c["alt"]}; border-color: {c["border"]}; }}
                QCheckBox {{ spacing: 8px; padding: 4px 0; }}
                QCheckBox::indicator {{ width: 17px; height: 17px; }}
                QProgressBar {{ border: none; background: {c["border"]}; border-radius: 2px; }}
                QProgressBar::chunk {{ background: #20a58a; border-radius: 2px; }}
                QPlainTextEdit#buildLog {{ background: #111e2b; color: #d5e8e4; border: 1px solid {c["border"]}; border-radius: 7px; padding: 12px; font-family: monospace; }}
                QTableWidget {{ background: {c["card"]}; alternate-background-color: {c["alt"]}; gridline-color: {c["border"]}; border: 1px solid {c["border"]}; border-radius: 5px; selection-background-color: {c["banner"]}; selection-color: {c["text"]}; }}
                QHeaderView::section {{ background: {c["alt"]}; color: {c["muted"]}; border: none; border-bottom: 1px solid {c["border"]}; padding: 8px; font-weight: 600; }}
                QScrollBar:vertical {{ background: {c["bg"]}; width: 10px; margin: 0; }}
                QScrollBar::handle:vertical {{ background: {c["border"]}; border-radius: 4px; min-height: 25px; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
                QToolTip {{ background: {c["card"]}; color: {c["text"]}; border: 1px solid {c["border"]}; padding: 6px; }}
            """)

        def config_from_ui(self) -> BuildConfig:
            script_text = self.script_edit.text().strip()
            output_text = self.output_edit.text().strip()
            if not script_text:
                raise ConfigError("Choose an existing .py entry script before continuing.")
            if not output_text:
                raise ConfigError("Choose an output folder before continuing.")
            imports = tuple(dict.fromkeys(self.imports_edit.text().replace(",", " ").split()))
            icon = self.icon_edit.text().strip()
            return BuildConfig(
                script=Path(script_text),
                output_dir=Path(output_text),
                name=self.name_edit.text(),
                target=self.target_combo.currentData(),
                mode=self.mode_combo.currentData(),
                console=self.console_check.isChecked(),
                icon=Path(icon) if icon else None,
                version=self.version_edit.text().strip(),
                description=self.description_edit.text(),
                bundle_identifier=self.bundle_edit.text().strip(),
                hidden_imports=imports,
                timeout=self.timeout_spin.value(),
            ).normalized()

        def set_config(self, config: BuildConfig) -> None:
            """Apply inert profile settings; trust is deliberately not restored."""
            if self.is_busy:
                raise ConfigError("Wait for the current operation before changing profiles.")
            self.script_edit.setText(str(config.script))
            self.output_edit.setText(str(config.output_dir))
            self.name_edit.setText(config.name)
            self.version_edit.setText(config.version)
            for combo, value in (
                (self.target_combo, config.target),
                (self.mode_combo, config.mode),
            ):
                index = combo.findData(value)
                if index < 0:
                    raise ConfigError(f"Unsupported profile setting: {value}")
                combo.setCurrentIndex(index)
            self.console_check.setChecked(config.console)
            self.description_edit.setText(config.description)
            self.icon_edit.setText(str(config.icon) if config.icon else "")
            self.bundle_edit.setText(config.bundle_identifier)
            self.imports_edit.setText(", ".join(config.hidden_imports))
            self.timeout_spin.setValue(config.timeout)
            self.trust_check.setChecked(False)
            self._configuration_changed()

        def load_profile_path(self, path: Path) -> bool:
            if self.is_busy:
                return False
            try:
                config = load_profile(path)
                # Strict profile loader does not validate runtime fields; prevent
                # spinboxes and combo boxes from silently correcting unsafe values.
                errors = config.validate()
                if errors:
                    raise ConfigError("\n".join(errors))
                self.set_config(config)
            except (ConfigError, OSError) as exc:
                self._show_error("Profile not loaded", str(exc))
                return False
            self._profile_path = path
            self.message_label.setText(
                f"Loaded {path.name}. Review settings and affirm trust before building."
            )
            self.show_page(0)
            return True

        def save_profile_path(self, path: Path) -> bool:
            if self.is_busy:
                return False
            try:
                save_profile(self.config_from_ui(), path)
            except (ConfigError, OSError) as exc:
                self._show_error("Profile not saved", str(exc))
                return False
            self._profile_path = path
            self.message_label.setText(
                f"Saved settings to {path.name}. Build trust is not included."
            )
            return True

        def _choose_load_profile(self) -> None:
            if self.is_busy:
                return
            path, _ = QFileDialog.getOpenFileName(
                self, "Load PyForge profile", "", "PyForge JSON profile (*.json)"
            )
            if path:
                self.load_profile_path(Path(path))

        def _choose_save_profile(self) -> None:
            if self.is_busy:
                return
            default = str(self._profile_path or Path.cwd() / "pyforge-profile.json")
            path, _ = QFileDialog.getSaveFileName(
                self, "Save PyForge profile", default, "PyForge JSON profile (*.json)"
            )
            if path:
                if not path.lower().endswith(".json"):
                    path += ".json"
                self.save_profile_path(Path(path))

        def _choose_script(self) -> None:
            if self.is_busy:
                return
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose trusted Python entry script", "", "Python scripts (*.py)"
            )
            if path:
                self.script_edit.setText(path)
                if not self.name_edit.text().strip():
                    self.name_edit.setText(Path(path).stem)
                self.message_label.setText(
                    "Entry script selected. Run Doctor, review settings, then affirm trust before building."
                )

        def _choose_output(self) -> None:
            if self.is_busy:
                return
            path = QFileDialog.getExistingDirectory(
                self, "Choose output directory", self.output_edit.text()
            )
            if path:
                self.output_edit.setText(path)

        def _choose_icon(self) -> None:
            if self.is_busy:
                return
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose native app icon", "", "Native icons (*.ico *.icns *.png)"
            )
            if path:
                self.icon_edit.setText(path)

        def _show_error(self, title: str, message: str) -> None:
            self.message_label.setText(message.splitlines()[0] if message else title)
            QMessageBox.warning(self, title, message)

        def _update_actions(self) -> None:
            busy = self.is_busy or self._close_pending
            self._config_content.setEnabled(not busy)
            self.load_profile_button.setEnabled(not busy)
            self.save_profile_button.setEnabled(not busy)
            self.doctor_button.setEnabled(not busy)
            self.build_button.setEnabled(not busy and self.trust_check.isChecked())
            self.build_button.setToolTip(
                "Build the reviewed project"
                if self.trust_check.isChecked()
                else "Affirm trust in Configure before building"
            )
            self.cancel_button.setEnabled(
                self._build_worker is not None and not self._build_worker.cancel_requested.is_set()
            )
            self.clear_log_button.setEnabled(not busy)

        @pyqtSlot()
        def start_doctor(self) -> None:
            if self.is_busy or self._close_pending:
                return
            try:
                config = self.config_from_ui()
            except (ConfigError, OSError) as exc:
                self._show_error("Check your configuration", str(exc))
                return
            worker = _DoctorWorker(config, self.doctor, self)
            self._doctor_worker = worker
            worker.job_completed.connect(self._on_doctor_completed)
            worker.finished.connect(self._on_doctor_thread_finished)
            self.doctor_summary.setText("Inspecting source and interpreter metadata…")
            self.message_label.setText(
                "Read-only inspection is running. Project code is not executed."
            )
            self.progress.setRange(0, 0)
            self.show_page(1)
            self._update_actions()
            worker.start()

        @pyqtSlot(object)
        def _on_doctor_completed(self, report: Any) -> None:
            if isinstance(report, _WorkerFailure):
                self.doctor_summary.setText("Inspection failed")
                self.message_label.setText("; ".join(report.errors))
                return
            self._doctor_report = report
            errors = sum(f.severity == "error" for f in report.findings)
            warnings = sum(f.severity == "warning" for f in report.findings)
            self.doctor_summary.setText(
                f"{'Needs attention' if errors else 'Checks complete'}  ·  {errors} errors  ·  {warnings} warnings  ·  {report.dependencies.files_scanned} files inspected"
            )
            self.findings_table.setRowCount(len(report.findings))
            for row, finding in enumerate(report.findings):
                for column, text in enumerate(
                    (finding.severity.upper(), finding.message, finding.recovery)
                ):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.findings_table.setItem(row, column, item)
                color = {"error": "#c94e5d", "warning": "#ba842c", "info": "#248f79"}.get(
                    finding.severity, "#57677d"
                )
                self.findings_table.item(row, 0).setForeground(QColor(color))
            self.findings_table.resizeRowsToContents()
            self.dependencies_table.setRowCount(len(report.dependencies.imports))
            for row, dependency in enumerate(report.dependencies.imports):
                for column, text in enumerate(
                    (dependency.name, dependency.kind, ", ".join(dependency.distributions) or "—")
                ):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.dependencies_table.setItem(row, column, item)
            self.dependencies_table.resizeRowsToContents()
            self.message_label.setText(
                "Review the findings before packaging. Doctor is advisory; build preflight runs again."
            )
            self.progress.setRange(0, 100)
            self.progress.setValue(100)

        @pyqtSlot()
        def _on_doctor_thread_finished(self) -> None:
            worker = self._doctor_worker
            self._doctor_worker = None
            if worker:
                worker.deleteLater()
            self.progress.setRange(0, 100)
            self._update_actions()
            self._maybe_finish_close()

        @pyqtSlot()
        def start_build(self) -> None:
            if self.is_busy or self._close_pending:
                return
            if not self.trust_check.isChecked():
                self.show_page(0)
                self.message_label.setText(
                    "Affirm that you trust this project and its hooks before building. PyForge is not a sandbox."
                )
                self.trust_check.setFocus()
                self._config_scroll.ensureWidgetVisible(self.trust_check)
                return
            try:
                config = self.config_from_ui()
                errors = config.validate()
                if errors:
                    raise ConfigError("\n".join(errors))
                engine = self.engine_factory()
            except (ConfigError, OSError, ImportError) as exc:
                self._show_error("Build cannot start", str(exc))
                return
            self._build_config = config
            worker = _BuildWorker(config, engine, self)
            self._build_worker = worker
            worker.event_received.connect(self._on_build_event)
            worker.job_completed.connect(self._on_build_completed)
            worker.finished.connect(self._on_build_thread_finished)
            self.log_edit.clear()
            self.log_state.setText(f"Building {config.name} · {config.target} · {config.mode}")
            self._append_log(
                f"Building reviewed project: {config.script}\nInterpreter: {sys.executable}"
            )
            self.message_label.setText(
                "Build started. You can cancel safely; artifacts are never run automatically."
            )
            self.progress.setRange(0, 0)
            self.show_page(2)
            self._update_actions()
            worker.start()

        def _append_log(self, text: str) -> None:
            # Bound both line count and single-line length before allocating a Qt block.
            for line in str(text).splitlines() or [""]:
                self.log_edit.appendPlainText(
                    line[:MAX_LOG_LINE]
                    + (" … [line truncated]" if len(line) > MAX_LOG_LINE else "")
                )

        @pyqtSlot(object)
        def _on_build_event(self, event: Any) -> None:
            self._append_log(str(getattr(event, "message", event)))
            progress = getattr(event, "progress", None)
            if isinstance(progress, (int, float)):
                self.progress.setRange(0, 100)
                self.progress.setValue(max(0, min(100, int(progress))))
            if getattr(event, "kind", "log") in ("phase", "status", "stage"):
                self.message_label.setText(str(event.message)[:250])

        @pyqtSlot()
        def cancel_build(self) -> None:
            worker = self._build_worker
            if worker is None or worker.cancel_requested.is_set():
                return
            worker.cancel()
            self.cancel_button.setEnabled(False)
            self.message_label.setText("Cancelling the build process and its child processes…")
            self.log_state.setText("Cancellation requested · waiting for process cleanup")
            self._append_log("Cancellation requested by user.")

        @pyqtSlot(object)
        def _on_build_completed(self, result: Any) -> None:
            self._last_result = result
            self.display_result(result)
            status = str(getattr(result, "status", "failed"))
            self.log_state.setText(
                f"Build {status} · {getattr(result, 'elapsed_seconds', 0.0):.1f}s"
            )
            self._append_log(f"Build finished: {status}")
            for error in getattr(result, "errors", ()):
                self._append_log(f"ERROR: {error}")
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if getattr(result, "success", False) else 0)
            self.message_label.setText(
                f"Build {status}. Review the build record and log for details."
            )
            if not self._close_pending:
                self.show_page(3)

        @pyqtSlot()
        def _on_build_thread_finished(self) -> None:
            worker = self._build_worker
            self._build_worker = None
            if worker:
                worker.deleteLater()
            self._update_actions()
            self._maybe_finish_close()

        def display_result(self, result: Any) -> None:
            self._last_result = result
            status = str(getattr(result, "status", "failed"))
            titles = {
                "success": "Build complete",
                "cancelled": "Build cancelled",
                "timeout": "Build timed out",
                "preflight_failed": "Preflight needs attention",
                "untrusted": "Trust required",
                "invalid": "Configuration needs attention",
            }
            self.result_title.setText(titles.get(status, "Build did not complete"))
            errors = list(getattr(result, "errors", ()))
            warnings = list(getattr(result, "warnings", ()))
            detail = f"Status: {status}   ·   Elapsed: {getattr(result, 'elapsed_seconds', 0.0):.1f} seconds"
            if errors:
                detail += "\n" + "\n".join(str(value) for value in errors[:8])
            if warnings:
                detail += "\nWarnings: " + "; ".join(str(value) for value in warnings[:5])
            self.result_detail.setText(detail)
            artifact = getattr(result, "artifact", None)
            report = getattr(result, "report_path", None)
            run = getattr(result, "run_dir", None)
            self.artifact_edit.setText(str(artifact) if artifact else "")
            self.report_edit.setText(str(report) if report else "")
            self.run_edit.setText(str(run) if run else "")
            self.copy_artifact_button.setEnabled(bool(artifact))
            self.open_folder_button.setEnabled(bool(artifact or run))

        def open_output_folder(self) -> None:
            if self._last_result is None:
                return
            artifact = getattr(self._last_result, "artifact", None)
            run = getattr(self._last_result, "run_dir", None)
            path = Path(artifact).parent if artifact else Path(run) if run else None
            if (
                path
                and path.is_dir()
                and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            ):
                self.message_label.setText(f"Could not open folder. Copy this location: {path}")

        def _maybe_finish_close(self) -> None:
            if self._close_pending and not self.is_busy:
                QTimer.singleShot(0, self.close)

        @pyqtSlot()
        def shutdown(self) -> None:
            """Drain owned threads if Qt quits without sending a window close.

            Normal close stays asynchronous. Once aboutToQuit fires, however,
            there is no future event loop to finish the normal close handshake.
            Cancel builds and wait for bounded workers rather than destroying a
            running QThread or stranding the owned PyInstaller subprocess.
            """
            self._close_pending = True
            build_worker, doctor_worker = self._build_worker, self._doctor_worker
            if build_worker:
                build_worker.cancel()
            for worker in (build_worker, doctor_worker):
                if worker:
                    worker.wait()
                    worker.deleteLater()
            self._build_worker = None
            self._doctor_worker = None

        def closeEvent(self, event: Any) -> None:
            if not self.is_busy:
                event.accept()
                return
            if self._build_worker is not None and not self._close_pending:
                answer = QMessageBox.question(
                    self,
                    "Cancel build and close?",
                    "A build is running. Cancel it and close after its processes stop? No artifact will be launched.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
            self._close_pending = True
            if self._build_worker is not None:
                self.cancel_build()
            else:
                self.message_label.setText("Finishing read-only inspection before closing…")
            self._update_actions()
            event.ignore()


def main(argv: list[str] | None = None) -> int:
    """Launch without imposing PyQt5 on headless CLI users."""
    if not QT_AVAILABLE:
        print(
            "PyForge GUI requires PyQt5. In your virtual environment run: "
            f'"{sys.executable}" -m pip install "pyforge-tool[gui,build]"\n'
            'From a source checkout use: python -m pip install -e ".[gui,build]"',
            file=sys.stderr,
        )
        return 2
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("PyForge")
    app.setOrganizationName("PyForge")
    app.setStyle("Fusion")
    window = PyForgeWindow()
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return int(app.exec_())


if __name__ == "__main__":
    raise SystemExit(main())
