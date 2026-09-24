"""API-22 item record."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.core.errors import NotFound, SourceMissing
from app.core.fsio import read_json
from app.ingest.schemas import ItemDetail

router = APIRouter(tags=["items"])


@router.get("/projects/{pid}/items/{iid}", response_model=ItemDetail)
def get_item(pid: str, iid: str, ctx: Ctx) -> ItemDetail:
    """Item record + `advanced` absolute paths + its warnings."""
    return ingest_service(ctx).item_detail(pid, iid)


@router.get("/projects/{pid}/items/{iid}/dicom-tags", response_model=dict[str, Any])
async def get_dicom_tags(pid: str, iid: str, ctx: Ctx) -> dict[str, Any]:
    """The item's DICOM JSON sidecar (DCM-04), read on demand only (DCM-05: PHI stays here)."""
    item = ctx.index.get_item(pid, iid)
    ref = item.extra.get("dicom_sidecar")
    if not isinstance(ref, str) or not ref:
        raise NotFound("item has no DICOM sidecar")
    path = ctx.workspace.resolver(pid).resolve(ref)
    if not path.is_file():
        raise SourceMissing("DICOM sidecar is missing")
    raw: Any = await asyncio.to_thread(read_json, path)
    if not isinstance(raw, dict):
        raise NotFound("DICOM sidecar is not a JSON object")
    return raw
