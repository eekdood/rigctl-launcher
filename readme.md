# RigCtl-Launcher

A desktop manager for a separately installed Hamlib `rigctld`. Select a radio profile and serial interface, assign a local TCP port, start or stop independent daemon sessions, and view their logs. CAT clients connect directly to each daemon at its displayed `127.0.0.1:port` address.

The app does not install or bundle Hamlib. It does not provide a CAT proxy, radio tuning controls, terminal emulation, audio routing, remote access, automatic client configuration, or companion application launching.

## Install and launch

For packaged releases, download the build matching your operating system and processor from the repository's Releases page. Extract the archive; its folder contains the application, documentation, inventory and third-party notices. Keep those files together when redistributing it. Packaged builds include the application's Python and UI runtime; Hamlib remains a separate prerequisite. Supported platforms and signing status will be stated in each release. Packaging is currently being prepared; native support is not implied by a successful automated build alone.

For a source installation, use Python 3.11 or newer and an isolated environment:

```sh
python -m venv .venv
```

Activate that environment using your Python environment manager, then:

```sh
python -m pip install -e .
python -m rigctl_launcher
```

Alternatively, install the project in an environment managed by `uv`. The console command is `rigctl-launcher`.

Install Hamlib separately using a method suitable for your system. In **Settings**, select its `rigctld` executable or use **Browse** to locate it. On first launch the app explains this requirement. If the executable cannot be found, a reminder stays visible, and attempts to start a session report a useful error. These checks only inspect executable availability; they do not open serial devices or verify that a radio responds.

## Configure a radio

Fresh installations start with **no radio profiles**, no saved device identities and no machine-specific executable paths. Defaults are profile-port assignment, ordered slots `4532, 4534, 4536`, and loopback-only listening. Existing user profiles/settings are preserved across upgrades.

1. Choose **New profile**, enter a name and your radio's Hamlib model number, and set a baud rate if the radio requires one. Check those values against your radio and Hamlib documentation.
2. Save a preferred TCP port. The executable override can remain blank to inherit Settings. Additional arguments are a JSON array; model, device, baud, TCP port, bind address and verbosity use dedicated fields.
3. Choose **Start** and select the intended serial interface. Discovery reads metadata without opening serial ports. If multiple devices match, you must choose; the app never blindly takes the first.
4. Check **Remember this serial interface** to save its identity. Strong USB interface identities follow device-path changes. If reliable metadata is unavailable, the choice is pinned to its exact path; a changed path requires reselection. A missing saved interface never silently falls back to a sibling port.
5. Configure your CAT client with the displayed host and assigned port. Start another radio on a distinct interface and port; either session can be stopped independently.

`examples/profile.json` illustrates the file format and is never automatically imported. Its model is a placeholder that must be replaced for a real radio. The example contains no device path, executable override or saved USB identity.

## Ports, sessions and logs

**Profile port** is the default mode and reports conflicts rather than silently changing ports. **First available slot** uses the first available entry from Settings' ordered list. **Start on…** provides a session-only override. External listeners are checked, and stopping a session never renumbers the others.

**Running (radio unverified)** means the owned process is alive; it does not prove CAT response or TCP readiness. Each profile has a separate log tab. Capture continues while scrolling is paused. Search wraps through the display. **Clear display** hides existing text while Copy/Save still include the retained capture. Logs are bounded to 250,000 characters per profile and survive stopped/failed sessions until application exit.

Start, Stop and Restart target independent owned processes. Normal window close terminates them, with a bounded forced-stop fallback. Detected disconnects stop affected sessions. Automatic restart/reconnection is not provided.

## Configuration and architecture

User profiles and settings live in the operating system's per-user application configuration directory, shown in Settings. They are separate from the source and installed application. JSON profile filenames must match their `id`. Existing configurations from the previous application name are copied once to the current configuration directory without modifying the originals.

`profiles.py` handles validation and storage. `devices.py` and `usb_identity.py` handle metadata, matching and per-interface identities. `ports.py` handles allocation/conflicts. `executable.py` checks the external executable. `processes.py` manages children and bounded capture independently of Qt. `ui.py` provides the desktop interface.

USB metadata quality varies. Changing firmware, USB configuration or operating system may require reselection. The app protects interfaces claimed by its own sessions, not those owned by another application. There is a small race between checking a TCP port and the daemon binding it; failures appear in logs. Unknown manual devices cannot reliably be monitored for unplug events. Logs are in memory until explicitly saved, and stdout/stderr ordering is approximate.

## Development and releases

Install development dependencies in your isolated environment:

```sh
python -m pip install -e '.[test,build]'
python -m pytest -q
python -m compileall -q rigctl_launcher tests
```

Tests use synthetic device metadata and a fake daemon. No real radio serial port is opened and no CAT/PTT command is sent. See `verification.md` for validation results and `release.md` for branch, build and publication rules.

To build an archive on the current operating system, install the build extra and run `python packaging/build.py`. The script verifies application metadata and an empty first launch using temporary configuration before producing an archive, dependency inventory and SHA-256 checksum under `artifacts/packages/`. Filenames include the version from `pyproject.toml`, operating system and processor architecture. That same version is used for native application metadata. Each build replaces this generated output directory.

Run `python packaging/sources.py` afterward to produce matching source downloads, provider recipes and build instructions for the native CI artifact. Public releases offer the application archives, one combined sources ZIP for all platforms, and `checksums.txt`. Inventories are included inside the downloads. About / Licenses provides local license texts and a link to the matching release.

Source repository: [eekdood/rigctl-launcher](https://github.com/eekdood/rigctl-launcher). The project uses GPLv3; see [license.txt](license.txt). Hamlib remains a separately installed dependency. Packaged dependencies retain their own licenses.

For changes, start a short-lived branch from current `main` and submit a pull request into `main`. Contributors can use a fork. After the checks pass, squash and merge, then delete the branch. See [release.md](release.md) for the repository and release workflow.
