# ADR-0001 Web app first; Electron as a thin shell later
Status: Accepted · Date: 2026-09-23

**Context.** Users run the app locally (Docker) and on remote no-sudo servers (udocker via VS Code port forwarding). A desktop build is wanted eventually.

**Decision.** Build a browser SPA served by the backend. Electron (P8) only wraps the same SPA, pointing at a backend URL, and adds native dialogs through a preload bridge. The Python backend is not bundled inside Electron.

**Consequences.** + One codebase, same UX everywhere; + remote servers work unchanged. − The desktop app still needs a running backend (Docker locally). The frontend must avoid Node APIs (FE-07).

**Rejected.** Electron-first with a bundled Python sidecar (PyInstaller): heavy packaging and no remote-server use. Tauri: same bundling problem, and no benefit for a web-first app.
