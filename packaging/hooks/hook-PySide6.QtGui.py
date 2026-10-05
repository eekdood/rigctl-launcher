"""Keep Qt's desktop plugins; this app does not consume PDF or virtual keyboards."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, destination) for source, destination in binaries
            if not Path(source).name.lower().startswith(('qpdf', 'libqpdf',
                                                        'qtvirtualkeyboard', 'libqtvirtualkeyboard'))]
