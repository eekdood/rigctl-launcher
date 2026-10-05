from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid


def config_dir(name="rigctl-launcher"):
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support" / name
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / name
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / name


def migrate_config(destination, legacy):
    """Copy the previous app's data once, without modifying the original.

    Stage the complete copy before publishing it so a failed copy cannot
    leave a partial configuration that would block migration on next launch.
    An existing new configuration always takes precedence.
    """
    if destination.exists() or not legacy.is_dir():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rigctl-launcher-migrate-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "config"
        shutil.copytree(legacy, staged)
        try:
            staged.rename(destination)
        except FileExistsError:
            # Another app instance already completed the migration.
            if not destination.is_dir():
                raise


def validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("TCP port must be an integer from 1 to 65535")
    return port


@dataclass
class Profile:
    id: str
    name: str
    model: int
    baud: int | None = None
    match: dict = field(default_factory=dict)
    manual_device: str = ""
    preferred_port: int = 4532
    arguments: list[str] = field(default_factory=list)
    executable: str = ""
    verbosity: int = 3

    def validate(self):
        if not isinstance(self.id, str) or not self.id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in self.id):
            raise ValueError("Profile ID must contain letters, numbers, underscores or hyphens")
        if not isinstance(self.name, str) or not self.name.strip() or type(self.model) is not int or self.model <= 0:
            raise ValueError("Name and positive Hamlib model number are required")
        if self.baud is not None and (type(self.baud) is not int or self.baud <= 0):
            raise ValueError("Baud must be a positive integer or null")
        if not isinstance(self.manual_device, str) or not isinstance(self.executable, str):
            raise ValueError("Manual device and executable must be strings")
        validate_port(self.preferred_port)
        if type(self.verbosity) is not int or not 0 <= self.verbosity <= 5:
            raise ValueError("Verbosity must be 0–5")
        if not isinstance(self.match, dict) or set(self.match) - {"vid", "pid", "serial_number", "interface", "interface_id", "location", "path"}:
            raise ValueError("Unknown device identity field")
        for key, value in self.match.items():
            if key in {"vid", "pid"}:
                if type(value) is not int or not 0 <= value <= 65535:
                    raise ValueError("USB vendor/product IDs must be integers from 0 to 65535")
            elif not isinstance(value, str) or not value:
                raise ValueError("Identity strings must be nonempty")
        if not isinstance(self.arguments, list) or any(not isinstance(a, str) for a in self.arguments):
            raise ValueError("Additional arguments must be a JSON array of strings")
        # Keep managed resources authoritative, even for compact short options.
        reserved_short = set("mrstTvbpd")
        value_short = set("cPDCSWwxA")
        reserved_long = {"model", "rig-file", "serial-speed", "port", "listen-addr", "verbose", "bind-all", "ptt-file", "dcd-file"}
        for arg in self.arguments:
            if not arg or "\0" in arg:
                raise ValueError("Empty/NUL arguments are not allowed")
            long_name = arg[2:].split("=")[0] if arg.startswith("--") else ""
            managed_long = bool(long_name) and any(name.startswith(long_name) for name in reserved_long)
            managed_short = arg.startswith("-") and not arg.startswith("--") and len(arg) > 1 and arg[1] not in value_short and any(c in reserved_short for c in arg[1:])
            if arg == "--" or managed_long or managed_short:
                raise ValueError(f"Managed device, port, model, verbosity or bind argument is not allowed here: {arg}")
        for index, arg in enumerate(self.arguments):
            config = None
            if arg in {"-C", "--set-conf"}:
                if index + 1 >= len(self.arguments):
                    raise ValueError("Missing value for --set-conf/-C")
                config = self.arguments[index + 1]
            elif arg.startswith("--set-conf="):
                config = arg.split("=", 1)[1]
            elif arg.startswith("-C"):
                config = arg[2:]
            if config:
                for item in config.split(","):
                    if item.split("=", 1)[0].strip() in {"rig_pathname", "rig_path", "ptt_pathname", "dcd_pathname", "serial_speed"}:
                        raise ValueError("Device paths and baud must use the managed profile fields")
        return self


@dataclass
class Settings:
    executable: str = field(default_factory=lambda: shutil.which("rigctld") or "rigctld")
    port_mode: str = "profile"
    slots: list[int] = field(default_factory=lambda: [4532, 4534, 4536])
    setup_seen: bool = False

    def validate(self):
        if not isinstance(self.executable, str) or not self.executable.strip():
            raise ValueError("Choose a rigctld executable")
        if type(self.setup_seen) is not bool:
            raise ValueError("Setup acknowledgement must be true or false")
        if self.port_mode not in {"profile", "slots"}:
            raise ValueError("Unknown port assignment mode")
        if not isinstance(self.slots, list) or not self.slots or any(type(p) is not int for p in self.slots) or len(set(self.slots)) != len(self.slots):
            raise ValueError("Slots must be a nonempty ordered list of distinct ports")
        for port in self.slots:
            validate_port(port)
        return self


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else config_dir()
        if root is None:
            migrate_config(self.root, config_dir("rigctld-manager"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.directory = self.root / "profiles"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.errors = []

    def load_profiles(self):
        profiles = []
        self.errors = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                profile = Profile(**json.loads(path.read_text())).validate()
                if path.stem != profile.id:
                    raise ValueError("JSON filename must match profile ID")
                if any(p.id == profile.id for p in profiles):
                    raise ValueError("Duplicate profile ID")
                profiles.append(profile)
            except (ValueError, TypeError, OSError) as e:
                self.errors.append(f"{path.name}: {e}")
        return profiles

    def save_profile(self, profile):
        profile.validate()
        write_json(self.directory / f"{profile.id}.json", asdict(profile))

    def load_settings(self):
        path = self.root / "settings.json"
        return Settings(**json.loads(path.read_text())).validate() if path.exists() else Settings()

    def save_settings(self, settings):
        write_json(self.root / "settings.json", asdict(settings.validate()))

    @staticmethod
    def new_profile():
        return Profile(id=uuid.uuid4().hex, name="New radio", model=1)
