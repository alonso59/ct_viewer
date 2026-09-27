"""App factory (BE-*). Routers are mounted under /api/v1 (docs/backend/API.md).

When `STATIC_ROOT/index.html` exists (the image, OPS-01), the SPA is served on the same port:
`/assets` as static files, other files under the root as-is, and `index.html` for any other
path (client-side routes). Paths under `/api` never fall back to the SPA (404 problem).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app import __version__
from app.api.v1 import router as v1_router
from app.config import Settings, get_settings
from app.context import AppContext, build_context
from app.core.errors import install_handlers
from app.core.logs import configure
from app.imaging import thumbnails

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
        ctx.server_lock.acquire()  # BE-05: refuse to start if another server holds it
        try:
            ctx.workspace.open()
            wire(ctx)
            await ctx.jobs.start()
            if ctx.cache_budget is not None:
                ctx.cache_budget.start()
            app.state.ctx = ctx
            if not ctx.guard.restricted:
                log.warning("ALLOWED_DATA_ROOTS is empty: path access is unrestricted (dev only)")
            yield
        finally:
            if ctx.cache_budget is not None:
                await ctx.cache_budget.stop()
            await ctx.jobs.shutdown()  # BE-13
            ctx.bus.close()
            ctx.server_lock.release()

    app = FastAPI(title="Radiology Workbench", version=__version__, lifespan=lifespan)
    install_handlers(app)
    app.include_router(v1_router, prefix="/api/v1")
    mount_spa(app, (settings or get_settings()).static_root)  # after every API router
    return app


def mount_spa(app: FastAPI, static_root: Path) -> bool:
    """Serve the SPA build from `static_root` if it has an `index.html`; returns whether it did."""
    root = static_root.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False
    if (root / "assets").is_dir():
        # Vite content-hashes asset names, so they are safe to cache.
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        f = (root / path).resolve()
        if path and f.is_file() and f.is_relative_to(root):
            return FileResponse(f)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True


def wire(ctx: AppContext) -> None:
    """Cross-service hooks (integration point)."""
    ctx.after_index.append(thumbnails.after_index_hook(ctx.workspace, ctx.index, ctx.jobs))
    # AUD-A4-16: jobs that write disposable caches trigger a CACHE_MAX_GB sweep
    ctx.jobs.on_finished.append(
        lambda info: ctx.cache_written() if info.kind in CACHE_WRITERS else None
    )


app = create_app()
