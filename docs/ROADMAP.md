# Roadmap

This is a prioritized plan, not a promise of supported features or release dates.

## Required before public distribution

1. Preserve the authorized MIT project grant and scope; review new contributions and dependency distribution terms.
2. Keep unknown-origin assets excluded or establish their rights.
3. Complete exact-commit native CI and interactive desktop testing; review dependency notices/security.
4. Document unsigned developer output accurately; establish any future signing/notarization path.

## Next engineering priorities

- External Python interpreter selection/validation for frozen PyForge, with isolated project environments and safe argument handling. Until then frozen builds are UI-only previews.
- More native regression coverage for process-tree cancellation/shutdown, Qt plugins and output permissions.
- Explicit, reviewed data-file/custom-hook support rather than arbitrary flags or executable spec inputs.
- Reproducible platform-specific lock files/SBOMs and deeper bundled-native-library security review.
- Accessible GUI/keyboard/navigation checks on actual Windows/macOS systems.
- Architecture-aware build diagnostics before any universal/cross-architecture claims.

## Deliberate non-goals of this iteration

Silent dependency installation, requirements rewriting, untrusted-code sandboxing claims, cross-OS compilation, automatic signing/notarization, unattended public publication and execution of arbitrary `.spec` inputs.
