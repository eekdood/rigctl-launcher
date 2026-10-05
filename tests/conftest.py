from pathlib import Path
import os
import socket
import sys
import time
import pytest

from rigctl_launcher.devices import Device
from rigctl_launcher.processes import Manager
from rigctl_launcher.profiles import Profile, Settings


@pytest.fixture
def free_ports():
    # Hold sockets until all port numbers are selected so they are distinct.
    sockets = []
    try:
        for _ in range(5):
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            sockets.append(sock)
        return [s.getsockname()[1] for s in sockets]
    finally:
        for sock in sockets:
            sock.close()


@pytest.fixture
def fake_executable(tmp_path, monkeypatch):
    script = Path(__file__).with_name('fake_rigctld.py')
    target = tmp_path / ('fake rigctld.exe' if os.name == 'nt' else 'fake rigctld')
    # Absolute interpreter avoids relying on activated shell or PATH.
    target.write_text(f'#!{sys.executable}\n' + script.read_text().split('\n', 1)[1])
    target.chmod(0o755)
    if os.name == 'nt':
        # Route this synthetic executable only through Python on Windows;
        # still exercise real child processes, sockets and capture threads.
        import subprocess
        original = subprocess.Popen
        def fake_popen(args, *a, **kw):
            if isinstance(args, (list, tuple)) and os.path.normcase(str(args[0])) == os.path.normcase(str(target)):
                args = [sys.executable, str(script), *args[1:]]
            return original(args, *a, **kw)
        monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    return str(target)


@pytest.fixture
def settings(fake_executable, free_ports):
    return Settings(executable=fake_executable, slots=free_ports[:3])


@pytest.fixture
def profiles(free_ports):
    return [Profile(id=f'radio{i}', name=f'Radio {i}', model=1, baud=115200, preferred_port=p) for i, p in enumerate(free_ports)]


@pytest.fixture
def devices():
    return [Device('/dev/cu.fakeA', 'Fake radio A', 0x1234, 0x5678, 'A', 'CAT', '1-1', interface_id='fake:usb-interface:0'), Device('/dev/cu.fakeB', 'Fake radio B', 0x1234, 0x5678, 'B', 'CAT', '1-2', interface_id='fake:usb-interface:0')]


@pytest.fixture
def manager():
    m = Manager(stop_timeout=0.12)
    yield m
    m.stop_all()
    wait_until(m, lambda: not m.active())


def wait_until(manager, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        manager.poll()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for fake process state')
