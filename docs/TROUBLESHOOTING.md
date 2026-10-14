# Troubleshooting

## Missing command/component

Use `python -m pyforge --help` to avoid PATH mismatch. Reinstall with the active virtual environment's Python: `python -m pip install -e ".[build]"`, or `.[gui,build]` for desktop. Confirm `python -c "import sys; print(sys.executable)"`. Nothing is installed automatically. The original GUI route is `python pyforge.py`, not the missing historical `p12.py`.

## Unresolved imports

Import names can differ from distribution names (`PIL`/Pillow); optional/local/dynamic imports may confuse static inspection. Review actual dependency declarations/installed metadata. Do not install similarly named packages blindly. Use the same isolated interpreter for dependencies, PyInstaller and PyForge. Add only reviewed hidden imports needed by genuine runtime behavior.

## Cross-OS target rejected

Build on the destination OS. Linux cannot produce Windows `.exe` or macOS `.app` by changing a field. Architecture follows the current interpreter/native libraries; universal/cross-architecture output is not promised. [Upstream constraints](https://pyinstaller.org/en/stable/operating-mode.html).

## Artifact does not launch

Start with `onedir` and a console, launch from a terminal and inspect errors. Dynamic imports, native libraries, Qt plugins and data files need project-specific review. Copy the entire onedir bundle, not its executable alone. Test on a clean destination system because build-machine libraries may mask gaps.

Onefile extracts to temporary storage and starts more slowly; no-execute temporary mounts can block it. Do not elevate bundles as a workaround. Prefer onedir for macOS `.app`, especially for any future sandboxed distribution. [Mode details](https://pyinstaller.org/en/stable/operating-mode.html).

A frozen PyForge is a UI-only preview and Doctor blocks packaging from it. Install from source/in a virtual environment to build. External interpreter selection is roadmap work.

## Icon/metadata problems

Export a real `.ico`, `.icns` or `.png` for the host. Renaming is not conversion. Use portable names, numeric versions and reverse-DNS bundle identifiers. A windowed macOS `.app` requires exactly major.minor.patch: major 1–9999 and minor/patch 0–99. Linux metadata sidecars are not embedded ELF resources. Desktop icon caches may need a fresh bundle name/location; do not disable security protections.

## Permissions/disk/timeout

Use an output location your normal account can write and allow enough temporary space. Do not elevate PyForge as the first fix. Increase timeout only after reviewing a legitimate slow step. Failed/cancelled files can be partial; retain the report and clean only inactive run directories you no longer need.

## Qt on Linux/headless CI

`QT_QPA_PLATFORM=offscreen` is for automated widget tests, not an interactive desktop. Use a normal display session and your distribution's supported system-library packages. Inspect the Qt plugin/library error instead of copying random binaries. Offscreen screenshots are labelled and are not native Windows/macOS evidence.

## Unsigned/antivirus warnings

Developer artifacts are unsigned. Signing/notarization/reputation are separate release work. Verify provenance/source/checksums; do not disable antivirus or automatically bypass OS security warnings. Suspected false positives should be reviewed and submitted via the vendor's official process.

## Reporting

Include version/commit, OS/architecture, Python/PyInstaller versions, exact settings, a minimal reviewed reproduction and redacted logs. Remove private paths, secrets and proprietary code. Report vulnerabilities through [SECURITY.md](../SECURITY.md), not public bugs. Keep headless and interactive native evidence distinct.
