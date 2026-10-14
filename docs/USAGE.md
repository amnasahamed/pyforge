# Usage

## Safe workflow

1. Review the entry script, project files, dependencies and packaging hooks. Static inspection is not malware detection.
2. Create a dedicated virtual environment and install reviewed project dependencies yourself.
3. Install PyForge and its build extra in that same interpreter; add GUI only if needed.
4. Inspect imports and run Doctor. Resolve errors and review warnings.
5. Start with a console `onedir` build. Test on the destination OS before trying `onefile` or hiding the console.
6. Explicitly acknowledge trusted code, build, inspect the report and test the produced application in a controlled environment.

PyInstaller can execute hooks and invoke native tools. A virtual environment separates dependencies but does not prevent code from accessing files/network. For additional containment use your own appropriately configured disposable environment.

## CLI

`pyforge --help` and each command's `--help` are authoritative. `python -m pyforge` is equivalent.

```bash
pyforge inspect examples/hello_cli.py --json
pyforge doctor examples/hello_cli.py --name ReviewedCLI --output-dir dist --json
pyforge build examples/hello_cli.py --name ReviewedCLI --output-dir dist --mode onefile --trust-code
```

Doctor, Build and Profile Save accept these settings:

| Option | Purpose |
| --- | --- |
| `--name` | Portable ASCII app name, not a path or command. |
| `--output-dir` | Parent of unique per-run output directories. |
| `--target` | `auto`, `windows`, `macos`, `linux`; must match host. |
| `--mode` | `onedir` or `onefile`. |
| `--console` / `--no-console` | Console setting on supported platforms. |
| `--icon` | Valid native `.ico`, `.icns` or `.png` for the host. |
| `--version` | One to four numeric components, each 0–65535; macOS windowed `.app` requires exactly three: major 1–9999, minor/patch 0–99. |
| `--description` | Short application description. |
| `--bundle-identifier` | Reverse-DNS macOS bundle identifier. |
| `--hidden-import` | Repeat for reviewed dynamic imports. |
| `--timeout` | Seconds, 10–86400. |

Defaults: script stem, script parent's `dist`, host target, `onedir`, console, version `1.0.0`, 600 seconds. Defaults do not certify portability or licensing.

```bash
pyforge profile save reviewed.pyforge.json examples/hello_cli.py \
  --name ReviewedCLI --output-dir dist --mode onedir --version 1.2.0
pyforge doctor --profile reviewed.pyforge.json
pyforge build --profile reviewed.pyforge.json --trust-code --json
```

Profiles are strict, schema-versioned JSON. Unknown fields/types and invalid settings are rejected. Relative paths resolve from the profile location; saved profiles normalize paths. Loading never grants build trust. Saved profiles may expose private absolute paths.

## GUI and output

Use `pyforge-gui` or `python pyforge.py` from the installed source checkout. Select a `.py` entry, inspect, run Doctor, set output/settings and save/load profiles as needed. Executable `.spec` inputs are deliberately unsupported. Native icon contents are checked, not just file extensions.

The GUI runs one build at a time. Cancellation/timeout terminates the active process tree; closing during a build follows the confirmation flow. Failed/cancelled outputs can be partial and must not be treated as successful artifacts.

Each build has a unique output run directory, with `dist/` and `build-report.json`. Temporary PyInstaller spec/work paths stay away from project sources. The reported artifact path is authoritative. Reports record settings/outcome/command/errors/warnings/logs and may contain private paths or project output. PyForge does not upload them.

Windows uses version resources; macOS uses plist metadata; Linux uses sidecars, not embedded ELF version information. A frozen PyForge preview cannot build: `sys.executable` is the frozen program rather than a usable Python interpreter, and Doctor blocks that path. Use source/venv installation for packaging.

## Reviewed examples

`hello_cli.py` uses only the standard library and prints a JSON greeting with `PYFORGE_SMOKE_OK`. `hello_gui.py` displays a Qt label; `--smoke-test` exits automatically. Optional `--marker-file PATH` explicitly writes a marker to that file, only in smoke mode. Neither uses the network or starts subprocesses. Distributing the Qt example still requires appropriate dependency licensing.

CLI exit codes: successful operations 0; inspection/Doctor/build failure 1; invalid configuration or missing build trust 2; timeout 124; cancelled/interrupted build 130. For automation, inspect the structured status/errors too, not exit code alone.
