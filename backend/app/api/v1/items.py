"""API-22 item record."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.ingest.schemas import ItemDetail

router = APIRouter(tags=["items"])


@router.get("/projects/{pid}/items/{iid}", response_model=ItemDetail)
def get_item(pid: str, iid: str, ctx: Ctx) -> ItemDetail:
    """Item record + `advanced` absolute paths + its warnings."""
    return ingest_service(ctx).item_detail(pid, iid)
