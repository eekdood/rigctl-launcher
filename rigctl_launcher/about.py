"""Local legal notices and a compact About dialog."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel,
                              QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget)
from .version import application_version

RELEASES = 'https://github.com/eekdood/rigctl-launcher/releases'


def legal_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'legal'
    return Path(__file__).parent / 'legal'


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        version = application_version()
        self.setWindowTitle('About RigCtl-Launcher')
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        about = QWidget()
        content = QVBoxLayout(about)
        text = QLabel(
            f'<h3>RigCtl-Launcher {version}</h3>'
            '<p>Copyright © 2026 RigCtl-Launcher contributors.</p>'
            '<p>Free software under the GNU GPL version 3. You may redistribute '
            'and modify it under that license. Provided without warranty.</p>'
            '<p>Uses Qt and PySide6, copyright The Qt Company Ltd. and contributors, '
            'under their open-source LGPLv3/GPL terms, and pySerial under BSD terms.</p>'
            '<p>License texts and third-party notices are in the Licenses tab.</p>'
            f'<p><a href="{RELEASES}/tag/v{version}">Release and source downloads</a></p>')
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        content.addWidget(text)
        content.addStretch()
        tabs.addTab(about, 'About')
        licenses = QWidget()
        content = QVBoxLayout(licenses)
        self.documents = QComboBox()
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        root = legal_directory()
        paths = sorted(path for path in root.rglob('*') if path.is_file() and path.suffix.lower() != '.docx')
        paths.sort(key=lambda path: (path.name != 'third-party-notices.txt', path.relative_to(root).as_posix()))
        for path in paths:
            self.documents.addItem(path.relative_to(root).as_posix(), path)
        self.documents.currentIndexChanged.connect(self.show_document)
        content.addWidget(self.documents)
        content.addWidget(self.text)
        tabs.addTab(licenses, 'Licenses')
        self.show_document()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_document(self):
        path = self.documents.currentData()
        if path is None:
            self.text.setPlainText('License documents are unavailable in this installation.')
            return
        try:
            data = path.read_bytes()
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = data.decode('latin-1')
            self.text.setPlainText(text)
        except OSError as error:
            self.text.setPlainText(f'Could not read license document: {error}')
