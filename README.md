
# 🛠️ PyForge – Convert Python Scripts into Native Apps

[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pyinstaller.svg)](https://pypi.org/project/pyinstaller/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#license)
[![Built with PyQt5](https://img.shields.io/badge/Built%20with-PyQt5-blue.svg)](https://pypi.org/project/PyQt5/)
[![Dark Mode Ready](https://img.shields.io/badge/Theme-Dark%20%2F%20Light-333333)](https://pypi.org/project/qdarktheme/)

> ✨ **Craft native apps from Python scripts – no terminal required!**

---

## 🚀 Features

✅ Build `.exe` or `.app` with **one click**  
🎨 Add custom app icon (`.ico` or `.icns`)  
📦 Auto-generate `requirements.txt` using `pipreqs`  
📥 Auto-install dependencies before build  
🌗 Clean UI with **dark mode support**  
⏳ Progress & error feedback via dialogs

---

## 🖼️ Screenshots

> UI on Windows/macOS

| Main UI | Building |
|--------|---------|
| ![Main UI](https://via.placeholder.com/450x300?text=PyForge+Main+Interface+(Example)) | ![Build Progress](https://via.placeholder.com/450x300?text=PyForge+Build+In+Progress+(Example)) |

---

## 🧰 Requirements

Install required packages using pip:

```bash
pip install pyqt5 pyinstaller pipreqs qdarktheme
```
*   `PyQt5`: For the graphical user interface.
*   `PyInstaller`: To package your Python script into an executable.
*   `pipreqs`: To automatically generate the `requirements.txt` file.
*   `qdarktheme`: For the dark/light theme styling of the UI.

Ensure `Python 3.6+` is installed and added to `PATH`.

---

## 🧪 How to Run

```bash
python pyforge.py
```

---

## 🖱️ How to Use (GUI)

1. **Select your `.py` script**
2. (Optional) Add a **custom icon**
3. Enter your **app name** and **version**
4. Click **"Build for Windows/macOS"**
5. Find your app inside the `dist/` folder

✅ It even warns you for invalid inputs!

---

## 🗂️ Output Structure

```
/your_script_directory
├── dist/  # Contains the final packaged application (.exe or .app)
│   └── YourAppName.exe/.app
├── requirements.txt  # Auto-generated list of project dependencies
├── build_pyinstaller/  # Temporary PyInstaller working directory
└── YourAppName.spec  # PyInstaller spec file, used for configuring the build
```

---

## ⚠️ Tips & Troubleshooting

- **Missing PyInstaller?** Install it with:
  ```bash
  pip install pyinstaller
  ```
- **Missing pipreqs?** Install:
  ```bash
  pip install pipreqs
  ```
- **Wrong icon format?** Use `.ico` for Windows, `.icns` for macOS
- **Issue:** "My app closes immediately after opening!"
  **Solution:** "This often happens with console applications packaged without the `--console` flag (or with `--windowed` inappropriately). If your script is a command-line tool, try rebuilding with PyInstaller using the `--console` option. For GUI apps, ensure errors during startup are logged or displayed instead of crashing."
- **Issue:** "Antivirus flags my app as malware!"
  **Solution:** "This is a common issue with PyInstaller executables. You can try: 1) Submitting your app to the antivirus vendor as a false positive. 2) Using a code signing certificate if you have one. 3) Modifying your script or PyInstaller build options, as sometimes specific libraries or settings trigger flags."

---

## 👨‍💻 Developer

Built with ❤️ by [**Amnas Ahamed**](https://www.linkedin.com/in/amnasahamed)

---

## 📄 License

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

This project is licensed under the **MIT License** – free to use, modify, and distribute.
