"""Router dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.context import AppContext


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]
