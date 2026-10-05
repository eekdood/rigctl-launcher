"""Frozen application entry point; smoke test uses temporary configuration only."""
import sys
import tempfile
from pathlib import Path

from rigctl_launcher.ui import main


def smoke_test():
    from PySide6.QtWidgets import QApplication
    from rigctl_launcher.profiles import Settings, Store
    from rigctl_launcher.ui import MainWindow
    from rigctl_launcher.version import application_version
    from rigctl_launcher.about import AboutDialog

    app = QApplication([])
    app.setApplicationName('RigCtl-Launcher')
    app.setApplicationVersion(application_version())
    assert app.applicationVersion() == application_version()
    about = AboutDialog()
    assert about.documents.count() >= 2
    assert 'Qt' in about.text.toPlainText()
    about.close()
    with tempfile.TemporaryDirectory(prefix='rigctl-launcher-smoke-') as directory:
        store = Store(Path(directory))
        store.save_settings(Settings(executable=str(Path(directory) / 'missing-rigctld')))
        window = MainWindow(store=store, discovery=lambda: [])
        window.show()
        app.processEvents()
        assert not window.profiles and window.table.rowCount() == 0
        assert window.setup_panel.isVisible()
        assert 'installed separately' in window.setup_message.text()
        assert not window.manager.active()
        window.close()
        app.processEvents()
    return 0


if __name__ == '__main__':
    raise SystemExit(smoke_test() if '--smoke-test' in sys.argv else main())
