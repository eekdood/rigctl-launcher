# Verification

Automated checks cover profile/settings persistence, empty fresh-install configuration, external executable availability, first-launch reminders, serial metadata matching, USB interface identity, aliases, port conflicts, owned process lifecycle, bounded logs and UI workflows.

All process tests use a fake daemon and synthetic serial metadata. No radio serial port is opened and no CAT/PTT command is sent. POSIX-only signal behavior is explicitly marked where the operating system's termination semantics differ. Windows fake executables are routed through the Python test harness while preserving real subprocess, loopback socket and log-capture behavior.

The source application has been exercised with offscreen and native UI widgets. Individual release support must be based on testing the packaged application on its advertised target. CI build success alone does not establish hardware or driver compatibility.

Local screenshots and build artifacts are ignored by Git and excluded from the application package. Test profiles, identifiers and paths are synthetic; personal configuration is not used as a test fixture or shipped as a default.

Release preparation checks: 99 automated tests passed, including nine UI tests. All nine UI tests also passed using native macOS widgets. A macOS ARM64 PyInstaller app was built and passed an isolated empty-configuration smoke test. Windows and Linux jobs are configured but have not yet run; their packages and native behavior remain unverified.

Run the checks documented in `readme.md`. Public documentation does not include machine-specific device paths, local installation paths or private script references.
