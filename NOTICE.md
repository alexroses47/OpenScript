# Legal notices and third-party components

## Trademark

OpenScript is an independent project. **It is not affiliated with, sponsored or endorsed by
Celtx Inc.** "Celtx" is a registered trademark of its owner and is mentioned here only to
describe where the code comes from. OpenScript does not use the Celtx logo as its own identity.

The user interface uses OpenScript's own name and logo. "Celtx" is still mentioned where it
describes facts: the `.celtx` project file format, the engine version in the About dialog, and
the original Celtx credits, kept as attribution. The bundled sample projects were created by
the Celtx team.

## Components

| Component | License | Origin |
|---|---|---|
| Celtx 2.9.7 (engine, XUL/JS interface) | MPL 2.0 | Celtx / Greyfirst Corp. Source: `celtx-2-9-7-src.tar.bz2` |
| XULRunner / Gecko 1.9, NSS, NSPR, SQLite | Mozilla MPL tri-license; SQLite is public domain | Included in Celtx 2.9.7 |
| Spanish translation of Celtx 2.9.7 | MPL 2.0 | Celtx Portable 2.9.7 Spanish (PortableApps.com) |
| es_ES spell-check dictionary | See the bundled dictionary's license | Celtx Portable 2.9.7 Spanish |
| WeasyPrint | BSD-3-Clause | https://weasyprint.org |
| pypdfium2 / PDFium | Apache-2.0 / BSD-3-Clause | https://github.com/pypdfium2-team/pypdfium2 |
| Beautiful Soup | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| Pango, HarfBuzz, FontConfig, FreeType, GLib (Windows build via MSYS2, AppImage via Ubuntu, macOS app via Homebrew) | LGPL-2.1+ / MIT / FreeType License | https://www.msys2.org, https://ubuntu.com |
| GTK 2, libXt, libSM, libICE (bundled in the AppImage) | LGPL-2.1+ / MIT | https://www.gtk.org, https://www.x.org |
| libpng 1.2.59 (bundled in the AppImage) | libpng license | http://www.libpng.org |
| LibreOffice (optional, not included) | MPL 2.0 | https://www.libreoffice.org |
| Wine 11.21 (Staging), macOS app only | LGPL-2.1+ | Build by Gcenx: https://github.com/Gcenx/macOS_Wine_builds/releases/tag/11.21 (`wine-staging-11.21-osx64.tar.xz`, SHA-256 in `packaging/tools.sha256`). Source code: https://gitlab.winehq.org/wine/wine/-/tree/wine-11.21 and https://gitlab.winehq.org/wine/wine-staging/-/tree/v11.21 |
| MoltenVK and other libraries bundled in that Wine build, macOS app only | Apache-2.0, LGPL and others (see the Wine build) | https://github.com/Gcenx/macOS_Wine_builds |

## OpenScript changes

Files in `overlay/` that replace Celtx 2.9.7 files keep their MPL 2.0 license and are marked
with "Local modification" / "OpenScript" comments. The rest of the code in this repository is
also released under MPL 2.0.
