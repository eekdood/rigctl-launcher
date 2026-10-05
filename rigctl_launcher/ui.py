"""PySide6 interface; device and process policies live in the core modules."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from .devices import Device, candidates, discover, unique_interfaces
from .processes import Manager
from .profiles import Settings, Store
from .executable import INSTALL_MESSAGE, locate_executable


def button(text, callback):
    result = QPushButton(text)
    result.clicked.connect(lambda checked=False: callback())
    return result


def spin(value, low=1, high=65535):
    result = QSpinBox()
    result.setRange(low, high)
    result.setValue(value)
    return result


class ProfileDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit radio profile")
        self.resize(610, 490)
        self.profile = profile
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(profile.name)
        self.model = spin(profile.model, 1, 999999)
        self.baud = QLineEdit(str(profile.baud) if profile.baud else "")
        self.manual = QLineEdit(profile.manual_device)
        self.port = spin(profile.preferred_port)
        self.executable = QLineEdit(profile.executable)
        self.executable.setPlaceholderText("Blank uses executable from Settings")
        self.verbosity = spin(profile.verbosity, 0, 5)
        self.match = QPlainTextEdit(json.dumps(profile.match, indent=2))
        self.match.setMaximumHeight(100)
        self.args = QLineEdit(json.dumps(profile.arguments))
        for label, field in [("Radio name", self.name), ("Hamlib model", self.model), ("Baud (blank = Hamlib default)", self.baud), ("Manual device fallback", self.manual), ("Preferred TCP port", self.port), ("Executable override", self.executable), ("Verbosity (-v count)", self.verbosity), ("Device identity (JSON)", self.match), ("Additional arguments (JSON array)", self.args)]:
            form.addRow(label, field)
        layout.addLayout(form)
        hint = QLabel("Use the device chooser’s ‘Remember’ option to fill identity fields.\nModel/device/port/bind/verbosity arguments are managed by the app.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.result_profile = replace(self.profile, name=self.name.text().strip(), model=self.model.value(), baud=int(self.baud.text()) if self.baud.text().strip() else None, manual_device=self.manual.text().strip(), preferred_port=self.port.value(), executable=self.executable.text().strip(), verbosity=self.verbosity.value(), match=json.loads(self.match.toPlainText()), arguments=json.loads(self.args.text())).validate()
        except (ValueError, TypeError) as e:
            QMessageBox.warning(self, "Invalid profile", str(e))
            return
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, settings, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings_setup_seen = settings.setup_seen
        self.resize(600, 270)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.executable = QLineEdit(settings.executable)
        self.mode = QComboBox()
        self.mode.addItem("Profile port (report conflicts)", "profile")
        self.mode.addItem("First available slot", "slots")
        self.mode.setCurrentIndex(0 if settings.port_mode == "profile" else 1)
        self.slots = QLineEdit(", ".join(map(str, settings.slots)))
        executable_row = QHBoxLayout()
        executable_row.addWidget(self.executable)
        executable_row.addWidget(button("Browse…", self.browse_executable))
        form.addRow("Default rigctld executable", executable_row)
        form.addRow("Port assignment", self.mode)
        form.addRow("Ordered TCP slots", self.slots)
        layout.addLayout(form)
        self.executable_status = QLabel()
        self.executable_status.setWordWrap(True)
        layout.addWidget(self.executable_status)
        self.executable.textChanged.connect(self.check_executable)
        self.check_executable()
        hint = QLabel(f"Bind address: 127.0.0.1\nProfiles/settings: {root}\nPer-profile executable overrides take precedence.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_executable(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select separately installed rigctld executable")
        if path:
            self.executable.setText(path)

    def check_executable(self):
        path = locate_executable(self.executable.text())
        self.executable_status.setText(f"Executable found: {path} (radio response unverified)" if path else INSTALL_MESSAGE)

    def save(self):
        try:
            self.result_settings = Settings(executable=self.executable.text().strip(), port_mode=self.mode.currentData(), slots=[int(x.strip()) for x in self.slots.text().split(",")], setup_seen=self.settings_setup_seen).validate()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid settings", str(e))
            return
        self.accept()


class DeviceDialog(QDialog):
    def __init__(self, profile, devices, parent=None, port_description=""):
        super().__init__(parent)
        self.setWindowTitle(f"Choose serial device — {profile.name}")
        self.resize(800, 250)
        self.devices = devices
        layout = QVBoxLayout(self)
        matches = unique_interfaces(candidates(profile, devices))
        explanation = "One saved match detected; confirm it below." if len(matches) == 1 else ("Several devices match. Choose the intended serial interface." if matches else "No saved match detected. Select a device or enter its manual path.")
        layout.addWidget(QLabel(explanation))
        if port_description:
            layout.addWidget(QLabel(port_description))
        self.combo = QComboBox()
        self.combo.addItem("Choose a device…", None)
        for device in devices:
            self.combo.addItem(device.label(), device)
        if len(matches) == 1:
            self.combo.setCurrentIndex(devices.index(matches[0]) + 1)
        self.manual = QLineEdit(profile.manual_device)
        self.manual.setPlaceholderText("Manual path or COM port")
        self.use_manual = QCheckBox("Use manual device path instead of detected selection")
        self.remember = QCheckBox("Remember this serial interface in the profile")
        layout.addWidget(self.combo)
        layout.addWidget(self.use_manual)
        layout.addWidget(self.manual)
        layout.addWidget(self.remember)
        hint = QLabel("Saved USB interface IDs follow device-path changes. When unavailable, the saved choice is pinned to its path.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose(self):
        self.device = Device(self.manual.text().strip(), "Manual selection", discovered=False) if self.use_manual.isChecked() else self.combo.currentData()
        if self.device is None or not self.device.path:
            QMessageBox.warning(self, "Device required", "Choose a detected device or enable and enter a manual path.")
            return
        # Preserve identity even when the user typed an equivalent known path.
        if self.use_manual.isChecked():
            from .devices import canonical_path
            self.device = next((d for d in self.devices if canonical_path(d.path) == canonical_path(self.device.path)), self.device)
        self.accept()


class LogPane(QWidget):
    def __init__(self, buffer, parent=None):
        super().__init__(parent)
        self.buffer = buffer
        self.revision = -1
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.pause = QCheckBox("Pause scrolling")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search session log")
        tools.addWidget(self.pause)
        tools.addWidget(self.search, 1)
        tools.addWidget(button("Find next", self.find))
        tools.addWidget(button("Clear display", self.clear))
        tools.addWidget(button("Copy", self.copy))
        tools.addWidget(button("Save…", self.save))
        layout.addLayout(tools)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text)
        self.search.returnPressed.connect(self.find)
        self.pause.toggled.connect(lambda checked: self.text.moveCursor(QTextCursor.End) if not checked else None)
        self.hidden_revision = -1

    def update_log(self):
        revision, text = self.buffer.snapshot()
        if revision == self.revision:
            return
        # Clear only the display; save/copy still retain the bounded capture.
        if self.hidden_revision >= 0:
            text = self.buffer_since_clear(text)
        bar = self.text.verticalScrollBar()
        position = bar.value()
        horizontal = self.text.horizontalScrollBar().value()
        cursor = self.text.textCursor()
        selection = (cursor.anchor(), cursor.position())
        self.text.setPlainText(text)
        if self.pause.isChecked():
            cursor = self.text.textCursor()
            cursor.setPosition(min(selection[0], len(text)))
            cursor.setPosition(min(selection[1], len(text)), QTextCursor.KeepAnchor)
            self.text.setTextCursor(cursor)
            bar.setValue(position)
            self.text.horizontalScrollBar().setValue(horizontal)
        else:
            self.text.moveCursor(QTextCursor.End)
        self.revision = revision

    def buffer_since_clear(self, text):
        # Buffer exposes a separate display stream through append revisions below.
        return self.buffer.display_snapshot(self.hidden_revision)

    def clear(self):
        self.hidden_revision = self.buffer.snapshot()[0]
        self.text.clear()
        self.revision = self.hidden_revision

    def find(self):
        self.pause.setChecked(True)
        if not self.text.find(self.search.text()):
            self.text.moveCursor(QTextCursor.Start)
            self.text.find(self.search.text())

    def copy(self):
        QApplication.clipboard().setText(self.buffer.snapshot()[1])

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save retained session log", "rigctld.log", "Log files (*.log);;All files (*)")
        if path:
            try:
                Path(path).write_text(self.buffer.snapshot()[1], encoding="utf-8")
            except OSError as e:
                QMessageBox.warning(self, "Could not save log", str(e))


class MainWindow(QMainWindow):
    def __init__(self, store=None, discovery=discover):
        super().__init__()
        self.setWindowTitle("RigCtl-Launcher")
        self.resize(1340, 780)
        self.store = store or Store()
        self.profiles = self.store.load_profiles()
        self.settings = self.store.load_settings()
        self.manager = Manager()
        self.discovery = discovery
        self.devices = []
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="serial-metadata")
        self.device_job = None
        self.closing = False
        self.log_panes = {}
        self.row_controls = {}
        root = QWidget()
        layout = QVBoxLayout(root)
        toolbar = QHBoxLayout()
        self.refresh_button = button("Refresh devices", self.refresh_devices)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(button("New profile", self.new_profile))
        toolbar.addWidget(button("Settings…", self.edit_settings))
        toolbar.addStretch()
        self.mode_label = QLabel()
        toolbar.addWidget(self.mode_label)
        layout.addLayout(toolbar)
        self.setup_panel = QWidget()
        setup_layout = QHBoxLayout(self.setup_panel)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        self.setup_message = QLabel()
        self.setup_message.setWordWrap(True)
        setup_layout.addWidget(self.setup_message, 1)
        setup_layout.addWidget(button("Settings…", self.edit_settings))
        self.setup_dismiss = button("Got it", self.dismiss_setup)
        setup_layout.addWidget(self.setup_dismiss)
        layout.addWidget(self.setup_panel)
        self.notice = QLabel("Clients connect directly to the assigned CAT address. Running does not verify radio response.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Radio", "Serial device / detection", "Assigned CAT address", "Session status", "Actions"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 280)
        self.table.setColumnWidth(2, 205)
        self.table.setColumnWidth(3, 200)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 2)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 3)
        self.setCentralWidget(root)
        self.build_rows()
        self.update_setup_notice()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.device_timer = QTimer(self)
        self.device_timer.timeout.connect(self.refresh_devices)
        self.device_timer.start(3000)
        self.refresh_devices()
        if self.store.errors:
            self.notice.setText("Profile load errors: " + "; ".join(self.store.errors))

    def update_setup_notice(self):
        found = locate_executable(self.settings.executable)
        first_launch = not self.settings.setup_seen
        self.setup_panel.setVisible(first_launch or found is None)
        self.setup_message.setText(INSTALL_MESSAGE + (f" Executable found: {found}." if found else " No default executable was found."))
        self.setup_dismiss.setVisible(first_launch)

    def dismiss_setup(self):
        try:
            settings = replace(self.settings, setup_seen=True)
            self.store.save_settings(settings)
            self.settings = settings
            self.update_setup_notice()
        except OSError as e:
            self.show_error(e)

    def build_rows(self):
        self.table.setRowCount(len(self.profiles))
        for row, profile in enumerate(self.profiles):
            for col in range(4):
                self.table.setItem(row, col, QTableWidgetItem())
            actions = QWidget()
            buttons = QHBoxLayout(actions)
            buttons.setContentsMargins(2, 2, 2, 2)
            controls = {}
            for label, fn in [("Start", lambda p=profile: self.start(p)), ("Start on…", lambda p=profile: self.start_on(p)), ("Stop", lambda p=profile: self.manager.stop(p.id)), ("Restart", lambda p=profile: self.restart(p)), ("Edit", lambda p=profile: self.edit_profile(p))]:
                controls[label] = button(label, fn)
                buttons.addWidget(controls[label])
            self.row_controls[profile.id] = controls
            self.table.setCellWidget(row, 4, actions)
            if profile.id not in self.log_panes:
                pane = LogPane(self.manager.session(profile.id).logs)
                self.log_panes[profile.id] = pane
                self.tabs.addTab(pane, profile.name)
            else:
                self.tabs.setTabText(self.tabs.indexOf(self.log_panes[profile.id]), profile.name)
        self.render()

    def render(self):
        self.mode_label.setText("Port mode: " + ("Profile port" if self.settings.port_mode == "profile" else "First available slot"))
        for row, profile in enumerate(self.profiles):
            session = self.manager.session(profile.id)
            matches = unique_interfaces(candidates(profile, self.devices))
            detected = matches[0].path + " (detected)" if len(matches) == 1 else ("Choose device (multiple matches)" if matches else "No saved device detected")
            device = session.device.path if session.active else detected
            address = f"127.0.0.1:{session.port}" if session.port is not None else (f"127.0.0.1:{profile.preferred_port} (preferred)" if self.settings.port_mode == "profile" else "First available slot")
            if session.port is not None and not session.active:
                address += " (last)"
            status = session.state + (f" — {session.error}" if session.error else "")
            for col, value in enumerate((profile.name, device, address, status)):
                item = self.table.item(row, col)
                item.setText(value)
                item.setToolTip(value)
                if col == 2:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            for label, control in self.row_controls[profile.id].items():
                control.setEnabled(not self.closing and (session.active if label in {"Stop", "Restart"} else not session.active))
            self.log_panes[profile.id].update_log()

    def refresh_devices(self):
        if self.closing or self.device_job is not None:
            return
        self.refresh_button.setEnabled(False)
        self.device_job = self.executor.submit(self.discovery)

    def tick(self):
        self.manager.poll()
        if self.device_job is not None and self.device_job.done():
            try:
                self.devices = self.device_job.result()
                self.manager.disconnected(self.devices)
            except Exception as e:
                self.notice.setText(f"Device discovery failed: {e}")
            self.device_job = None
            self.refresh_button.setEnabled(not self.closing)
        self.render()
        if self.closing and not self.manager.active():
            self.timer.stop()
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.close()

    def show_error(self, message):
        QMessageBox.warning(self, "RigCtl-Launcher", str(message))

    def start(self, profile, override=None):
        description = (f"Session override: 127.0.0.1:{override}" if override is not None else (f"Preferred CAT address: 127.0.0.1:{profile.preferred_port}" if self.settings.port_mode == "profile" else "CAT port: first available slot from " + ", ".join(map(str, self.settings.slots))))
        dialog = DeviceDialog(profile, self.devices, self, description)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.remember.isChecked():
            profile = replace(profile, match=dialog.device.identity(), manual_device=dialog.device.path)
            try:
                self.store.save_profile(profile)
            except (OSError, ValueError) as e:
                self.show_error(e)
                return
            self.profiles = [profile if p.id == profile.id else p for p in self.profiles]
            self.build_rows()
        self.tabs.setCurrentWidget(self.log_panes[profile.id])
        try:
            self.manager.start(profile, dialog.device, self.settings, override)
        except ValueError as e:
            self.show_error(e)
        self.render()

    def start_on(self, profile):
        port, ok = QInputDialog.getInt(self, "Start on… (session only)", "TCP port at 127.0.0.1:", profile.preferred_port, 1, 65535)
        if ok:
            self.start(profile, port)

    def restart(self, profile):
        try:
            self.manager.restart(profile, self.settings)
        except ValueError as e:
            self.show_error(e)

    def new_profile(self):
        self.edit_profile(self.store.new_profile())

    def edit_profile(self, profile):
        dialog = ProfileDialog(profile, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.store.save_profile(dialog.result_profile)
                self.profiles = self.store.load_profiles()
                self.build_rows()
            except (OSError, ValueError) as e:
                self.show_error(e)

    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self.store.root, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.store.save_settings(dialog.result_settings)
                self.settings = dialog.result_settings
                self.update_setup_notice()
                self.render()
            except (OSError, ValueError) as e:
                self.show_error(e)

    def closeEvent(self, event):
        if self.manager.active():
            event.ignore()
            if not self.closing:
                self.closing = True
                self.device_timer.stop()
                self.notice.setText("Stopping owned rigctld processes before closing…")
                self.manager.stop_all()
                self.render()
        else:
            self.executor.shutdown(wait=False, cancel_futures=True)
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RigCtl-Launcher")
    try:
        window = MainWindow()
    except (OSError, ValueError, TypeError) as e:
        QMessageBox.critical(None, "Cannot load configuration", str(e))
        return 1
    # Qt recommends aboutToQuit cleanup; window close normally finishes first.
    app.aboutToQuit.connect(window.manager.shutdown)
    window.show()
    return app.exec()
