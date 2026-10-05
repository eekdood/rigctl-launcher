"""Offscreen Qt verification with fake metadata and a fake daemon only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from pathlib import Path
import time
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox
from rigctl_launcher.profiles import Store
from rigctl_launcher.ui import DeviceDialog, LogPane, MainWindow, ProfileDialog, SettingsDialog
from rigctl_launcher.processes import LogBuffer


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def pump(app, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Qt workflow did not complete')


@pytest.fixture
def window(app, tmp_path, profiles, settings, devices, monkeypatch):
    store = Store(tmp_path / 'configuration')
    for file in store.directory.glob('*.json'):
        file.unlink()
    store.save_profile(profiles[0])
    store.save_profile(profiles[1])
    store.save_settings(settings)
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[-1]))
    w = MainWindow(store=store, discovery=lambda: list(devices))
    w.manager.stop_timeout = .15
    w.show()
    pump(app, lambda: w.devices == devices)
    yield w, errors
    w.close()
    pump(app, lambda: not w.manager.active())
    w.close()
    app.processEvents()


def choose_device(app, index, remember=False):
    def accept():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, DeviceDialog)
        dialog.combo.setCurrentIndex(index + 1)
        dialog.remember.setChecked(remember)
        dialog.choose()
    QTimer.singleShot(20, accept)


def test_full_two_radio_ui_workflow_and_shutdown(app, window, profiles, devices, tmp_path):
    w, errors = window
    assert w.windowTitle() == 'RigCtl-Launcher'
    assert '(preferred)' in w.table.item(0, 2).text()
    choose_device(app, 0, remember=True)
    w.row_controls[profiles[0].id]['Start'].click()
    a = w.manager.session(profiles[0].id)
    pump(app, lambda: 'fake listening' in a.logs.snapshot()[1])
    assert w.profiles[0].match['serial_number'] == devices[0].serial_number
    assert 'location' not in w.profiles[0].match

    # Exercise Start on… and its nested device chooser through actual Qt dialogs.
    timer = QTimer()
    seen = set()
    override = profiles[2].preferred_port
    def accept_override():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QInputDialog) and 'port' not in seen:
            seen.add('port')
            dialog.setIntValue(override)
            dialog.accept()
        elif isinstance(dialog, DeviceDialog):
            dialog.combo.setCurrentIndex(2)
            dialog.choose()
    timer.timeout.connect(accept_override)
    timer.start(20)
    w.row_controls[profiles[1].id]['Start on…'].click()
    timer.stop()
    b = w.manager.session(profiles[1].id)
    pump(app, lambda: a.state.startswith('Running') and b.state.startswith('Running'))
    w.tick()
    assert a.port != b.port and b.port == override
    assert w.profiles[1].preferred_port == profiles[1].preferred_port
    assert w.table.item(1, 2).text() == f'127.0.0.1:{override}'
    assert 'unverified' in w.table.item(1, 3).text()
    assert not w.row_controls[profiles[0].id]['Start'].isEnabled()
    assert 'fake stderr' in w.log_panes[profiles[1].id].text.toPlainText()
    artifacts = Path('artifacts')
    artifacts.mkdir(exist_ok=True)
    name = 'native-ui-two-sessions.png' if os.environ.get('QT_QPA_PLATFORM') == 'cocoa' else 'ui-two-sessions.png'
    w.grab().save(str(artifacts / name))

    w.row_controls[profiles[0].id]['Stop'].click()
    pump(app, lambda: not a.active)
    assert b.active and b.port == override
    assert 'Process exited' in w.log_panes[profiles[0].id].text.toPlainText()
    # Normal window close also cleans up the still-running second fake daemon.
    w.close()
    pump(app, lambda: not w.isVisible())
    assert not b.active and not errors


def test_ambiguous_chooser_requires_explicit_selection(app, profiles, devices, monkeypatch):
    p = replace(profiles[0], match={'vid': devices[0].vid, 'pid': devices[0].pid})
    dialog = DeviceDialog(p, devices)
    assert dialog.combo.currentIndex() == 0
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[-1]))
    dialog.choose()
    assert errors and dialog.result() != QDialog.Accepted
    dialog.combo.setCurrentIndex(2)
    dialog.choose()
    assert dialog.device == devices[1]


def test_manual_chooser(app, profiles, devices):
    dialog = DeviceDialog(profiles[0], devices)
    dialog.use_manual.setChecked(True)
    dialog.manual.setText('/dev/manual-no-identity')
    dialog.choose()
    assert dialog.device.path == '/dev/manual-no-identity'
    assert not dialog.device.discovered


def test_profile_editor_and_settings(app, window, profiles):
    w, errors = window
    def fill_new_profile():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, ProfileDialog)
        dialog.name.setText('Added radio')
        dialog.model.setValue(2028)
        dialog.baud.setText('115200')
        dialog.save()
    QTimer.singleShot(20, fill_new_profile)
    w.new_profile()
    assert len(w.profiles) == 3 and w.table.rowCount() == 3
    created = next(p for p in w.profiles if p.name == 'Added radio')
    assert (created.model, created.baud) == (2028, 115200)
    def fill_settings():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, SettingsDialog)
        dialog.mode.setCurrentIndex(1)
        dialog.slots.setText('5004, 5002, 5000')
        dialog.save()
    QTimer.singleShot(20, fill_settings)
    w.edit_settings()
    assert w.settings.port_mode == 'slots'
    assert w.store.load_settings().slots == [5004, 5002, 5000]
    assert not errors


def test_logs_pause_search_clear_copy_save(app, tmp_path, monkeypatch):
    logs = LogBuffer()
    pane = LogPane(logs)
    pane.resize(700, 200)
    pane.show()
    logs.append(''.join(f'line {i}\n' for i in range(100)))
    pane.update_log()
    pane.pause.setChecked(True)
    pane.text.verticalScrollBar().setValue(0)
    logs.append('needle\n')
    pane.update_log()
    assert pane.text.verticalScrollBar().value() == 0
    assert 'needle' in pane.text.toPlainText()
    pane.search.setText('needle')
    pane.find()
    assert pane.text.textCursor().selectedText() == 'needle'
    pane.clear()
    assert pane.text.toPlainText() == ''
    logs.append('after clear\n')
    pane.update_log()
    assert pane.text.toPlainText() == 'after clear\n'
    pane.copy()
    assert 'needle' in app.clipboard().text()
    output = tmp_path / 'saved.log'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), ''))
    pane.save()
    assert 'needle' in output.read_text() and 'after clear' in output.read_text()
    pane.close()


def test_saved_usb_interface_is_selected_after_path_change(app, tmp_path, profiles, devices):
    chosen = replace(devices[0], interface_id='macos:usb-interface:1')
    sibling = replace(chosen, path='/dev/cu.sibling', interface_id='macos:usb-interface:3')
    store = Store(tmp_path / 'config')
    saved = replace(profiles[0], match=chosen.identity(), manual_device=chosen.path)
    store.save_profile(saved)
    loaded = next(p for p in store.load_profiles() if p.id == saved.id)
    moved = replace(chosen, path='/dev/cu.renumbered')
    dialog = DeviceDialog(loaded, [sibling, moved])
    assert dialog.combo.currentData() == moved
    assert 'macos:usb-interface:1' in dialog.combo.currentText()
    if os.environ.get('QT_QPA_PLATFORM') == 'cocoa':
        dialog.show()
        app.processEvents()
        Path('artifacts').mkdir(exist_ok=True)
        dialog.grab().save('artifacts/native-saved-interface.png')
        dialog.close()
    missing = DeviceDialog(loaded, [sibling])
    assert missing.combo.currentIndex() == 0


def test_first_launch_reminder_and_persistent_acknowledgement(app, tmp_path, fake_executable):
    from rigctl_launcher.profiles import Settings
    store = Store(tmp_path / 'config')
    store.save_settings(Settings(executable=fake_executable))
    w = MainWindow(store=store, discovery=lambda: [])
    w.show()
    assert w.profiles == [] and w.table.rowCount() == 0
    assert w.setup_panel.isVisible()
    assert 'installed separately' in w.setup_message.text()
    w.dismiss_setup()
    assert store.load_settings().setup_seen
    assert not w.setup_panel.isVisible()
    w.close()
    app.processEvents()
    reopened = MainWindow(store=store, discovery=lambda: [])
    reopened.show()
    assert not reopened.setup_panel.isVisible()
    reopened.close()
    app.processEvents()


def test_missing_binary_reminder_survives_acknowledgement(app, tmp_path):
    from rigctl_launcher.profiles import Settings
    store = Store(tmp_path / 'config')
    store.save_settings(Settings(executable=str(tmp_path / 'missing'), setup_seen=True))
    w = MainWindow(store=store, discovery=lambda: [])
    w.show()
    assert w.setup_panel.isVisible() and not w.setup_dismiss.isVisible()
    assert 'No default executable' in w.setup_message.text()
    w.close()
    app.processEvents()


def test_settings_browse_and_binary_feedback(app, tmp_path, fake_executable, monkeypatch):
    from rigctl_launcher.profiles import Settings
    dialog = SettingsDialog(Settings(executable=str(tmp_path / 'missing')), tmp_path)
    assert 'installed separately' in dialog.executable_status.text()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (fake_executable, ''))
    dialog.browse_executable()
    assert dialog.executable.text() == fake_executable
    assert 'Executable found' in dialog.executable_status.text()


def test_about_licenses_are_local_and_readable(app, monkeypatch, tmp_path):
    from rigctl_launcher.about import AboutDialog
    (tmp_path / 'third-party-notices.txt').write_text('Qt copyright and license notice')
    (tmp_path / 'gpl.txt').write_text('GPL terms available offline')
    monkeypatch.setattr('rigctl_launcher.about.legal_directory', lambda: tmp_path)
    dialog = AboutDialog()
    dialog.show()
    app.processEvents()
    assert dialog.documents.count() == 2
    assert 'Qt copyright' in dialog.text.toPlainText()
    dialog.documents.setCurrentIndex(1)
    assert dialog.text.toPlainText() == 'GPL terms available offline'
    dialog.close()
