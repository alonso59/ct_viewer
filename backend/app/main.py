"""When `STATIC_ROOT/index.html` exists (the image), the SPA is served on the same port:
`/assets` as static files, other files under the root as-is, and `index.html` for any other
path (client-side routes). Paths under `/api` never fall back to the SPA (404/405 problem).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.routing import Match

from app import __version__
from app.api.v1 import router as v1_router
from app.config import Settings, get_settings
from app.context import build_context
from app.core.errors import install_handlers
from app.core.logs import configure
from app.imaging import thumbnails
from app.ingest.recycle import RecycleService
from app.tasks.dicom_resources import initialize as initialize_dicom_resources
from app.tasks.service import TaskService

log = logging.getLogger("app.main")
CACHE_WRITERS = frozenset({"mesh", "thumbnail", "open-convert"})


def create_app(settings: Settings | None = None, *, inline_jobs: bool = False) -> FastAPI:
    """`inline_jobs=True` (tests) runs job units in threads instead of worker processes."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        s = settings or get_settings()
        configure(s.log_level)
        ctx = build_context(s, inline_jobs=inline_jobs)
        s.workspace_root.mkdir(parents=True, exist_ok=True)
        ctx.server_lock.acquire()  # refuses to start if another server holds it
        try:
            ctx.workspace.open()
            initialize_dicom_resources(s)
            RecycleService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus).recover()
            ctx.after_index.append(thumbnails.after_index_hook(ctx.workspace, ctx.index, ctx.jobs))
            ctx.jobs.on_finished.append(
                lambda info: ctx.cache_budget.request() if info.kind in CACHE_WRITERS else None
            )
            await ctx.jobs.start()
            ctx.cache_budget.start()
            app.state.ctx = ctx
            await TaskService(
                s, ctx.registry, ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks
            ).recover_all()
            await ctx.source_operations.recover_all()
            if not ctx.guard.restricted:
                log.warning("ALLOWED_DATA_ROOTS is empty: path access is unrestricted (dev only)")
            yield
        finally:
            await ctx.cache_budget.stop()
            await ctx.jobs.shutdown()
            ctx.bus.close()
            ctx.workspace.close()
            ctx.server_lock.release()

    app = FastAPI(title="Radiology Workbench", version=__version__, lifespan=lifespan)
    install_handlers(app)
    app.include_router(v1_router, prefix="/api/v1")
    mount_spa(app, (settings or get_settings()).static_root)  # after every API router
    return app


def mount_spa(app: FastAPI, static_root: Path) -> None:
    root = static_root.resolve()
    index = root / "index.html"
    if not index.is_file():
        return
    if (root / "assets").is_dir():
        # Vite content-hashes asset names, so they are safe to cache.
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            allowed = {
                method
                for route in app.routes
                if route.matches(request.scope)[0] == Match.PARTIAL
                for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                if route.matches({**request.scope, "method": method})[0] == Match.FULL
            }
            if allowed:
                raise HTTPException(status_code=405, headers={"Allow": ", ".join(sorted(allowed))})
            raise HTTPException(status_code=404)
        f = (root / path).resolve()
        if path and f.is_file() and f.is_relative_to(root):
            return FileResponse(f)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
