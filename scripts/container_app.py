"""Container entry point (OPS-01): the API app plus the SPA from STATIC_ROOT on one port.

Temporary home for SPA serving: BE ARCHITECTURE puts it in `backend/app/main.py`, which lane
P7-prep does not own (LANE_NOTES.md asks the integrator to move it there). Paths under `/api`
never fall back to `index.html`; any other unknown path does (client-side routes, FE-*).

    python scripts/container_app.py      # HOST, PORT, LOG_LEVEL from env (OPS-03)
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.main import app


def mount_spa(api: FastAPI, static_root: Path) -> None:
    root = static_root.resolve()
    index = root / "index.html"
    if not index.is_file():
        return
    if (root / "assets").is_dir():
        # Vite hashes asset names, so they can be cached forever.
        api.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @api.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        f = (root / path).resolve()
        if path and f.is_file() and f.is_relative_to(root):
            return FileResponse(f)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


try:
    settings = get_settings()  # invalid config (e.g. OPS-04) stops here, before binding the port
except ValidationError as e:
    sys.exit("refusing to start: " + "; ".join(err["msg"] for err in e.errors()))

mount_spa(app, settings.static_root)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)
