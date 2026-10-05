import socket
from .profiles import validate_port


class PortConflict(ValueError):
    pass


def available(port):
    validate_port(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # Do not enable SO_REUSEADDR: this check must detect other listeners.
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def allocate(settings, preferred, owned=(), override=None, check=available):
    owned = set(owned)
    ports = [validate_port(override)] if override is not None else ([validate_port(preferred)] if settings.port_mode == "profile" else settings.slots)
    for port in ports:
        if port not in owned and check(port):
            return port
    if override is not None or settings.port_mode == "profile":
        raise PortConflict(f"127.0.0.1:{ports[0]} is occupied or unavailable. Stop its owner or use Start on…")
    raise PortConflict("No configured TCP slots are available")
