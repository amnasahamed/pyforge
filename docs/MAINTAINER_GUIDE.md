# Maintainer guide

## Review and repository setup

- Preserve unrelated work and the existing remote `feature/readme-ui-enhancements` branch. Work on the production branch must not overwrite it.
- Require CI for the exact candidate commit and review changes to trust checks, subprocess arguments, process termination, profile validation and output handling.
- Configure branch protection/review requirements through the repository's normal settings; this change does not claim to have enabled them.
- Enable GitHub private vulnerability reporting and verify a private contact route before announcing a reporting SLA. See [SECURITY.md](../SECURITY.md).
- Inspect direct/transitive dependency updates and action SHA changes. Dependabot makes proposals; do not enable unattended merges for security-critical code.

The original file named `ignore` was a two-line historical README, **not** Git ignore configuration. It was removed from the production branch after preserving this explanation and its Git history. `.gitignore` is the actual configuration; no unrelated work was deleted.

## CI operation

The CI workflow runs unit compatibility, Linux quality/source packaging/audit and native Windows/macOS examples. Native jobs install reviewed PyQt/PyInstaller pins and build/launch tiny trusted fixtures in both CLI modes, plus a windowed Qt artifact. Qt automation is offscreen; add interactive native testing before release.

Run workflow_dispatch with `package_gui_preview` only when an unsigned frozen **UI-only** PyForge preview is desired. It cannot build projects because there is no external Python selector yet; Doctor must block frozen builds. These previews are developer review artifacts, not public production executables. Tar archives preserve macOS executable modes and symlinks; Windows zip archives preserve its native directory contents.

Source distributions/wheels, integration reports and previews are separate artifact names. No secrets are needed for tests. Checkout credentials are not persisted. Action SHAs were read from their official repositories; review future Dependabot updates against those upstream releases. Cached pip downloads improve speed but are not a trust or reproducibility guarantee.

A failed audit is a release blocker. Service/network failure is an incomplete audit, not a pass. Investigate vulnerabilities and review compatible fixed versions; avoid automatic fixes or broad ignores. Qt native-library advisories require independent upstream review.

## Evidence and support

Keep the commit, OS/architecture, Python/tool versions, full commands, actual exit statuses and artifact launch results. Clearly label skipped/unrun stages. Redact private paths/project output from public issue attachments. A green mock, file existence or YAML file does not certify a native application.

Validate minimal install of the wheel in a clean environment, CLI help/imports without Qt, source-installed GUI behavior, cancellation/timeout/error paths, metadata, repeat builds and shutdown. Use the [release checklist](RELEASE_CHECKLIST.md) and update changelog/audit only with verified facts.

## Dependency pin updates

1. Read upstream release notes/security advisories and check Python/OS compatibility.
2. Update direct pins in `requirements-dev.txt` or `.github/requirements-build.txt` and the consumer range only if justified.
3. Re-resolve on native systems; record actual transitive versions. No full cross-platform lock is currently promised.
4. Run lint/type/unit/native builds/source/wheel checks and strict audit.
5. Review distribution notices/terms whenever bundled dependencies change.

Optional preview archives require the manual distribution attestation and a real LICENSE too. Until those gates are resolved, CI uploads reports only for native example builds, not bundled Qt binaries.

The macOS UI-only preview uses compatibility bundle version `1.2.0` by mapping the zero major to one, because candidate `0.x` versions are invalid for the strict `.app` version contract; `preview-environment.json` separately records the actual project version and native bundle version. This does not change package/release metadata.

The audit exporter verifies that the only editable distribution is `pyforge-tool`, then captures all installed third-party packages (including pip/setuptools) as exact pins. The strict no-resolution audit uses those pins; only our own unpublished editable package is omitted and is covered by code/tests. Unexpected editable packages or URL/local-path requirements fail the export instead of being silently skipped.
