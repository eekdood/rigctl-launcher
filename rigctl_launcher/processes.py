"""Subprocess lifecycle independent of Qt. poll() never waits for a child."""
from collections import deque
import codecs
from dataclasses import dataclass, field
import os
import shlex
import subprocess
import threading
import time
from .devices import same_interface
from .ports import allocate
from .executable import require_executable

LOG_CHARS = 250_000


class LogBuffer:
    def __init__(self, limit=LOG_CHARS):
        self.limit = limit
        self.lines = deque()
        self.size = 0
        self.revision = 0
        self.lock = threading.Lock()

    def append(self, text):
        with self.lock:
            text = text[-self.limit:]
            self.lines.append((self.revision + 1, text))
            self.size += len(text)
            while self.size > self.limit and self.lines:
                self.size -= len(self.lines.popleft()[1])
            self.revision += 1

    def snapshot(self):
        with self.lock:
            return self.revision, "".join(text for _, text in self.lines)

    def display_snapshot(self, after_revision):
        with self.lock:
            return "".join(text for revision, text in self.lines if revision > after_revision)

    def clear(self):
        with self.lock:
            self.lines.clear()
            self.size = 0
            self.revision += 1


@dataclass
class Session:
    profile_id: str
    logs: LogBuffer = field(default_factory=LogBuffer)
    process: subprocess.Popen | None = None
    device: object = None
    port: int | None = None
    state: str = "Stopped"
    error: str = ""
    started: float = 0
    stop_deadline: float | None = None
    threads: list = field(default_factory=list)
    restart: tuple | None = None
    exited_at: float | None = None

    @property
    def active(self):
        # Retain claims until poll has reaped the process and readers drained.
        return self.process is not None


class Manager:
    def __init__(self, stop_timeout=2.0):
        self.sessions = {}
        self.stop_timeout = stop_timeout

    def session(self, profile_id):
        return self.sessions.setdefault(profile_id, Session(profile_id))

    def start(self, profile, device, settings, override=None):
        session = self.session(profile.id)
        if session.active:
            raise ValueError("This profile already has a managed session")
        try:
            profile.validate()
            settings.validate()
            if not device.path.strip():
                raise ValueError("Select a serial device")
            for other in self.sessions.values():
                if other.active and same_interface(device, other.device):
                    raise ValueError(f"Serial interface is already owned by profile {other.profile_id}")
            port = allocate(settings, profile.preferred_port, [s.port for s in self.sessions.values() if s.active], override)
            executable = require_executable(profile.executable or settings.executable)
            args = [executable, "-m", str(profile.model), "-r", device.path, "-T", "127.0.0.1", "-t", str(port)]
            if profile.baud is not None:
                args += ["-s", str(profile.baud)]
            if profile.verbosity:
                args += ["-" + "v" * profile.verbosity]
            args += profile.arguments
            session.logs.append(f"\n[manager] Launch: {shlex.join(args)}\n[manager] CAT address: 127.0.0.1:{port}; process state does not verify radio response.\n")
            session.device, session.port = device, port
            session.error = ""
            session.stop_deadline = None
            session.exited_at = None
            session.started = time.monotonic()
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            session.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **kwargs)
            session.state = "Starting"
            session.threads = []
            for stream, label in ((session.process.stdout, "stdout"), (session.process.stderr, "stderr")):
                thread = threading.Thread(target=self._capture, args=(stream, label, session.logs), daemon=True)
                session.threads.append(thread)
                thread.start()
            return session
        except (OSError, ValueError) as e:
            session.state, session.error = "Error", str(e)
            session.logs.append(f"[manager] Start failed: {e}\n")
            raise ValueError(str(e)) from e

    @staticmethod
    def _capture(stream, label, logs):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            # Bounded reads also handle huge or unterminated lines.
            while data := os.read(stream.fileno(), 4096):
                text = decoder.decode(data)
                if text:
                    logs.append(f"[{label}] {text}")
            tail = decoder.decode(b"", final=True)
            if tail:
                logs.append(f"[{label}] {tail}")
        except OSError as e:
            logs.append(f"[manager] {label} capture failed: {e}\n")
        finally:
            stream.close()

    def stop(self, profile_id):
        session = self.session(profile_id)
        session.restart = None
        self._stop(session)

    def _stop(self, session):
        if session.process is not None and session.stop_deadline is None:
            session.state = "Stopping"
            session.stop_deadline = time.monotonic() + self.stop_timeout
            session.logs.append("[manager] Stopping owned process\n")
            try:
                session.process.terminate()
            except ProcessLookupError:
                pass

    def restart(self, profile, settings):
        session = self.session(profile.id)
        if not session.active:
            raise ValueError("Start the stopped profile first")
        session.restart = (profile, session.device, settings, session.port)
        self._stop(session)

    def poll(self):
        for session in list(self.sessions.values()):
            proc = session.process
            if proc is None:
                continue
            code = proc.poll()
            if code is not None:
                if session.exited_at is None:
                    session.exited_at = time.monotonic()
                if any(t.is_alive() for t in session.threads) and time.monotonic() - session.exited_at < 0.5:
                    continue
                stopped = session.stop_deadline is not None
                session.process = None
                session.state = "Stopped" if stopped else "Error"
                if not stopped:
                    session.error = f"rigctld exited with code {code}"
                session.logs.append(f"[manager] Process exited: {code}\n")
                pending, session.restart = session.restart, None
                if pending:
                    try:
                        self.start(*pending)
                    except ValueError:
                        pass
            elif session.stop_deadline is not None:
                if time.monotonic() >= session.stop_deadline:
                    session.logs.append("[manager] Stop timeout; killing owned process\n")
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    session.stop_deadline = time.monotonic() + self.stop_timeout
            elif time.monotonic() - session.started >= 0.4:
                session.state = "Running (radio unverified)"

    def disconnected(self, devices):
        for session in self.sessions.values():
            if session.active and session.stop_deadline is None and session.device.discovered and not any(same_interface(session.device, d) for d in devices):
                session.error = "Serial device disconnected; session stopped. Re-select device and start manually."
                session.logs.append(f"[manager] {session.error}\n")
                self.stop(session.profile_id)

    def stop_all(self):
        for profile_id in self.sessions:
            self.stop(profile_id)

    def shutdown(self):
        """Final application-quit fallback when the Qt event loop is ending.

        Normal window close uses asynchronous stop/poll instead.
        """
        self.stop_all()
        deadline = time.monotonic() + self.stop_timeout + 1.0
        while self.active() and time.monotonic() < deadline:
            self.poll()
            time.sleep(0.01)
        for session in self.sessions.values():
            if session.process is not None and session.process.poll() is None:
                try:
                    session.process.kill()
                except ProcessLookupError:
                    pass
        self.poll()

    def active(self):
        return any(s.active for s in self.sessions.values())
