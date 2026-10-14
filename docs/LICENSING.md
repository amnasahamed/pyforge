# Licensing and asset release gate

## Project license is unresolved

The original README claimed MIT, but the audited baseline did not contain a LICENSE or corresponding grant text. A badge or sentence alone is not a complete record of ownership, permission and scope. This upgrade preserves authorship/history and does **not** add a grant, relicense existing code or represent that redistribution has been cleared.

On 2026-10-14, the maintainer stated that they created the original code and icons
themselves using AI assistance. This records their authorship assertion, not an
independent verification of rights, training-data provenance or third-party terms.
No particular AI service or creation terms have been established. The original
icons remain excluded from distributions while their creation/provenance record
is completed.

For the maintainer's own project code, MIT is a reasonable recommendation matching
the original stated intention. It is an [OSI-approved license](https://opensource.org/license/mit)
and the [GNU license list identifies its Expat/MIT form as GPL-compatible](https://www.gnu.org/licenses/license-list.html#Expat).
Project-code licensing must not be mistaken for relicensing PyQt/Qt or clearing a
combined binary: those dependencies retain their own terms and distribution
requirements. A real grant still requires the rights holder's explicit approval;
this recommendation is not a grant or a legal certainty about AI-assisted material.

Before a public source/binary release, the rights holder must establish the intended license, supply the correct grant text and confirm that existing/contributed code is covered. Contributors must identify any third-party material and its terms. Public repository availability does not by itself resolve these obligations. This document records engineering release constraints, not legal advice.

## PyQt and Qt are distinct

PyQt5 is available under GPLv3 or Riverbank's commercial license. It is **not LGPL**. A distribution using the GPL PyQt implementation requires review of GPL-compatible terms and corresponding source/notice obligations; a proprietary/non-GPL-compatible distribution needs an appropriate commercial plan. Qt's own licensing is separate. GPL PyQt binary wheels include an LGPL Qt build, which brings its own applicable obligations. Consult [Riverbank's introduction](https://www.riverbankcomputing.com/software/pyqt/intro) and [licensing FAQ](https://www.riverbankcomputing.com/commercial/license-faq).

Making GUI dependencies optional does not waive their terms when a GUI is installed or distributed. The base CLI does not import Qt; do not assume that this resolves the project's missing license grant. Do not bundle commercial license files/credentials, or buy a license without explicit purchasing authorization.

## PyInstaller and other dependencies

PyInstaller's GPL exception permits distributing built applications under other terms **subject to the licenses of bundled dependencies**; it is not a waiver for PyQt, Qt or project code. Review upstream [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html), the actual installed distributions and their notices. Pinning a package version and passing pip-audit are not licensing clearance. Review compiled libraries and transitive dependencies, not only Python package names.

## Original icons

`forge.png`, `forge.ico` and `forge.icns` are retained in the repository to preserve existing work. Their provenance and redistribution rights are undocumented. They are not used as default application/window icons or native build assets, and are deliberately excluded from source/wheel and preview packaging. Do not add them back into distributions without documented rights. [Asset provenance](ASSET_PROVENANCE.md) tracks the status.

## Release policy

Public release is blocked until the project grant is established, any distributed assets are cleared or omitted, and the dependency distribution plan/notices are reviewed. The manual workflow requires affirmative attestations and a non-placeholder LICENSE at the selected commit; an unchecked input or missing license fails the gate. An attestation is not legal advice and does not independently verify rights. Native/test/security checks must also pass for that exact commit. Optional frozen GUI output remains a UI-only unsigned preview, not a standalone build tool.
