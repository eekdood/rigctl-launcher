# RigCtl-Launcher release sources

This archive accompanies the platform-specific application download. `manifest.json`
identifies the source archives by component, exact version, upstream URL and SHA-256.
`inventory.json` identifies the packaged modules and native providers. Sources are
preserved as nested archives (tar detects their original compression).

In the combined release ZIP, select your platform's `manifest.json` and extract
the archive identified by `application_source` to obtain the application,
packaging scripts, tests and GitHub workflow from the recorded commit. Shared
upstream archive paths in that manifest are relative to the source ZIP's root
`rigctl-launcher-sources/` directory. Create a Python environment using the
recorded Python version, install `.[test,build]`, and run:

    python -m pytest -q
    python packaging/build.py

For dependency versions, use the accompanying inventory rather than the newest
versions allowed by pyproject.toml. Install the recorded PySide6/PySide6_Essentials/
PySide6_Addons/shiboken6, pyserial and build-tool versions when recreating a release.
The binaries may differ because compiler, SDK, signatures and build environments
vary; this is not a promise of byte-for-byte reproducibility.

Upstream source archives retain their build files and instructions. Qt source
modules use CMake; build the recorded Qt version and selected modules, then build
PySide/Shiboken with that Qt installation using the included pyside-setup scripts:

    python setup.py bdist_wheel --qtpaths=/path/to/qt/bin/qtpaths6

Upstream build references:
https://doc.qt.io/qt-6/build-sources.html
https://doc.qt.io/qtforpython-6/building_from_source/index.html
https://devguide.python.org/getting-started/setup-building/

Homebrew providers include their installed formula, pinned source archives and
public build options. The formula retains its build commands and patches. Debian/
Ubuntu providers include their exact .dsc, original source and Debian patch/build
archives: use `dpkg-source -x package.dsc` to apply the patches, then consult
`debian/rules` and `debian/control` for build commands and dependencies.

To use modified Qt/PySide libraries, build and install your replacement in a Python
environment, then run the application source or rebuild the desktop package in that
environment. The application does not validate or restrict replacement libraries.

Microsoft redistributable runtime files remain governed by their supplied terms;
their proprietary sources are not part of this archive. Operating-system SDKs and
compilers are obtained separately. Hamlib is not bundled.
