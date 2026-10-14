# Security policy

## Trust boundary

PyForge's inspection and Build Doctor parse source/metadata without importing the selected project, installing packages or editing requirements. They are not malware scanners and do not certify code safety.

Packaging is code-executing: PyInstaller hooks, installed dependencies and project tooling can run with your account's permissions. `--trust-code` or the GUI confirmation is required. Review code and dependencies first, use a dedicated environment and do not run as administrator/root. A virtual environment is not a security sandbox. Only launch produced applications you trust. Executable `.spec` inputs are not supported.

Profiles and build reports may contain private paths, command arguments and project logs. Review/redact before sharing. PyForge has no built-in telemetry/report uploader or credential storage; invoked tools/code may independently use network/filesystem access. Do not assume network isolation.

## Supported security work

The current development line is 0.2.x; no public release/support SLA is established. Report issues against the latest reviewed commit and state any affected versions. Older prototype behavior should not be relied upon for safe dependency handling.

## Reporting vulnerabilities

Do **not** open a public issue containing exploit details, sensitive files or secrets. On the [repository Security tab](https://github.com/amnasahamed/pyforge/security), use “Report a vulnerability” if GitHub private reporting is enabled. Its availability must be verified; this document does not claim it is configured. If unavailable, contact a repository maintainer through a private route you already know and ask for a secure reporting channel before sending details. No private email address or response-time promise is invented here.

Include affected commit/version, host/interpreter, minimal reviewed reproduction, impact and redacted evidence. Do not execute malicious fixtures against other people or upload private projects. Coordinate disclosure after the maintainer assesses/fixes the issue.

## Maintainer security checks

Run strict pip-audit with service access, inspect upstream native-library advisories, review dependency/action updates and rerun native tests. Service failures are not clean audits; passes cover known Python advisories, not all native Qt code. Do not use broad ignores or automatic unreviewed dependency fixes. Public releases require the [licensing and verification gates](docs/RELEASE_CHECKLIST.md).
