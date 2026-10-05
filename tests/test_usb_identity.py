import plistlib
from types import SimpleNamespace
import subprocess
import pytest
from rigctl_launcher.usb_identity import interface_ids, macos_interface_ids, metadata_interface_id


def interface(number, name):
    return {'bInterfaceNumber': number, 'IORegistryEntryChildren': [
        {'IORegistryEntryName': 'Driver', 'IORegistryEntryChildren': [
            {'IOCalloutDevice': f'/dev/cu.{name}', 'IODialinDevice': f'/dev/tty.{name}'}
        ]}
    ]}


def port(**changes):
    values = dict(device='/dev/cu.portA', vid=1, pid=2, location=None, hwid='')
    values.update(changes)
    return SimpleNamespace(**values)


def test_macos_maps_serial_nodes_to_nearest_numeric_interface():
    roots = [interface(1, 'portA'), interface(3, 'portB')]
    roots[0]['IORegistryEntryChildren'].append(interface(5, 'nested'))
    ids = macos_interface_ids(plistlib.dumps(roots))
    assert ids['/dev/cu.portA'] == ids['/dev/tty.portA'] == 'macos:usb-interface:1'
    assert ids['/dev/cu.portB'] == 'macos:usb-interface:3'
    assert ids['/dev/cu.nested'] == 'macos:usb-interface:5'


def test_macos_missing_number_never_guesses_from_path_suffix():
    node = interface(1, 'usbmodem12301')
    del node['bInterfaceNumber']
    assert macos_interface_ids(plistlib.dumps([node])) == {}


@pytest.mark.parametrize('number', ['1', -1, 256, True])
def test_macos_invalid_number(number):
    assert macos_interface_ids(plistlib.dumps([interface(number, 'portA')])) == {}


def test_macos_discovery_uses_readonly_bounded_registry_command(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args == ['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostInterface']
        assert kwargs['timeout'] == 2 and kwargs['shell'] is False
        return SimpleNamespace(stdout=plistlib.dumps([interface(1, 'portA')]))
    monkeypatch.setattr('rigctl_launcher.usb_identity.subprocess.run', run)
    assert interface_ids([port()], 'darwin')['/dev/cu.portA'] == 'macos:usb-interface:1'
    assert len(calls) == 1


def test_macos_legacy_class_fallback(monkeypatch):
    def run(args, **kwargs):
        roots = [] if args[-1] == 'IOUSBHostInterface' else [interface(1, 'portA')]
        return SimpleNamespace(stdout=plistlib.dumps(roots))
    monkeypatch.setattr('rigctl_launcher.usb_identity.subprocess.run', run)
    assert interface_ids([port()], 'darwin')['/dev/cu.portA'] == 'macos:usb-interface:1'


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('ioreg', 2), subprocess.CalledProcessError(1, 'ioreg')])
def test_registry_failure_preserves_safe_fallback(monkeypatch, error):
    def run(*a, **kw):
        raise error
    monkeypatch.setattr('rigctl_launcher.usb_identity.subprocess.run', run)
    assert interface_ids([port()], 'darwin') == {}


def test_bad_registry_output(monkeypatch):
    monkeypatch.setattr('rigctl_launcher.usb_identity.subprocess.run', lambda *a, **kw: SimpleNamespace(stdout=b'not a plist'))
    assert interface_ids([port()], 'darwin') == {}


def test_no_usb_ports_never_runs_registry_command(monkeypatch):
    monkeypatch.setattr('rigctl_launcher.usb_identity.subprocess.run', lambda *a, **kw: pytest.fail('Unnecessary registry query'))
    assert interface_ids([port(vid=None, pid=None)], 'darwin') == {}


def test_linux_reads_sysfs_metadata(tmp_path):
    (tmp_path / 'bInterfaceNumber').write_text('0a\n')
    assert metadata_interface_id(port(usb_interface_path=str(tmp_path)), 'linux') == 'linux:usb-interface:10'
    assert interface_ids([port(usb_interface_path=str(tmp_path))], 'linux')['/dev/cu.portA'] == 'linux:usb-interface:10'


def test_linux_location_fallback():
    assert metadata_interface_id(port(location='2-3.1:1.3'), 'linux') == 'linux:usb-interface:3'
    assert metadata_interface_id(port(location='2-3.1'), 'linux') is None


def test_windows_location_and_hardware_id():
    assert metadata_interface_id(port(location='1-2:x.0'), 'win32') == 'windows:usb-interface:0'
    assert metadata_interface_id(port(hwid='USB\\VID_1234&PID_5678&MI_0A\\SERIAL'), 'win32') == 'windows:usb-interface:10'
    assert metadata_interface_id(port(location='1-2', hwid='USB VID:PID=1234:5678'), 'win32') is None


def test_platforms_without_backend_do_not_guess():
    assert interface_ids([port()], 'unknown') == {}
