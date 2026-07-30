"""
Standalone entry point for the Radiology WebUI.

Usage
-----
  python -m app                                 # starts on port 8000, opens browser
  python -m app --data-dir /path/to/Dataset420  # pre-select dataset folder
  python -m app --port 9000                     # custom port
  python -m app --no-browser                    # server-only, no browser pop-up

Environment variables (can be combined with CLI flags):
  DATASET_DIR   — same as --data-dir
  PORT          — same as --port
  OPEN_BROWSER  — set to "false" / "0" to disable auto-open (useful in Docker)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _resolve_static_root() -> str | None:
    """
    Determine the frontend static files directory.

    Priority:
      1. STATIC_ROOT env var (explicit override)
      2. PyInstaller bundle: <_MEIPASS>/static
      3. Adjacent frontend/dist when running from source
      4. /app/static (Docker default)
    """
    explicit = os.environ.get("STATIC_ROOT", "").strip()
    if explicit:
        return explicit

    # PyInstaller frozen bundle
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "static")  # type: ignore[attr-defined]

    # Running from source: look for frontend/dist next to the backend directory
    source_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if source_dist.is_dir():
        return str(source_dist)

    return None  # fallback: let main.py use its default (/app/static)


def _parse_open_browser_env() -> bool:
    value = os.environ.get("OPEN_BROWSER", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="radiology-webui",
        description="Radiology WebUI — local annotation server",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help="Dataset folder to pre-load (sets DATASET_DIR env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        default=None,
        help="Port to listen on (default: 8080 or PORT env var)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically on startup",
    )
    args = parser.parse_args()

    # Apply CLI overrides to environment before importing the app
    if args.data_dir:
        os.environ["DATASET_DIR"] = str(args.data_dir)

    static_root = _resolve_static_root()
    if static_root:
        os.environ["STATIC_ROOT"] = static_root

    port = args.port or int(os.environ.get("PORT", "8080"))
    os.environ["PORT"] = str(port)

    # Check if the port is already in use and fail fast with a clear message
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
        _s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            _s.bind(("0.0.0.0", port))
        except OSError:
            print(f"\n  ERROR: Port {port} is already in use.")
            print(f"  Try: radiology-webui --port {port + 1}\n")
            sys.exit(1)

    open_browser = (not args.no_browser) and _parse_open_browser_env()

    if open_browser:
        url = f"http://localhost:{port}"
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
        print(f"  Browser will open at {url}")

    print(f"  Starting Radiology WebUI on http://0.0.0.0:{port}")
    if args.data_dir:
        print(f"  Dataset folder: {args.data_dir}")
    if static_root:
        print(f"  Static root:    {static_root}")

    import uvicorn
    # Import the app object directly — avoids string-based module lookup
    # which fails inside a PyInstaller frozen bundle.
    from app.main import app  # noqa: PLC0415
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
