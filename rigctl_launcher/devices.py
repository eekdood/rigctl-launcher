"""Discovery uses port metadata only: never opens a serial device."""
from dataclasses import dataclass
import os
import re
from serial.tools import list_ports
from .usb_identity import interface_ids


@dataclass(frozen=True)
class Device:
    path: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    interface: str | None = None
    location: str | None = None
    hwid: str = ""
    discovered: bool = True
    interface_id: str | None = None

    def identity(self):
        if self.interface_id and self.vid is not None and self.pid is not None and (self.serial_number or self.location):
            keys = ("vid", "pid", "serial_number", "interface_id") if self.serial_number else ("vid", "pid", "location", "interface_id")
            return {key: getattr(self, key) for key in keys}
        # A name such as "USB Serial" is not a per-port identity. Without a
        # strong interface ID, pin the path too: a lone remaining sibling
        # must not silently replace the interface remembered by this profile.
        keys = ("vid", "pid", "serial_number", "interface") if self.serial_number else ("vid", "pid", "interface", "location")
        identity = {key: getattr(self, key) for key in keys if getattr(self, key) is not None and getattr(self, key) != ""}
        identity["path"] = canonical_path(self.path)
        return identity

    def label(self):
        usb = f" USB {self.vid:04X}:{self.pid:04X}" if self.vid is not None and self.pid is not None else ""
        info = " · ".join(str(x) for x in (self.serial_number, self.interface, self.interface_id, self.location) if x)
        return f"{self.path} — {self.description}{usb}" + (f" · {info}" if info else "")


def discover():
    ports = list(list_ports.comports(include_links=True))
    ids = interface_ids(ports)
    return [Device(p.device, p.description or "", p.vid, p.pid, p.serial_number, p.interface, p.location, p.hwid, interface_id=ids.get(p.device)) for p in ports]


def canonical_path(path):
    # Normalize COM syntax before OS realpath, also when testing on macOS.
    com = re.fullmatch(r"(?:\\\\\.\\)?COM(\d+)", path, re.I)
    if com:
        return "COM" + str(int(com.group(1)))
    path = os.path.normcase(os.path.realpath(path))
    # macOS callout and dial-in nodes refer to the same serial interface.
    return re.sub(r"^/dev/(?:cu|tty)\.", "/dev/serial.", path)


def same_interface(a, b):
    if canonical_path(a.path) == canonical_path(b.path):
        return True
    if not a.interface_id or a.interface_id != b.interface_id:
        return False
    if a.vid is None or a.pid is None or (a.vid, a.pid) != (b.vid, b.pid):
        return False
    if a.serial_number and b.serial_number:
        return a.serial_number == b.serial_number
    return bool(a.location) and a.location == b.location


def candidates(profile, devices):
    if profile.match:
        result = [d for d in devices if all(
            canonical_path(d.path) == canonical_path(value) if key == "path" else getattr(d, key) == value
            for key, value in profile.match.items()
        )]
        # Old profiles remembered a selected path alongside broad metadata.
        # Until explicitly remembered again, honor that last selection instead
        # of automatically switching to a sibling with the same USB identity.
        if "interface_id" not in profile.match and "path" not in profile.match and profile.manual_device:
            result = [d for d in result if canonical_path(d.path) == canonical_path(profile.manual_device)]
        return result
    if profile.manual_device:
        return [d for d in devices if canonical_path(d.path) == canonical_path(profile.manual_device)]
    return []


def unique_interfaces(devices):
    result = []
    for device in devices:
        # Only proven path aliases can remove a choice. USB interface names
        # may repeat on multiport adapters, and locations may describe the
        # whole USB device. Matching metadata must never hide ambiguity.
        if not any(canonical_path(device.path) == canonical_path(d.path) for d in result):
            result.append(device)
    return result
