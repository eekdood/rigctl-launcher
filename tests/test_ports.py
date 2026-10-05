from dataclasses import replace
import socket
import pytest
from rigctl_launcher.ports import PortConflict, allocate, available
from rigctl_launcher.profiles import Settings


def test_slots_use_order_skip_external_and_owned():
    settings = Settings(port_mode='slots', slots=[4536, 4532, 4534])
    assert allocate(settings, 9000, check=lambda p: True) == 4536
    assert allocate(settings, 9000, owned=[4536], check=lambda p: p != 4532) == 4534
    with pytest.raises(PortConflict):
        allocate(settings, 9000, owned=settings.slots)


def test_profile_conflict_never_falls_back():
    with pytest.raises(PortConflict, match='4532'):
        allocate(Settings(), 4532, check=lambda p: p != 4532)
    assert allocate(Settings(), 4534, check=lambda p: True) == 4534


def test_session_override_does_not_mutate_preferences():
    settings = Settings(port_mode='slots')
    assert allocate(settings, 4532, override=5000, check=lambda p: True) == 5000
    assert settings.slots == [4532, 4534, 4536]
    with pytest.raises(PortConflict, match='5000'):
        allocate(settings, 4532, override=5000, check=lambda p: False)


def test_real_external_socket_conflict(free_ports):
    port = free_ports[0]
    with socket.socket() as external:
        external.bind(('127.0.0.1', port))
        external.listen()
        assert not available(port)
        with pytest.raises(PortConflict):
            allocate(Settings(), port)
    assert available(port)


@pytest.mark.parametrize('port', [0, -1, 65536, '4532', True])
def test_invalid_port(port):
    with pytest.raises(ValueError):
        allocate(Settings(), port)
