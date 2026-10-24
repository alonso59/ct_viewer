"""DCM-16: complete dry-run plans in bounded workspace chunks, manifest published last."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.core.cursors import decode_cursor, encode_cursor
from app.core.errors import ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.tasks.models import SeriesPlan

CHUNK_ROWS = 500


class SourcePlanPage(BaseModel):
    items: list[SeriesPlan]
    total: int
    next_cursor: str | None = None
    generation: str | None = None


def write_plan(root: Path, rows: list[dict[str, Any]]) -> str:
    generation = new_ulid()
    counts = {"convert": 0, "skip": 0}
    for start in range(0, len(rows), CHUNK_ROWS):
        page = [
            SeriesPlan.model_validate(row).model_dump() for row in rows[start : start + CHUNK_ROWS]
        ]
        for row in page:
            counts[row["action"]] += 1
        atomic_write_json(root / f"{start // CHUNK_ROWS:06d}.json", page)
    atomic_write_json(
        root / "index.json",
        {
            "version": 1,
            "generation": generation,
            "total": len(rows),
            "counts": counts,
        },
    )
    return generation


def read_plan_page(
    root: Path,
    *,
    limit: int = 50,
    cursor: str | None = None,
    action: Literal["convert", "skip"] | None = None,
) -> SourcePlanPage:
    if not 1 <= limit <= CHUNK_ROWS:
        raise ValidationProblem("Plan page size must be in 1..500")
    index = read_json(root / "index.json")
    generation = str(index["generation"])
    fence = generation + ":" + (action or "all")
    offset = decode_cursor(cursor, fence)
    total = int(index["counts"][action]) if action else int(index["total"])
    found: list[SeriesPlan] = []
    skipped = 0
    start = 0 if action else offset // CHUNK_ROWS
    chunks = (int(index["total"]) + CHUNK_ROWS - 1) // CHUNK_ROWS
    for chunk in range(start, chunks):
        rows = read_json(root / f"{chunk:06d}.json")
        for position, row in enumerate(rows, chunk * CHUNK_ROWS):
            if action:
                if row["action"] != action:
                    continue
                position, skipped = skipped, skipped + 1
            if position >= offset:
                found.append(SeriesPlan.model_validate(row))
            if len(found) == limit:
                break
        if len(found) == limit:
            break
    following = encode_cursor(fence, offset + len(found)) if offset + len(found) < total else None
    return SourcePlanPage(items=found, total=total, next_cursor=following, generation=generation)
