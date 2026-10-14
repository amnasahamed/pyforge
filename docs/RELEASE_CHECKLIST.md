# Release checklist

A workflow configuration is not a release. Version 0.2.0 is candidate metadata until a maintainer records actual release evidence. This repository does not configure PyPI publication, credentials, signing or notarization.

## Current blockers

- The missing baseline grant is resolved by the maintainer-authorized MIT LICENSE; retain LICENSE/NOTICE and check the selected candidate's scope and metadata.
- Original forge icon provenance is unresolved; they must stay excluded unless rights are documented.
- PyQt/Qt and all bundled dependency distribution obligations need maintainer review.
- A frozen PyForge is UI-only, not a standalone packaging tool. Source/venv installation is the supported build route.
- Native Windows/macOS evidence must come from successful runs for the exact candidate commit. Linux/offscreen results cannot substitute for it.

## Before any public release

- [x] Maintainer authorized MIT for their own project code; LICENSE, NOTICE and package license metadata are present. Third-party terms and excluded icons are unchanged.
- [ ] Review the grant/scope and all contributed material for the exact release candidate. License presence or an AI-authorship assertion is not independent rights verification.
- [ ] Confirm all shipped assets have rights/attributions, or remain omitted; review [provenance](ASSET_PROVENANCE.md).
- [ ] Establish PyQt/Qt/dependency licensing plan, ship notices/corresponding source as applicable, and inspect final bundles.
- [ ] Review version/changelog/package metadata and record exact 40-character candidate commit.
- [ ] Linux lint, strict core types, core/GUI tests and security audit pass, with no unexplained skips.
- [ ] Native Windows/macOS reviewed CLI onefile/onedir artifacts launch successfully; Qt windowed smoke marker and macOS plist checks pass.
- [ ] Inspect sdist/wheel, verify no original forge assets, install wheel in a clean environment and test CLI without Qt.
- [ ] Manually test source-installed GUI on actual Windows/macOS: paths with spaces, profiles, repeated builds, failure, cancellation, timeout, close/cancel and themes.
- [ ] Test built example applications on clean target systems and review OS/architecture/tool metadata.
- [ ] Redact reports/paths and check final artifacts/checksums/notices.
- [ ] If publishing a standalone desktop tool, first implement/test external interpreter selection; UI-only preview must never be described as that tool.
- [ ] Establish signing/notarization and a secure distribution plan where applicable, or clearly mark reviewed unsigned developer output.

## Manual candidate workflow

`release.yml` accepts an exact candidate commit, candidate version and explicit project-license/dependency-distribution attestations. It checks the MIT grant structure, scope/legal files and matching package license/version metadata, reruns the reusable CI at that commit and creates a **draft prerelease**, not a public release. These structural checks do not independently establish rights. Defaults are conservative and unmet gates fail closed. It is not triggered by tags/pushes. Inputs are passed through environment variables, not interpolated into shell code.

The release stage downloads only artifacts from that workflow run, verifies action-level artifact digests and generates a checksum manifest. Source packages are the release deliverables; native example smoke artifacts and optional UI-only previews remain CI development outputs. Draft notes state native checks and unresolved capability limits. A maintainer reviews the draft, grant/notices/assets, checksums and matching CI evidence before choosing to publish.

There is no automatic PyPI upload, account setup, token creation, commercial-license purchase, certificate provisioning or operating-system warning bypass. Those require a separate authorized setup and review. Do not declare publication complete until the actual remote release is verified.

Optional preview archives require the manual distribution attestation and a real LICENSE too. Until those gates are resolved, CI uploads reports only for native example builds, not bundled Qt binaries.
