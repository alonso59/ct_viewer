"""App factory (BE-*). Routers are mounted under /api/v1 (docs/backend/API.md)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.v1 import router as v1_router
from app.config import Settings, get_settings
from app.context import AppContext, build_context
from app.core.errors import install_handlers
from app.core.logs import configure

log = logging.getLogger("app.main")


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
            app.state.ctx = ctx
            if not ctx.guard.restricted:
                log.warning("ALLOWED_DATA_ROOTS is empty: path access is unrestricted (dev only)")
            yield
        finally:
            await ctx.jobs.shutdown()  # BE-13
            ctx.bus.close()
            ctx.server_lock.release()

    app = FastAPI(title="Radiology Workbench", version=__version__, lifespan=lifespan)
    install_handlers(app)
    app.include_router(v1_router, prefix="/api/v1")
    return app


def wire(ctx: AppContext) -> None:
    """Cross-service hooks (integration point)."""


app = create_app()
