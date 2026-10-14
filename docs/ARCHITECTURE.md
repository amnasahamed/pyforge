# Architecture and trust boundary

| Module | Responsibility |
| --- | --- |
| `config` | Immutable settings, validation, strict JSON profiles, atomic writes. |
| `platform` | Native host resolution, cross-OS rejection, artifact layout. |
| `dependencies` | Bounded AST inspection and installed distribution metadata. |
| `diagnostics` | Read-only Build Doctor findings and recovery guidance. |
| `build` | Trusted PyInstaller process, events, lifecycle, reports, artifact checks. |
| `cli` / `__main__` | Text/JSON CLI without Qt imports. |
| `gui` / `gui_entry` | Optional Qt presentation, worker lifecycle, profiles/themes/dialogs. |

The source `pyforge.py` wrapper preserves the original GUI route. Installed entry points are `pyforge` and `pyforge-gui`; the base package has no required runtime dependencies.

## Read-only side

Inspection parses Python text, not project imports. It never runs pipreqs/pip, contacts an index or rewrites requirements. It scans the entry and bounded sibling files, skipping symlinks/common environment/output directories. Import-to-distribution mapping uses only active-interpreter metadata. Unresolved imports are review signals, not install commands.

Source bounds are 500 Python files, 2,000 visited directories, 2 MiB per inspected script, 32 MiB total inspected source and 128 KiB per profile. Dynamic imports, plugins, optional imports and data files require human review. Static analysis does not certify dependencies or safety. Settings/profiles contain no arbitrary subprocess commands or executable spec input.

## Code-executing side

`BuildEngine().build(config, trusted=True)` is the shared API; missing trust must prevent launch. Each run validates settings, runs Doctor and creates an argument vector for PyInstaller using the current interpreter, without shell interpolation. PyInstaller hooks can execute installed/project code. Explicit trust is not sandboxing, and launching an artifact is another code-executing action.

One engine runs one build at a time. The GUI separates subprocess work from presentation. `cancel()` and deadlines terminate the active process group/tree. Bounded logs/events limit UI memory use. Unique run directories preserve previous outputs; temporary specs/work do not pollute source files. A zero return code alone is insufficient: expected native output is checked.

`BuildResult` exposes success/status, artifact/run/report paths, return code, elapsed seconds, command, logs, errors and warnings; `to_dict()` is JSON-safe. Reports/profiles can contain private paths. PyForge has no telemetry/upload, credential storage or automatic dependency installation. Invoked trusted tools/code retain their own behavior; this is not a network sandbox.

## Native/frozen limitations

Python 3.10+ is the source baseline. Native compatibility needs actual OS-specific execution, not Linux screenshots/platform mocks. Output OS/architecture follows the running interpreter/native libraries. Signing, notarization, universal binaries and arbitrary hook/data-file editing are outside this iteration.

A frozen PyForge cannot launch itself as `python -m PyInstaller`; Doctor rejects it. Optional frozen artifacts are UI-only previews. External interpreter selection/validation must be implemented and tested before advertising a standalone packaging desktop tool.
