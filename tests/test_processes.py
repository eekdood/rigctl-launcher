from dataclasses import replace
import socket
import os
import time
import pytest
from rigctl_launcher.devices import Device
from rigctl_launcher.processes import LogBuffer
from conftest import wait_until


def ready(manager, session):
    wait_until(manager, lambda: 'fake listening' in session.logs.snapshot()[1])


def test_two_radios_stop_independently_and_preserve_port(manager, settings, profiles, devices):
    a = manager.start(profiles[0], devices[0], settings)
    b = manager.start(profiles[1], devices[1], settings)
    ready(manager, a)
    ready(manager, b)
    address = b.port
    pid = b.process.pid
    manager.stop(profiles[0].id)
    wait_until(manager, lambda: not a.active)
    assert a.state == 'Stopped'
    assert b.active and b.process.pid == pid and b.port == address
    assert '[stdout]' in a.logs.snapshot()[1] and '[stderr]' in a.logs.snapshot()[1]
    assert 'Process exited' in a.logs.snapshot()[1]


def test_no_duplicate_profile_or_equivalent_serial_claim(manager, settings, profiles, devices):
    a = manager.start(profiles[0], devices[0], settings)
    with pytest.raises(ValueError, match='already has'):
        manager.start(profiles[0], devices[1], settings)
    with pytest.raises(ValueError, match='already owned'):
        manager.start(profiles[1], replace(devices[0], path='/dev/tty.fakeA'), settings)
    with pytest.raises(ValueError, match='already owned'):
        manager.start(profiles[1], replace(devices[0], path='/dev/aliasA'), settings)
    assert a.active


def test_profile_port_conflict_and_override(manager, settings, profiles, devices):
    manager.start(profiles[0], devices[0], settings)
    duplicate_port = replace(profiles[1], preferred_port=profiles[0].preferred_port)
    with pytest.raises(ValueError, match='occupied'):
        manager.start(duplicate_port, devices[1], settings)
    b = manager.start(duplicate_port, devices[1], settings, override=profiles[2].preferred_port)
    ready(manager, b)
    assert b.port == profiles[2].preferred_port
    assert duplicate_port.preferred_port == profiles[0].preferred_port


def test_slots_remain_stable_and_reuse_vacated_slot(manager, settings, profiles, devices):
    settings.port_mode = 'slots'
    a = manager.start(profiles[0], devices[0], settings)
    b = manager.start(profiles[1], devices[1], settings)
    assert a.port == settings.slots[0] and b.port == settings.slots[1]
    manager.stop(profiles[0].id)
    wait_until(manager, lambda: not a.active)
    c = manager.start(profiles[2], devices[0], settings)
    assert c.port == settings.slots[0] and b.port == settings.slots[1]


def test_startup_exit_failure_keeps_output(manager, settings, profiles, devices):
    profile = replace(profiles[0], arguments=['--fake-mode', 'fail'])
    a = manager.start(profile, devices[0], settings)
    wait_until(manager, lambda: not a.active)
    assert a.state == 'Error' and '7' in a.error
    assert 'simulated startup failure' in a.logs.snapshot()[1]


def test_missing_executable_error(manager, settings, profiles, devices):
    profile = replace(profiles[0], executable='/definitely/not/an/executable')
    with pytest.raises(ValueError):
        manager.start(profile, devices[0], settings)
    a = manager.session(profile.id)
    assert a.state == 'Error' and not a.active
    assert 'Start failed' in a.logs.snapshot()[1]


def test_restart_retains_device_and_session_override(manager, settings, profiles, devices):
    a = manager.start(profiles[0], devices[0], settings, override=profiles[2].preferred_port)
    ready(manager, a)
    old_pid = a.process.pid
    manager.restart(profiles[0], settings)
    wait_until(manager, lambda: a.active and a.process.pid != old_pid)
    ready(manager, a)
    assert a.port == profiles[2].preferred_port and a.device == devices[0]


@pytest.mark.skipif(os.name == "nt", reason="Windows termination is immediate; SIGTERM cannot be ignored")
def test_force_stop_fallback(manager, settings, profiles, devices):
    a = manager.start(replace(profiles[0], arguments=['--fake-mode', 'stubborn']), devices[0], settings)
    ready(manager, a)
    started = time.monotonic()
    manager.stop(profiles[0].id)
    wait_until(manager, lambda: not a.active)
    assert time.monotonic() - started < 2
    assert 'killing owned process' in a.logs.snapshot()[1]


def test_disconnect_no_automatic_restart(manager, settings, profiles, devices):
    a = manager.start(profiles[0], devices[0], settings)
    ready(manager, a)
    manager.disconnected([])
    wait_until(manager, lambda: not a.active)
    assert 'disconnected' in a.error
    manager.disconnected(devices)
    assert not a.active


def test_external_process_is_untouched(manager, settings, profiles, devices, fake_executable):
    import subprocess
    external = subprocess.Popen([fake_executable, '-t', str(profiles[4].preferred_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        a = manager.start(profiles[0], devices[0], settings)
        manager.stop_all()
        wait_until(manager, lambda: not manager.active())
        assert external.poll() is None
    finally:
        external.terminate()
        external.wait(timeout=3)


def test_bounded_logs_and_display_clear():
    logs = LogBuffer(limit=20)
    logs.append('old')
    revision = logs.snapshot()[0]
    logs.append('new')
    assert logs.display_snapshot(revision) == 'new'
    assert logs.snapshot()[1] == 'oldnew'
    logs.append('x' * 100)
    assert len(logs.snapshot()[1]) <= 20
    assert logs.display_snapshot(revision) == 'x' * 20


def test_flood_unterminated_output_does_not_block(manager, settings, profiles, devices):
    a = manager.start(replace(profiles[0], arguments=['--fake-mode', 'flood']), devices[0], settings)
    ready(manager, a)
    assert len(a.logs.snapshot()[1]) <= a.logs.limit
    manager.stop(profiles[0].id)
    wait_until(manager, lambda: not a.active)


def test_application_quit_fallback_stops_owned_processes(manager, settings, profiles, devices):
    a = manager.start(replace(profiles[0], arguments=['--fake-mode', 'stubborn']), devices[0], settings)
    b = manager.start(profiles[1], devices[1], settings)
    ready(manager, a)
    ready(manager, b)
    manager.shutdown()
    assert not manager.active()
    assert a.state == 'Stopped' and b.state == 'Stopped'


def test_two_interfaces_on_same_radio_are_independent_claims(manager, settings, profiles, devices):
    selected = devices[0]
    sibling = replace(selected, path='/dev/cu.sibling', interface_id='fake:usb-interface:2')
    a = manager.start(profiles[0], selected, settings)
    b = manager.start(profiles[1], sibling, settings)
    ready(manager, a)
    ready(manager, b)
    assert a.active and b.active
    # A second path to the first interface still cannot claim it twice.
    with pytest.raises(ValueError, match='already owned'):
        manager.start(profiles[2], replace(selected, path='/dev/cu.alias'), settings)
    manager.disconnected([sibling])
    wait_until(manager, lambda: not a.active)
    assert b.active
