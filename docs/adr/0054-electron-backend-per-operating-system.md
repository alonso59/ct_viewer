# ADR-0054 Electron: which backend the desktop app starts on each operating system
Status: Accepted (owner decision 2026-11-11: compose on Windows and macOS for development and tests only; production stays native) · Date: 2026-11-10
Amends: ADR-0001 (the desktop app still wraps the same SPA and never bundles Python). Stays within ADR-0051 §2 (compose is for development and quick tests, not a production deployment). R6 still holds: no Electron code before P7 is done.

**Context.** ADR-0001 says the desktop app points at "a running backend (Docker locally)". Since ADR-0051 the only production deployment is the native conda release (`scripts/rw-native.py`), which needs conda and systemd user services and so exists only on Linux; Docker compose stays as a development and quick-test path on any operating system, and udocker is gone. The P8 exit ("connects to a local Docker backend and a forwarded remote one") predates that split.

**Decision.** The shell offers three backend modes, chosen on first start and changeable in its settings; each ends as an API base URL handed to the SPA (FE-07):
1. **Linux — native release.** If a native release is installed for the user (its `release.json` and systemd user unit exist), the shell reads its port and opens it, and can start the stopped unit with `systemctl --user`. It never installs, upgrades or deploys a release itself.
2. **Windows and macOS — Docker compose, for development and tests.** If Docker is installed, the shell runs the repository's `docker-compose.yml` with the user's `.env` (`docker compose up -d`) and opens `127.0.0.1:${PORT}`. The shell labels this mode as a development and test backend. Docker Desktop and the data folders are the user's to set up; the shell checks and explains, never installs.
3. **Any OS — forwarded remote server.** A URL the user enters (for example a port VS Code Remote forwards, R7). The shell checks `/api/v1/health` and the version before loading the SPA. This is how Windows and macOS users reach production: a native release on a Linux server.
The shell adds only native folder dialogs through the preload bridge; every feature still runs in the browser build.

**Consequences.**
- + Every OS has a local path for development and tests, and production stays one native path.
- + Mode 2 is the use ADR-0051 §2 already allows, so no ADR changes; it adds no production support for compose.
- − Three modes to document; the version check must refuse a backend whose API major version differs.
- − The P8 exit criterion in `../product/ROADMAP.md` names the three modes.

**Rejected.** Bundling Python with PyInstaller or a conda-pack inside the app (ADR-0001: heavy, no remote use); the shell installing conda or Docker (R4 spirit, and a support burden); a native Windows/macOS release (no systemd; would be a second production path ADR-0051 removed); compose as a production desktop backend (ADR-0051 §2).
