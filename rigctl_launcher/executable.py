"""Locate an explicitly selected external executable without running it."""
from pathlib import Path
import shutil

INSTALL_MESSAGE = (
    "RigCtl-Launcher requires Hamlib's rigctld to be installed separately. "
    "This app does not bundle or install Hamlib. Select the rigctld executable "
    "in Settings, or correct this profile's executable override."
)


def locate_executable(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return shutil.which(str(Path(value.strip()).expanduser()))
    except (OSError, ValueError):
        return None


def require_executable(value):
    located = locate_executable(value)
    if located is None:
        raise ValueError(f"Executable not found or not executable: {value}. {INSTALL_MESSAGE}")
    return located
