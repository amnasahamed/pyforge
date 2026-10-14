# Contributing to PyForge

Thanks for helping make native Python packaging clearer and safer.

## Before contributing

Read [development](docs/DEVELOPMENT.md), [architecture](docs/ARCHITECTURE.md), [conduct](CODE_OF_CONDUCT.md), [security](SECURITY.md) and [licensing](docs/LICENSING.md). PyForge's own code/documentation use [MIT](LICENSE) with the exclusions in [NOTICE](NOTICE). Submit contributions you have the right to provide under that project license; identify any third-party code/assets and their separate terms. Do not copy material of unknown provenance. This policy does not create a separate contributor agreement or transfer copyright.

Use a topic branch and keep changes focused. Preserve existing work/history. Explain the problem, approach, security/trust effects and actual verification in the PR. Use a draft PR while native checks or review are pending.

## Required checks

```bash
python -m ruff check .
python -m mypy
QT_QPA_PLATFORM=offscreen python -m pytest -m "not integration"
python -m build
python .github/scripts/audit_environment.py artifacts/audit-requirements.txt
python -m pip_audit --strict --disable-pip --no-deps -r artifacts/audit-requirements.txt
```

PowerShell/headless setup and opt-in native builds are documented in [development](docs/DEVELOPMENT.md). Report missing dependencies, skips and network blockers accurately. Only run packaging tests on reviewed, trusted fixtures. Native claims require native runs.

## Design expectations

- Inspection/Doctor never execute project imports, install packages or rewrite requirements.
- Build trust is explicit and profiles do not grant it.
- Use validated argument vectors, bounded logs/timeouts, process-tree cancellation and isolated per-run outputs.
- Avoid user-project mutation and protect existing requirements/output.
- Keep the base CLI Qt-free and optional components genuinely optional.
- Add focused regressions for invalid profiles/settings, failure/cancel/repeat/shutdown flows, not just success.
- Do not weaken gates, hide failures/skips or replace genuine screenshots with fabricated native evidence.

Public bug reports must omit secrets, private paths and proprietary source. Vulnerabilities use the private reporting guidance in SECURITY.md. Maintainers may request focused changes or decline scope that compromises the trust boundary.
