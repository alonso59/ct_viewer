"""Which items run and which are ready, shared by tasks and radiomics.

`not_ready` returns a stable reason code; callers map it to their own shapes (tasks: short text
in `missing`; radiomics: `errors.jsonl` codes, `causes.TEXT`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from app.ingest.codes import QcCode
from app.ingest.models import Item
from app.variables.service import VariableService

# QC codes that make an item's imported mask unusable
BLOCKING: Final[tuple[QcCode, ...]] = (
    QcCode.MISSING_PATH,
    QcCode.UNREADABLE_FILE,
    QcCode.OUTSIDE_ROOT,
    QcCode.MISSING_SEG,
    QcCode.AFFINE_MISMATCH,
    QcCode.SHAPE_MISMATCH,
)


def blocking(codes: Iterable[str]) -> str | None:
    """The first code that blocks reading the imported mask, in `BLOCKING` order."""
    have = set(codes)
    return next((c.value for c in BLOCKING if c.value in have), None)


Code = Literal["no_image", "modality", "no_mask", "label_missing", "blocked"]


@dataclass(frozen=True)
class NotReady:
    """`code` + params (`modality`, `seg_id`, `label`, `qc`)."""

    code: Code
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Problem:
    """A selection problem at `loc` (relative to `selection`)."""

    loc: list[str | int]
    msg: str
    rule: str


class _Selection(Protocol):
    item_ids: list[str] | None
    filter: Any
    scope: Any


async def resolve(
    items: Sequence[Item],
    by_id: Mapping[str, Item],
    sel: _Selection,
    var_ids: Callable[[dict[str, list[str]]], Awaitable[Iterable[str]]] | None = None,
) -> tuple[list[Item], list[Problem]]:
    """Active items of an explicit list, an Explorer filter, or all.

    `var_ids(var)` is awaited for a `filter.var` and returns the matching item ids.
    """
    problems: list[Problem] = []
    if sel.item_ids is not None and sel.filter is not None:
        problems.append(Problem(["filter"], "Use either item_ids or filter", "conflict"))
    out = [i for i in items if i.status == "active"]
    if sel.item_ids is not None:
        for n, iid in enumerate(sel.item_ids):
            it = by_id.get(iid)
            if it is None:
                problems.append(Problem(["item_ids", n], "Unknown item", "unknown"))
            elif it.status != "active":
                problems.append(Problem(["item_ids", n], f"Item is {it.status}", "inactive"))
        wanted = set(sel.item_ids)
        out = [i for i in out if i.item_id in wanted]
    f = sel.filter
    if f is not None:
        if f.phase:
            out = [i for i in out if i.phase.canonical in f.phase]
        if f.side:
            out = [i for i in out if i.side in f.side]
        if f.var and var_ids is not None:
            ok = set(await var_ids(f.var))
            out = [i for i in out if i.item_id in ok]
    if sel.scope is not None:
        out = [i for i in out if i.scope == sel.scope]
    return sorted(out, key=lambda i: i.item_id), problems


def var_ids(
    workspace: Any, store: Any, locks: Any, bus: Any, pid: str
) -> Callable[[dict[str, list[str]]], Awaitable[list[str]]]:
    """`resolve`'s variable-filter lookup for project `pid`."""

    async def ids(var: dict[str, list[str]]) -> list[str]:
        vs = VariableService(workspace, store, locks, bus)
        return list((await vs.filter_ids(pid, var))["items"])

    return ids


def not_ready(
    it: Item,
    *,
    need_image: bool = True,
    modalities: Iterable[str] | None = None,
    seg_id: str | None = None,
    labels: Iterable[str] = (),
    label_map: Mapping[str, int] | None = None,
) -> NotReady | None:
    """Why `it` can't run, or None. `labels_present` and the QC codes describe the `imported`
    set only, so other sets skip the label and QC checks."""
    if need_image and it.image is None:
        return NotReady("no_image")
    mods = list(modalities or [])
    if mods and it.modality is not None and it.modality not in mods:
        return NotReady("modality", {"modality": it.modality})
    if seg_id is None:
        return None
    if seg_id not in it.masks:
        return NotReady("no_mask", {"seg_id": seg_id})
    if seg_id != "imported":
        return None
    names = list(labels)
    if names and it.labels_present:
        values = label_map or {}
        for name in names:
            if values.get(name) not in it.labels_present:
                return NotReady("label_missing", {"seg_id": seg_id, "label": name})
    qc = blocking(it.warning_codes)
    if qc is not None:
        return NotReady("blocked", {"seg_id": seg_id, "qc": qc})
    return None
