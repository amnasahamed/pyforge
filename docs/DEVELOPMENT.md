# Development and testing

## Setup

Read [contributing](../CONTRIBUTING.md), [security](../SECURITY.md) and [licensing](LICENSING.md). Use a dedicated Python 3.10+ virtual environment. Reviewed direct CI tools:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -r .github/requirements-build.txt
python -m pip install -e ".[gui,build,dev]"
```

PowerShell activation is `.venv\Scripts\Activate.ps1`; if restricted, invoke `.venv\Scripts\python.exe` directly. Core-only development can omit Qt/PyInstaller and install `-e ".[dev]"`. Optional-component tests skipped without dependencies are **not** verification of those components.

`requirements-dev.txt` and `.github/requirements-build.txt` pin reviewed direct tools, not a hash-locked full dependency graph. Qt wheels/transitive dependencies resolve per OS; consumer extras use compatible ranges. Record `python -m pip freeze`, interpreter and OS with test evidence.

## Fast checks

```bash
python -m ruff check .
python -m mypy
python -m pytest -m "not integration"
python -m build
python .github/scripts/audit_environment.py artifacts/audit-requirements.txt
python -m pip_audit --strict --disable-pip --no-deps -r artifacts/audit-requirements.txt
```

Headless Qt tests need `QT_QPA_PLATFORM=offscreen`. POSIX: `QT_QPA_PLATFORM=offscreen python -m pytest -m "not integration"`; PowerShell: `$env:QT_QPA_PLATFORM = "offscreen"` before pytest. Offscreen widgets do not prove native compositor/dialog behavior. Strict mypy covers the typed core/CLI; GUI modules are excluded from that scope.

pip-audit checks known published Python advisories and needs service access. A network failure is incomplete, not clean. Native Qt vulnerabilities need separate review. Do not automatically apply `--fix` or blanket ignores. Review updates and document any narrow exception.

## Opt-in real builds

Tests package and launch the reviewed examples, never arbitrary projects/requirements/hooks. Review fixtures before enabling this code-executing check.

```bash
# POSIX: CLI onedir and onefile
PYFORGE_RUN_INTEGRATION=1 python -m pytest -m integration tests/test_integration.py

# Include the reviewed Qt example
PYFORGE_RUN_INTEGRATION=1 PYFORGE_RUN_GUI_INTEGRATION=1 \
  python -m pytest -m integration tests/test_integration.py
```

```powershell
$env:PYFORGE_RUN_INTEGRATION = "1"
$env:PYFORGE_RUN_GUI_INTEGRATION = "1"
python -m pytest -m integration tests/test_integration.py
```

CLI tests require `PYFORGE_SMOKE_OK`, preserve an existing requirements file and reject source pollution by generated specs/work. The Qt test launches a windowed artifact with an explicit marker file and automatic exit; macOS additionally checks `.app` plist version/identifier. Smoke launches use Qt offscreen, so native interactive testing remains a separate release check.

`PYFORGE_INTEGRATION_OUTPUT` retains build runs/reports in a dedicated directory; otherwise pytest temporary output is used. Reports may include private paths.

## CI

- Linux core tests: Python 3.10/3.12/3.14, without optional runtime components.
- Linux full quality: lint, strict core mypy, Qt unit tests, real CLI packaging, source/wheel inspection and strict audit.
- Native Windows/macOS: unit tests, real CLI onedir/onefile launches and reviewed Qt windowed launch; no signing or notarization.
- Optional manual desktop packaging: unsigned **UI-only** frozen PyForge preview, separate from source packages/example fixtures.
- Release workflow: manual exact-commit candidate checks and license/dependency attestations; gated **draft** prerelease only. No PyPI upload or tag/push-triggered publication.

Actions use verified full upstream SHAs. Dependabot proposes updates for review. Tests use read-only token permissions, no `pull_request_target` and no secrets. [Maintainer guide](MAINTAINER_GUIDE.md) describes operation.

Report exact commit/host/interpreter/commands and distinguish passed, failed, skipped and never run. A configured workflow or expected path is not a successful launch. Update the audit only with actual evidence.

Optional preview archives require the manual distribution attestation and a real LICENSE too. Until those gates are resolved, CI uploads reports only for native example builds, not bundled Qt binaries.

The audit exporter verifies that the only editable distribution is `pyforge-tool`, then captures all installed third-party packages (including pip/setuptools) as exact pins. The strict no-resolution audit uses those pins; only our own unpublished editable package is omitted and is covered by code/tests. Unexpected editable packages or URL/local-path requirements fail the export instead of being silently skipped.
