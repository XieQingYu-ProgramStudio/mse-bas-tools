# Third-Party Notices

## PyQt6

PyQt6 is a runtime dependency and is not vendored in this repository.

PyQt6 is dual-licensed by Riverbank Computing under GPLv3 and a commercial
license. A public binary distribution of this application normally requires
GPLv3 compliance or a commercial PyQt license. Projects that cannot use GPLv3
should migrate to PySide6 and comply with LGPLv3.

- https://www.riverbankcomputing.com/software/pyqt/
- https://www.gnu.org/licenses/gpl-3.0.html
- https://www.qt.io/qt-licensing

## Lucide Icons

SVG icons under `tcc_permission_assistant/gui/icons/` and
`packaging/oc_icons/` are derived from Lucide and Feather.

The complete ISC and MIT license texts are included at
`LICENSES/Lucide.txt`.

## OpenCore and OpenCanopy

The source repository does not bundle `OpenCanopy.efi`.

Users must obtain a matching `OpenCanopy.efi` from the official OpenCore
release and comply with OpenCorePkg's BSD-3-Clause license:

- https://github.com/acidanthera/OpenCorePkg

Do not redistribute an OpenCore binary without its upstream copyright and
license notice.

## Apple Names and System Metadata

Application names are read locally from installed bundles and macOS Spotlight
metadata. No Apple system application binary is included in this repository.
