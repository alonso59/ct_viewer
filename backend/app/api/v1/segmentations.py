"""API-27 segmentation sets (ADR-0015); `default_seg` is set through API-03."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx
from app.core.errors import NotFound, ValidationProblem
from app.projects.models import SegmentationSet

router = APIRouter(tags=["segmentations"])


class SegmentationInfo(SegmentationSet):
    n_items: int = 0  # items with a mask in this set
    is_default: bool = False


class SegmentationPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    label_mapping: dict[str, int] | None = None


def _infos(ctx: Ctx, pid: str) -> list[SegmentationInfo]:
    cfg = ctx.workspace.get(pid)
    items = ctx.index.load(pid).items
    return [
        SegmentationInfo(
            **s.model_dump(),
            n_items=sum(1 for i in items if s.seg_id in i.masks),
            is_default=s.seg_id == cfg.default_seg,
        )
        for s in cfg.segmentations
    ]


@router.get("/projects/{pid}/segmentations", response_model=list[SegmentationInfo])
def list_segmentations(ctx: Ctx, pid: str) -> list[SegmentationInfo]:
    return _infos(ctx, pid)


@router.patch("/projects/{pid}/segmentations/{seg}", response_model=SegmentationInfo)
async def patch_segmentation(
    ctx: Ctx, pid: str, seg: str, body: SegmentationPatch
) -> SegmentationInfo:
    cur = ctx.workspace.get(pid).segmentation(seg)
    if cur is None:
        raise NotFound(f"Segmentation set {seg!r} not found")
    update: dict[str, object] = {}
    if body.name is not None:
        update["name"] = body.name.strip()
    if body.label_mapping is not None:
        values = {e.value for e in ctx.workspace.get(pid).label_map}
        bad = [k for k, v in body.label_mapping.items() if v not in values or not k.isdigit()]
        if bad:
            raise ValidationProblem(
                "label_mapping keys must be set values and targets project label values",
                errors=[{"loc": ["body", "label_mapping", k], "msg": "unknown"} for k in bad],
            )
        update["label_mapping"] = body.label_mapping
        update["unmatched"] = [u for u in cur.unmatched if str(u) not in body.label_mapping]
    await ctx.workspace.put_segmentation(pid, cur.model_copy(update=update))
    ctx.bus.publish(pid, "project.updated", {"fields": ["segmentations"]})
    return next(i for i in _infos(ctx, pid) if i.seg_id == seg)
