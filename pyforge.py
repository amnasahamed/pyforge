import sys
import platform
import subprocess
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QFileDialog, QVBoxLayout, QHBoxLayout, QMessageBox, QGroupBox,
    QProgressDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
import qdarktheme

class BuildWorker(QThread):
    finished = pyqtSignal(str, bool)  # message, success

    def __init__(self, py_file, icon_file, app_name, script_dir, os_name):
        super().__init__()
        self.py_file = py_file
        self.icon_file = icon_file
        self.app_name = app_name
        self.script_dir = script_dir
        self.os_name = os_name # Used in success message

    def run(self):
        try:
            # Step 0.1: Check if PyInstaller is available
            try:
                subprocess.run(
                    [sys.executable, "-m", "PyInstaller", "--version"],
                    check=True, capture_output=True, text=True
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                self.finished.emit(
                    "PyInstaller command failed or not found.\n"
                    "Please ensure PyInstaller is installed in the Python environment running PyForge: \n"
                    "'pip install pyinstaller' or 'python -m pip install pyinstaller'.\n\n"
                    f"Error details: {str(e)}",
                    False
                )
                return

            # Step 0.2: Check if pipreqs is available
            try:
                subprocess.run(
                    [sys.executable, "-m", "pipreqs.pipreqs", "--version"],
                    check=True, capture_output=True, text=True
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                self.finished.emit(
                    "pipreqs command failed or not found.\n"
                    "Please ensure pipreqs is installed in the Python environment running PyForge: \n"
                    "'pip install pipreqs' or 'python -m pip install pipreqs'.\n\n"
                    f"Error details: {str(e)}",
                    False
                )
                return

            # Step 1: Use pipreqs to generate requirements.txt
            # We'll place requirements.txt in the script_dir
            pipreqs_cmd = [
                sys.executable, "-m", "pipreqs.pipreqs", self.script_dir,
                "--force", # Overwrite existing requirements.txt
                "--savepath", os.path.join(self.script_dir, "requirements.txt") # Explicitly save in script_dir
            ]
            # Running pipreqs with cwd as script_dir can sometimes be more robust
            # but it defaults to scanning the path provided.
            proc1 = subprocess.run(
                pipreqs_cmd, check=True, capture_output=True, text=True
            )

            # Step 2: Install dependencies from requirements.txt
            req_path = os.path.join(self.script_dir, "requirements.txt")
            if os.path.exists(req_path):
                pip_cmd = [
                    sys.executable, "-m", "pip", "install", "-r", req_path
                ]
                proc2 = subprocess.run(
                    pip_cmd, check=True, capture_output=True, text=True
                )

            # Step 3: Build with PyInstaller
            pyinstaller_cmd = [
                sys.executable,
                "-m", "PyInstaller",
                "--onefile",
                "--windowed", # Use --noconsole for GUI apps; --windowed is an old alias sometimes problematic
                # Using --noconsole is generally preferred for GUI apps on Windows
                # and it's harmless on macOS/Linux where it's the default for windowed apps.
                # "--noconsole", # Consider this instead of --windowed
                "--name", self.app_name,
                "--distpath", os.path.join(self.script_dir, "dist"),
                "--workpath", os.path.join(self.script_dir, "build_pyinstaller"), # Renamed to avoid conflict if 'build' dir exists
                "--specpath", self.script_dir, # Place .spec file in script's directory
            ]
            if self.icon_file:
                pyinstaller_cmd += ["--icon", self.icon_file]
            pyinstaller_cmd.append(self.py_file) # Path to the main Python script

            # Run PyInstaller from the directory of the script being packaged
            proc3 = subprocess.run(
                pyinstaller_cmd, check=True, capture_output=True, text=True, cwd=self.script_dir
            )

            output_dir = os.path.join(self.script_dir, "dist")
            self.finished.emit(
                f"{self.os_name} app build complete!\n"
                f"Find your app in: {output_dir}",
                True
            )

        except subprocess.CalledProcessError as e:
            err_msg = f"Command failed: {' '.join(e.cmd)}\n"
            if e.stdout:
                err_msg += f"Stdout:\n{e.stdout}\n"
            if e.stderr:
                err_msg += f"Stderr:\n{e.stderr}\n"
            self.finished.emit(f"Build failed:\n\n{err_msg}", False)
        except FileNotFoundError as e: # Should be caught by preliminary checks mostly
            self.finished.emit(f"Build failed: A required command was not found.\n{str(e)}\n"
                                "Ensure Python and all tools (pipreqs, PyInstaller) are correctly installed and accessible.", False)
        except Exception as e:
            self.finished.emit(f"Build failed with an unexpected error:\n\n{str(e)}", False)


class PyForge(QWidget):
    def __init__(self):
        super().__init__()
        self.current_os = platform.system()
        self.setWindowTitle("PyForge")
        self.setGeometry(100, 100, 600, 520)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout()

        # Header
        header = QLabel("PyForge")
        header.setFont(QFont("SF Pro Display", 28, QFont.Bold)) # Or any available good font
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)

        tagline = QLabel("Craft native apps from Python scripts with ease.")
        tagline.setFont(QFont("SF Pro Display", 13, QFont.StyleItalic)) # Or any available good font
        tagline.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(tagline)

        # File Selection
        file_group = QGroupBox("Input Files")
        file_layout = QVBoxLayout()

        # Python File
        py_layout = QHBoxLayout()
        self.py_input = QLineEdit()
        self.py_input.setPlaceholderText("Select your Python script (.py)")
        py_browse = QPushButton("Browse")
        py_browse.clicked.connect(lambda: self.select_file(self.py_input, "Python Files (*.py)"))
        py_layout.addWidget(self.py_input)
        py_layout.addWidget(py_browse)

        # Icon Selection
        icon_layout = QHBoxLayout()
        self.icon_input = QLineEdit()
        icon_type_label = self.get_icon_label()
        self.icon_input.setPlaceholderText(f"Select {icon_type_label} icon file (optional)")
        icon_browse = QPushButton("Browse")
        icon_browse.clicked.connect(self.select_icon)
        icon_layout.addWidget(self.icon_input)
        icon_layout.addWidget(icon_browse)

        file_layout.addLayout(py_layout)
        file_layout.addLayout(icon_layout)
        file_group.setLayout(file_layout)

        # App Details
        details_group = QGroupBox("Application Details")
        details_layout = QVBoxLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Application Name (e.g., MyApp)")

        self.version_input = QLineEdit() # Not currently used by PyInstaller in this script
        self.version_input.setPlaceholderText("Version (e.g., 1.0.0) - Informational")

        self.desc_input = QTextEdit() # Not currently used by PyInstaller in this script
        self.desc_input.setPlaceholderText("Description (optional) - Informational")
        self.desc_input.setFixedHeight(80)


        details_layout.addWidget(self.name_input)
        details_layout.addWidget(self.version_input)
        details_layout.addWidget(self.desc_input)
        details_group.setLayout(details_layout)

        # Build Button
        build_btn = QPushButton(f"Build for {self.get_os_name()}")
        build_btn.setStyleSheet("font-size: 17px; padding: 12px;")
        build_btn.clicked.connect(self.build_app)

        # Footer/Branding
        footer = QLabel(
            'Built by <a href="https://www.linkedin.com/in/amnasahamed">Amnas Ahamed</a>'
        )
        footer.setOpenExternalLinks(True)
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #888; font-size: 13px; margin-top: 18px;")

        # Assemble UI
        main_layout.addWidget(file_group)
        main_layout.addWidget(details_group)
        main_layout.addWidget(build_btn)
        main_layout.addStretch(1) # Add stretch to push footer down
        main_layout.addWidget(footer)

        self.setLayout(main_layout)

    def get_os_name(self):
        return "macOS" if self.current_os == "Darwin" else self.current_os # More general

    def get_icon_label(self):
        return ".icns (macOS)" if self.current_os == "Darwin" else ".ico (Windows)"

    def select_file(self, field, file_type_filter):
        file, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_type_filter)
        if file:
            field.setText(file)
            # Auto-populate app name if empty and Python file is selected
            if field == self.py_input and not self.name_input.text():
                base_name = os.path.basename(file)
                app_name_suggestion = os.path.splitext(base_name)[0]
                self.name_input.setText(app_name_suggestion.replace("_", " ").title())


    def select_icon(self):
        icon_ext_filter = "Icon Files (*.icns)" if self.current_os == "Darwin" else "Icon Files (*.ico)"
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Icon File",
            "",
            icon_ext_filter
        )
        if file:
            self.icon_input.setText(file)

    def build_app(self):
        py_file = self.py_input.text().strip()
        icon_file = self.icon_input.text().strip()
        app_name = self.name_input.text().strip()

        if not py_file:
            QMessageBox.critical(self, "Error", "Please select a Python script (.py) to build.")
            return
        if not os.path.isfile(py_file):
            QMessageBox.critical(self, "Error", f"Python script not found: {py_file}")
            return
        if not py_file.lower().endswith(".py"):
            QMessageBox.critical(self, "Error", "The selected script must be a .py file.")
            return

        if not app_name:
            # Default app name from script if not provided
            app_name = os.path.splitext(os.path.basename(py_file))[0]
            self.name_input.setText(app_name) # Update UI field as well
        
        # Validate app_name (PyInstaller might have restrictions)
        if not app_name.isalnum() and '_' not in app_name and '-' not in app_name:
             # Basic check; PyInstaller might be more permissive but good to guide user
            reply = QMessageBox.question(self, "App Name Warning",
                                         f"The app name '{app_name}' contains characters that might cause issues. "
                                         "It's recommended to use only letters, numbers, underscores, or hyphens.\n"
                                         "Continue anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return


        script_dir = os.path.dirname(py_file)
        if not script_dir: # If file is in current dir, dirname is empty
            script_dir = "."
        script_dir = os.path.abspath(script_dir) # Ensure absolute path

        if icon_file and not os.path.isfile(icon_file):
            QMessageBox.critical(self, "Error", f"Icon file not found: {icon_file}")
            return
        
        icon_ext = ".icns" if self.current_os == "Darwin" else ".ico"
        if icon_file and not icon_file.lower().endswith(icon_ext):
            QMessageBox.critical(self, "Error", f"Please select a valid {icon_ext} icon file for {self.get_os_name()}.")
            return


        # Show indeterminate progress dialog
        self.progress = QProgressDialog("PyForge is building your app...", None, 0, 0, self)
        self.progress.setWindowTitle("Building Application")
        self.progress.setWindowModality(Qt.ApplicationModal)
        self.progress.setMinimumDuration(0) # Show immediately
        self.progress.setCancelButton(None) # No cancel button for now
        self.progress.show()
        QApplication.processEvents() # Ensure dialog is shown

        # Start build worker thread
        self.worker = BuildWorker(py_file, icon_file, app_name, script_dir, self.get_os_name())
        self.worker.finished.connect(self.on_build_finished)
        self.worker.start()

    def on_build_finished(self, msg, success):
        if self.progress: # Check if progress dialog still exists
            self.progress.close()
            self.progress = None # Clear reference

        if success:
            QMessageBox.information(self, "Build Successful", msg)
        else:
            # Create a scrollable text area for long error messages
            error_dialog = QMessageBox(self)
            error_dialog.setIcon(QMessageBox.Critical)
            error_dialog.setWindowTitle("Build Failed")
            error_dialog.setText("The application build failed. See details below:")
            
            error_text_edit = QTextEdit()
            error_text_edit.setPlainText(msg)
            error_text_edit.setReadOnly(True)
            error_text_edit.setMinimumHeight(200) # Adjust as needed
            error_text_edit.setMinimumWidth(500)  # Adjust as needed
            
            # QMessageBox doesn't directly support adding custom widgets like QTextEdit in a straightforward way
            # for its main text area. We'll use setDetailedText or just show the long message.
            # For very long messages, a custom dialog might be better, but this is simpler.
            if len(msg) > 300: # Arbitrary length to decide if detailed text is better
                error_dialog.setDetailedText(msg) # This adds a "Show Details..." button
                error_dialog.exec_()
            else:
                QMessageBox.critical(self, "Build Failed", msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Apply dark theme if available
    try:
        qdarktheme.enable_hi_dpi()
        qdarktheme.setup_theme("auto") # Or "dark", "light"
    except ImportError:
        print("qdarktheme not found. Proceeding with default system theme.")
    except Exception as e:
        print(f"Could not apply qdarktheme: {e}")

    window = PyForge()
    window.show()
    sys.exit(app.exec_())
