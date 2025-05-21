
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
| ![Main UI](https://via.placeholder.com/300x200?text=Main+UI) | ![Build Progress](https://via.placeholder.com/300x200?text=Build+Progress) |

---

## 🧰 Requirements

Install required packages using pip:

```bash
pip install pyqt5 pyinstaller pipreqs qdarktheme
```

Ensure `Python 3.6+` is installed and added to `PATH`.

---

## 🧪 How to Run

```bash
python p12.py
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
├── dist/
│   └── YourAppName.exe/.app
├── requirements.txt
├── build_pyinstaller/
└── YourAppName.spec
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

---

## 👨‍💻 Developer

Built with ❤️ by [**Amnas Ahamed**](https://www.linkedin.com/in/amnasahamed)

---

## 📄 License

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

This project is licensed under the **MIT License** – free to use, modify, and distribute.
