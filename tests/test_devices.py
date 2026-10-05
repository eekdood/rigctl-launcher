from dataclasses import replace
import os
import pytest
from rigctl_launcher import devices as module
from rigctl_launcher.devices import Device, candidates, canonical_path, same_interface, unique_interfaces
from rigctl_launcher.profiles import Profile


def test_match_all_fields_and_current_path():
    profile = Profile('a', 'Radio', 1, match={'vid': 1, 'pid': 2, 'serial_number': 'ABC', 'interface_id': 'fake:usb-interface:0'}, manual_device='/dev/cu.old')
    right = Device('/dev/cu.new', vid=1, pid=2, serial_number='ABC', interface='CAT', interface_id='fake:usb-interface:0')
    wrong_serial = replace(right, serial_number='DEF')
    wrong_interface = replace(right, path='/dev/cu.ptt', interface='PTT', interface_id='fake:usb-interface:2')
    assert candidates(profile, [wrong_serial, wrong_interface, right]) == [right]


def test_ambiguity_is_preserved_and_missing_identity_does_not_match():
    profile = Profile('a', 'Radio', 1, match={'vid': 1, 'pid': 2})
    a, b = Device('/dev/cu.a', vid=1, pid=2), Device('/dev/cu.b', vid=1, pid=2)
    assert candidates(profile, [a, b, Device('/dev/cu.unknown')]) == [a, b]
    assert len(unique_interfaces([a, b])) == 2
    assert candidates(Profile('empty', 'Empty', 1), [a, b]) == []


def test_aliases_and_symlinks(tmp_path):
    if os.name != 'nt':
        assert canonical_path('/dev/cu.usbmodem123') == canonical_path('/dev/tty.usbmodem123')
    target = tmp_path / 'serial'
    target.touch()
    link = tmp_path / 'alias'
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == 'nt' and getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account lacks symlink privilege')
        raise
    assert same_interface(Device(str(target)), Device(str(link)))
    assert same_interface(Device('COM3'), Device('\\\\.\\com3'))


def test_physical_interface_identity_and_multiport_separation():
    a = Device('/dev/one', vid=1, pid=2, serial_number='ABC', interface='CAT', location='1:1', interface_id='fake:usb-interface:0')
    assert same_interface(a, replace(a, path='/dev/two'))
    assert not same_interface(a, replace(a, path='/dev/three', interface='PTT', location='1:2', interface_id='fake:usb-interface:2'))
    assert not same_interface(replace(a, interface=None, location=None, interface_id=None), replace(a, path='/dev/four', interface=None, location=None, interface_id=None))


def test_manual_fallback_never_chooses_unrelated_device():
    p = Profile('a', 'Radio', 1, manual_device='COM3' if os.name == 'nt' else '/dev/tty.old')
    a, b = (Device('\\\\.\\COM3'), Device('COM4')) if os.name == 'nt' else (Device('/dev/cu.old'), Device('/dev/cu.other'))
    assert candidates(p, [a, b]) == [a]
    p.match = {'serial_number': 'missing'}
    assert candidates(p, [a, b]) == []


def test_discovery_only_reads_metadata(monkeypatch):
    class Port:
        device = '/dev/fake'
        description = 'Fake'
        vid = 1
        pid = 2
        serial_number = 'ABC'
        interface = 'CAT'
        location = '1:1'
        hwid = 'FAKE'
    monkeypatch.setattr(module, 'interface_ids', lambda ports: {'/dev/fake': 'fake:usb-interface:0'})
    monkeypatch.setattr(module.list_ports, 'comports', lambda **kw: [Port()])
    import serial
    monkeypatch.setattr(serial, 'Serial', lambda *a, **kw: pytest.fail('Discovery opened a serial port'))
    discovered = module.discover()[0]
    assert discovered.path == '/dev/fake'
    assert discovered.interface_id == 'fake:usb-interface:0'


def test_identical_usb_metadata_never_hides_distinct_paths():
    a = Device('/dev/port1', vid=1, pid=2, serial_number='ABC', location='1-1')
    b = replace(a, path='/dev/port2')
    assert unique_interfaces([a, b]) == [a, b]
    assert not same_interface(a, b)  # No evidence identifying a serial interface.
    a = replace(a, interface='USB Serial')
    b = replace(b, interface='USB Serial')
    assert unique_interfaces([a, b]) == [a, b]


def test_remembered_interface_survives_renumbering_and_reordering():
    chosen = Device('/dev/cu.oldA', vid=1, pid=2, serial_number='RADIO', interface='USB Serial', location='1-1', interface_id='macos:usb-interface:1')
    sibling = replace(chosen, path='/dev/cu.oldB', interface_id='macos:usb-interface:3')
    profile = Profile('a', 'Radio', 1, match=chosen.identity(), manual_device=chosen.path)
    changed = replace(chosen, path='/dev/cu.newA', location='2-3', interface='New label')
    other = replace(sibling, path='/dev/cu.newB', location='2-3')
    assert candidates(profile, [other, changed]) == [changed]
    assert candidates(profile, [other]) == []  # Selected port absent: never use its sibling.
    assert candidates(profile, [replace(changed, interface_id=None), other]) == []
    assert candidates(profile, [replace(changed, serial_number='OTHER')]) == []
    assert same_interface(chosen, changed)
    assert not same_interface(chosen, sibling)
    assert 'path' not in profile.match and 'location' not in profile.match


def test_path_pinning_when_interface_identity_is_unavailable():
    selected = Device('/dev/cu.portA', vid=1, pid=2, serial_number='RADIO', interface='USB Serial')
    sibling = replace(selected, path='/dev/cu.portB')
    profile = Profile('a', 'Radio', 1, match=selected.identity(), manual_device=selected.path)
    assert candidates(profile, [sibling, selected]) == [selected]
    assert candidates(profile, [sibling]) == []
    assert candidates(profile, [replace(selected, path='/dev/cu.renumbered')]) == []
    if os.name != 'nt':
        assert candidates(profile, [replace(selected, path='/dev/tty.portA')])
    assert not same_interface(selected, sibling)  # Generic labels do not merge distinct ports.


def test_legacy_profile_preserves_last_selected_path_until_remembered_again():
    a = Device('/dev/cu.portA', vid=1, pid=2, serial_number='RADIO')
    b = replace(a, path='/dev/cu.portB')
    profile = Profile('a', 'Radio', 1, match={'vid': 1, 'pid': 2, 'serial_number': 'RADIO'}, manual_device=a.path if os.name == 'nt' else '/dev/tty.portA')
    assert candidates(profile, [b, a]) == [a]
    assert candidates(profile, [b]) == []
    assert candidates(profile, [replace(a, path='/dev/cu.new')]) == []


def test_interface_identity_without_serial_is_tied_to_usb_location():
    a = Device('/dev/cu.a', vid=1, pid=2, location='1-2', interface_id='macos:usb-interface:1')
    profile = Profile('a', 'Radio', 1, match=a.identity())
    assert candidates(profile, [replace(a, path='/dev/cu.new')])
    assert candidates(profile, [replace(a, location='1-3')]) == []
    assert candidates(profile, [replace(a, interface_id='macos:usb-interface:3')]) == []


def test_portable_profile_requires_reselection_on_another_os():
    a = Device('/dev/cu.a', vid=1, pid=2, serial_number='RADIO', interface_id='macos:usb-interface:1')
    profile = Profile('a', 'Radio', 1, match=a.identity())
    assert candidates(profile, [replace(a, path='COM3', interface_id='windows:usb-interface:0')]) == []
