# Licensing and asset release gate

## MIT for PyForge's own project code

PyForge's own project code and associated documentation are licensed under the
[MIT License](../LICENSE), with scope and exclusions in [NOTICE](../NOTICE).
This includes the project's own examples, tests and development tooling. On
2026-10-14, the maintainer stated that they created the original code/icons using
AI assistance and authorized the choice of an appropriate project license. MIT
was selected under that delegated authority, matching the original README's
stated intention. The previously missing grant is now present; this is not a
claim that every file or dependency in a checkout is MIT-licensed.

MIT is [OSI-approved](https://opensource.org/license/mit) and its Expat form is
[GPL-compatible](https://www.gnu.org/licenses/license-list.html#Expat). It keeps
reuse of the project's own code straightforward while preserving the required
copyright/permission notice and warranty disclaimer. That compatibility does not
permit distributing a GPL PyQt combined binary under MIT alone.

The maintainer's creation statement is not independent verification of rights,
training-data provenance or third-party terms. No particular AI service or
creation terms have been established. Contributors must have the right to
provide their work under the project license and identify third-party material
and applicable notices. The project does not claim to grant rights it does not
hold. This document records engineering policy, not legal advice.

## Archive scope and notices

Package metadata uses the PEP 639 `MIT` license expression for source/wheel
archives, which contain PyForge project material and do not bundle optional
third-party libraries. Those archives include LICENSE, NOTICE and this document;
verification checks their metadata and actual bytes. The repository's original
`forge.*` assets are excluded from both the MIT grant and distributions. Preserve
all existing third-party copyright/license notices; identify any future vendored
material and update archive metadata/scope before distributing it.

## PyQt and Qt are distinct

PyQt5 is available under GPLv3 or Riverbank's commercial license. It is **not
LGPL**. A combined distribution using GPL PyQt requires the applicable GPL terms,
corresponding source and notices; a non-GPL-compatible distribution requires an
appropriate commercial plan. Qt's licensing is separate. GPL PyQt binary wheels
include an LGPL Qt build, which has its own applicable obligations. Consult
[Riverbank's introduction](https://www.riverbankcomputing.com/software/pyqt/intro)
and [licensing FAQ](https://www.riverbankcomputing.com/commercial/license-faq).

Making GUI dependencies optional does not waive their terms when a GUI is
installed or distributed. The base CLI does not import Qt. Neither an MIT project
LICENSE nor a passing package/advisory test is clearance for a combined GUI
binary. Do not bundle commercial license files/credentials or buy a license
without explicit purchasing authorization.

## PyInstaller and other dependencies

PyInstaller's GPL exception permits distributing built applications under other
terms **subject to the licenses of bundled dependencies**; it does not waive
PyQt, Qt or project obligations. Review upstream
[PyInstaller licensing](https://pyinstaller.org/en/stable/license.html), the
actual installed distributions and all compiled/transitive libraries and notices.

## Original icons

`forge.png`, `forge.ico` and `forge.icns` remain in Git to preserve existing work.
They are expressly excluded from the project MIT grant and are not default
application/build icons or included in source/wheel/preview archives. The
maintainer's AI-assisted creation assertion is recorded, but a usable
service/terms/source-reference provenance record is not established. Do not add
these assets back into distributions without documented rights.
[Asset provenance](ASSET_PROVENANCE.md) tracks their status.

## Release policy

The project's missing grant is resolved, not every release obligation. Public
release still requires cleared or omitted assets, reviewed dependency
requirements/notices and native/test/security evidence for the exact candidate.
The manual workflow keeps affirmative project-license and dependency-distribution
attestations plus structural MIT/scope/metadata/version checks; license presence
never replaces either attestation. These checks do not independently establish
rights and do not authorize public publication.

Optional frozen GUI output remains a UI-only unsigned preview, not a standalone
build tool. Its archive includes project license/scope documents, which do not
replace bundled dependency license texts or corresponding source. Maintainers
must supply/review the complete applicable dependency distribution materials
before redistribution; the helper does not automatically assemble or certify
those materials. Default CI uploads native test reports, not bundled Qt binaries.
