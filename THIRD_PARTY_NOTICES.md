# Third-Party Software Notices

Jackify includes and/or depends on third-party software components listed below. These components are subject to their own licenses.

## Bundled Components (Inherited from Wabbajack)

The following components are bundled with jackify-engine, which is based on the Wabbajack project (GPL v3).

### 7-Zip / 7-Zip Standalone (7zz)
**Location**: `jackify/engine/Extractors/`
**Version**: As distributed with Wabbajack
**License**: GNU LGPL + unRAR restriction
**Source**: https://www.7-zip.org/
**Purpose**: Archive extraction for modlist installation

7-Zip is licensed under the GNU LGPL license with an unRAR restriction. The unRAR sources are under a mixed license: GNU LGPL + unRAR restriction. Check license.txt for details.

### InnoExtract
**Location**: `jackify/engine/Extractors/windows-x64/innoextract.exe`
**Version**: As distributed with Wabbajack
**License**: zlib/libpng License
**Source**: https://constexpr.org/innoextract/
**Purpose**: Inno Setup archive extraction

### DirectXTex Tools (texconv.exe, texdiag.exe)
**Location**: `jackify/engine/Tools/`
**Version**: As distributed with Wabbajack
**License**: MIT License
**Source**: https://github.com/microsoft/DirectXTex
**Purpose**: Texture conversion and diagnostics for modlist processing

Copyright (c) Microsoft Corporation. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Build-Time Downloaded Components

The following components are downloaded during the AppImage build process and are not included in the git repository.

### Winetricks
**License**: GNU LGPL v2.1
**Source**: https://github.com/Winetricks/winetricks
**Purpose**: Wine prefix configuration and Windows component installation

Winetricks is downloaded from the official GitHub repository during build. See the Winetricks repository for full license details.

### cabextract
**License**: GNU GPL v3
**Source**: https://www.cabextract.org.uk/ (source: https://github.com/kyz/libmspack)
**Purpose**: Microsoft Cabinet file extraction (required by winetricks for Wine component installation)

cabextract is built from source during the AppImage build process. The source tarball is downloaded from the official website and compiled using autotools (configure/make). The compiled binary is bundled in the AppImage. cabextract is GPL v3 licensed and is compatible with Jackify's GPL v3 license.

## System Dependencies

Jackify expects the following utilities to be available on the system:

- **Python 3.8+**: Runtime environment (PSF License)
- **wget / curl**: Download utilities (GPL v3 / MIT-like License)
- **unzip**: Archive extraction (Info-ZIP License)
- **xz / gzip**: Compression utilities (Public Domain / GPL)
- **sha256sum**: Checksum verification (GPL v3, part of GNU coreutils)
- **lz4**: Fast compression (BSD 2-Clause, used by TTW installer)

These utilities are standard on most Linux distributions and are not bundled with Jackify.

## Python Dependencies

Python packages are listed in `requirements.txt` and `requirements-packaging.txt`. Each package is subject to its own license. Key dependencies include:

- **PySide6 / PyQt6**: Qt GUI framework (LGPL v3)
- **requests**: HTTP library (Apache 2.0)
- **psutil**: System utilities (BSD 3-Clause)
- **PyYAML**: YAML parser (MIT)
- **vdf**: Valve Data Format parser (MIT, from solsticegamestudios fork)
- **pycryptodome**: Cryptography library (BSD 2-Clause and Public Domain)

## Wabbajack-Derived Components

jackify-engine is based on Wabbajack, a modlist installation tool for Windows:

**Wabbajack Project**
**License**: GNU GPL v3
**Source**: https://github.com/wabbajack-tools/wabbajack
**Copyright**: Wabbajack Contributors

Jackify's use of Wabbajack components is in compliance with the GPL v3 license. Jackify itself is also licensed under GPL v3.

---

**Note**: This document provides attribution for components bundled with or used by Jackify. For the full text of licenses mentioned here, please refer to the respective project websites and repositories.

Last Updated: 2026-01-16
