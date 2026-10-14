# PyForge repository audit

Date: 2026-10-14. Baseline: `d74e06f4bd82cdea81e42664a2a05d772f9e9e42` (`main`).

## Scope and existing work

All six tracked files, repository history and remote branches were inspected before changes. The baseline is one 351-line PyQt5 script, three icon assets, a README and an obsolete README named `ignore`. An existing remote `feature/readme-ui-enhancements` branch is separate work and is preserved. Work starts from main on `feature/production-core`.

## Findings

| Severity | Finding | Planned resolution |
| --- | --- | --- |
| Critical | Every build overwrites the user's requirements.txt with pipreqs and runs pip install without review. Dependency inspection and packaging execute in the GUI's own environment. | Remove automatic installation and requirements rewriting. Static AST inspection and explicit trust confirmation before packaging. |
| High | No host/target enforcement; Linux is misleadingly treated like Windows, and native compilation limitations are not stated. | Separate platform module and reject cross-OS requests. Validate actual artifacts. |
| High | README declares MIT but no LICENSE text exists. PyQt5 is GPLv3/commercial, not LGPL; icon provenance is undocumented. | Preserve existing author and assets. Document license gaps, dependencies and release gate; do not invent or change licensing. |
| High | No cancellation, live logs, process timeout, artifact validation or protection against concurrent builds/output collisions. | Cancellable process groups, bounded logging, isolated temporary work, run-specific output directories, structured results. |
| High | No packaging metadata, supported Python version, tests, CI, static checks or reproducible developer setup. | src package, CLI, typed modules, tests, pinned development tools and native package CI. |
| Medium | Name validation incorrectly allows some invalid names and path separators. Icon extension only, no file signature checks. | Central input/schema validation with actionable errors and icon signature checks. |
| Medium | Version/description fields never reach artifacts. Always onefile/windowed. Output location fixed and project polluted by specs/build files. | Real Windows version resources and macOS bundle metadata; selectable bundle/console/output settings. |
| Medium | Theme import is mandatory despite fallback handling after import; qdarktheme package name/install instructions are unreliable. | Retain PyQt5; use built-in Qt palettes without extra theming dependency. |
| Medium | Thread signal called finished conflicts with QThread lifecycle; shutdown/repeated-click behavior unsafe. | Separate completion signal, one job at a time, cancellation-aware shutdown. |
| Medium | README points to missing p12.py, claims Python 3.6+, contains fabricated screenshots and advertises unsafe automation. | Verified package/source instructions, genuine offscreen application captures, limitations and trust warning. |
| Low | `ignore` is an old two-line README, not a .gitignore. Unused error widget/fonts and captured logs. | Archive history through Git, remove obsolete file, add proper ignore rules, modular GUI. |

## Architecture decision

Keep PyQt5 to avoid a gratuitous toolkit migration. UI, configuration/profile persistence, static dependency inspection, Build Doctor diagnostics, native platform behavior and subprocess build execution are separate modules. The CLI uses the same core without importing Qt. Inspection never imports the target project. Packaging is an explicit, trusted-code operation: PyInstaller hooks and dependency discovery can execute installed/project code, so the tool is not a sandbox.

## Native-platform and release policy

PyInstaller must run on the target operating system. Windows creates .exe files; macOS windowed builds create .app bundles; Linux produces Linux executables and is not a Windows/macOS cross-compiler. macOS onefile .app is inefficient and unsuitable for sandboxed Mac App Store delivery. Signing/notarization and universal architectures are outside the initial core.

Native CI must prove Windows/macOS smoke scenarios. Local Linux tests do not establish native compatibility. GitHub artifacts are unsigned development builds. No public binary release is ready until project license text, icon rights and GPL/commercial dependency distribution obligations have been resolved and native checks pass.

## References

- PyInstaller usage: https://pyinstaller.org/en/stable/usage.html
- PyInstaller platform overview: https://pyinstaller.org/en/stable/index.html
- PyQt licensing: https://www.riverbankcomputing.com/software/pyqt/intro
- Baseline source: https://github.com/amnasahamed/pyforge/tree/d74e06f4bd82cdea81e42664a2a05d772f9e9e42

## Implementation and verification

Updated with implementation/test evidence at the end of the change set. Audit findings above describe the original baseline, not an assertion that all are still open.
