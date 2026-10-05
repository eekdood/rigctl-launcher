"""Platform USB interface metadata. Never opens serial devices.

pySerial exposes a display name for an interface, not necessarily its unique
number. macOS needs a read-only IORegistry query; Linux/Windows metadata can
usually provide an interface number directly. IDs are platform-namespaced:
CDC drivers may associate their serial node with a different USB interface
on another operating system, so importing a profile must require reselection.
"""
from pathlib import Path
import plistlib
import re
import subprocess
import sys


def macos_interface_ids(data):
    """Map serial nodes to the nearest enclosing USB interface descriptor."""
    result = {}

    def walk(node, number=None):
        if not isinstance(node, dict):
            return
        if "bInterfaceNumber" in node:
            value = node["bInterfaceNumber"]
            number = value if type(value) is int and 0 <= value <= 255 else None
        if number is not None:
            for key in ("IOCalloutDevice", "IODialinDevice"):
                path = node.get(key)
                if isinstance(path, str) and path:
                    result[path] = f"macos:usb-interface:{number}"
        for child in node.get("IORegistryEntryChildren", []):
            walk(child, number)

    for root in plistlib.loads(data):
        walk(root)
    return result


def metadata_interface_id(port, platform):
    """Extract a stable per-interface number rather than a friendly name."""
    if platform.startswith("linux"):
        directory = getattr(port, "usb_interface_path", None)
        if directory:
            try:
                number = int((Path(directory) / "bInterfaceNumber").read_text().strip(), 16)
                if 0 <= number <= 255:
                    return f"linux:usb-interface:{number}"
            except (OSError, ValueError):
                pass
        # Linux sysfs locations end with configuration.interface, e.g. 1-2:1.3.
        match = re.search(r":\d+\.(\d+)$", getattr(port, "location", None) or "")
        if match and 0 <= int(match[1]) <= 255:
            return f"linux:usb-interface:{int(match[1])}"
    elif platform == "win32":
        # pySerial retains the composite interface in its location string.
        match = re.search(r":x\.(\d+)$", getattr(port, "location", None) or "")
        if match and 0 <= int(match[1]) <= 255:
            return f"windows:usb-interface:{int(match[1])}"
        match = re.search(r"\bMI_([0-9a-f]{2})\b|&MI_([0-9a-f]{2})(?:\\|&|$)", getattr(port, "hwid", ""), re.I)
        if match:
            return f"windows:usb-interface:{int(match[1] or match[2], 16)}"
    return None


def interface_ids(ports, platform=None):
    platform = platform or sys.platform
    usb_ports = [p for p in ports if p.vid is not None and p.pid is not None]
    if not usb_ports:
        return {}
    if platform != "darwin":
        return {p.device: value for p in usb_ports if (value := metadata_interface_id(p, platform)) is not None}
    result = {}
    for usb_class in ("IOUSBHostInterface", "IOUSBInterface"):
        try:
            data = subprocess.run(
                ["/usr/sbin/ioreg", "-a", "-l", "-r", "-c", usb_class],
                capture_output=True, check=True, timeout=2, shell=False,
            ).stdout
            result.update(macos_interface_ids(data))
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError, TypeError):
            # Discovery remains usable; saved strong IDs never degrade into
            # broad matching when metadata is temporarily unavailable.
            continue
        if all(p.device in result for p in usb_ports):
            break
    return result
