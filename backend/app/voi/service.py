"""VOI candidates and previews for the interactive view; volume reads run in job workers.

The slow step (reading the mask, finding components and the body midline) is cached per
image, mask, labels and region under `cache/voi/`; margin and minimum size are recomputed
in the API process on every request because they are arithmetic on the cached boxes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.errors import NotFound, ValidationProblem
from app.core.paths import is_within, realpath
from app.imaging.npy_convert import CACHE_DIR, WorkerRunner, atomic_write_cache
from app.voi.catalog import load
from app.voi.models import (
    VoiCandidate,
    VoiCandidates,
    VoiRegion,
    VoiRequest,
)

if TYPE_CHECKING:
    from types import ModuleType

ENGINE_REV = "9"  # bump when `engine.analyze` output changes, so stale cache entries are not read


def _engine() -> ModuleType:
    """`plugins` is importable once the task registry has loaded (`ensure_importable`)."""
    from plugins.voi import engine

    return engine


def regions() -> list[VoiRegion]:
    engine = _engine()
    return [VoiRegion(id=k, **v) for k, v in engine.REGIONS.items()]


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def _cache(project_dir: Path, name: str) -> Path:
    return project_dir / CACHE_DIR / "voi" / name


def analyze_worker(
    image: str,
    mask: str,
    values: list[int],
    protect: list[int],
    region: str,
    hints: dict[int, str],
    anatomy: dict[int, str],
    out: str,
) -> str | None:
    """Worker: write the `engine.analyze` JSON. Returns None on success or an error string."""
    try:
        engine = _engine()
        result = engine.analyze(image, mask, values, protect, region, hints, anatomy)
        atomic_write_cache(Path(out), json.dumps(result).encode())
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def preview_worker(spec_path: str, out: str) -> str | None:
    try:
        engine = _engine()
        spec = json.loads(Path(spec_path).read_text())
        data = engine.render_preview(spec["image"], engine.Candidate.from_json(spec["candidate"]))
        atomic_write_cache(Path(out), data)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def result_worker(image: str, mask: str, values: list[int], out: str) -> str | None:
    try:
        atomic_write_cache(Path(out), _engine().render_result(image, mask, values))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


class VoiService:
    def __init__(self, jobs: WorkerRunner, project_dir: Path) -> None:
        self.jobs = jobs
        self.project_dir = project_dir

    async def candidates(
        self,
        item_id: str,
        seg_id: str,
        req: VoiRequest,
        image: tuple[Path, str],
        mask: tuple[Path, str],
        project_labels: dict[str, int],
        mapping: dict[str, int],
    ) -> tuple[VoiCandidates, bool]:
        """Candidates plus whether a cache entry was written (the caller asks for a sweep)."""
        engine = _engine()
        preset = engine.REGIONS[req.region]
        names = req.labels or list(preset["labels"])
        if not names:
            raise ValidationProblem(
                "Choose the labels that make up the VOI",
                errors=[{"loc": ["body", "labels"], "msg": "required for a custom region"}],
            )
        organ = [] if req.labels else preset["organ"]
        values, missing = engine.file_values(names, project_labels, mapping, organ)
        hints = engine.side_hints(
            names, lambda n: engine.file_values(n, project_labels, mapping)[0]
        )
        anatomy = {
            v: side
            for organ, side in engine.ANATOMY.items()
            for v in engine.file_values([organ], project_labels, mapping)[0]
        }
        protect, _ = engine.file_values(
            [p for p in preset["protect"] if p in names], project_labels, mapping
        )
        margin = preset["margin_mm"] if req.margin_mm is None else req.margin_mm
        min_size = list(preset["min_size_mm"] if req.min_size_mm is None else req.min_size_mm)
        out = VoiCandidates(
            item_id=item_id,
            seg_id=seg_id,
            region=req.region,
            lateral=bool(preset["lateral"]),
            labels=names,
            missing_labels=missing,
            margin_mm=margin,
            min_size_mm=min_size,
            candidates=[],
        )
        if not values:
            return out, False
        key = _digest(
            ENGINE_REV,
            image[1],
            mask[1],
            values,
            protect,
            req.region,
            sorted(hints.items()),
            sorted(anatomy.items()),
        )
        path = _cache(self.project_dir, f"{key}.json")
        wrote = False
        if not path.is_file():
            err = await self.jobs.run_in_worker(
                analyze_worker,
                str(image[0]),
                str(mask[0]),
                values,
                protect,
                req.region,
                hints,
                anatomy,
                str(path),
            )
            if err:
                raise ValidationProblem(f"Cannot compute VOI candidates: {err}")
            wrote = True
        analysis = json.loads(path.read_text())
        out.shape, out.spacing_mm = analysis["shape"], analysis["zooms"]
        name_of = {v: k for k, v in project_labels.items()}
        for c in engine.reframe(analysis, margin, min_size):
            body = c.to_json()
            # file value → label name (through the set's mapping), for the card's breakdown
            body["label_ml"] = {
                name_of.get(int(mapping.get(v, v)) if mapping else int(v), f"label_{v}"): ml
                for v, ml in body["label_ml"].items()
            }
            token = _digest(key, body["crop"], body["tight"], body["id"])
            spec = _cache(self.project_dir, f"{token}.spec.json")
            if not spec.is_file():
                atomic_write_cache(
                    spec,
                    json.dumps(
                        {
                            "image": str(image[0]),
                            "candidate": body,
                        }
                    ).encode(),
                )
            out.candidates.append(VoiCandidate(**body, preview=token))
        return out, wrote

    async def preview(self, token: str) -> Path:
        if not token.isalnum():
            raise NotFound("unknown preview")
        out = _cache(self.project_dir, f"{token}.webp")
        if out.is_file():
            return out
        spec = _cache(self.project_dir, f"{token}.spec.json")
        if not spec.is_file():
            raise NotFound("preview expired; reload the candidates")
        err = await self.jobs.run_in_worker(preview_worker, str(spec), str(out))
        if err:
            raise ValidationProblem(f"Cannot render the preview: {err}")
        return out

    async def result_preview(self, run_id: str, output_dir: Path, n: int) -> Path:
        rows = load(output_dir)
        if not 0 <= n < len(rows):
            raise NotFound("no such VOI in this run")
        out = _cache(self.project_dir, f"run-{run_id}-{n}-r{ENGINE_REV}.webp")
        if out.is_file():
            return out
        row = rows[n]
        root = realpath(output_dir)
        files = [realpath(output_dir / str(row[k])) for k in ("image", "mask")]
        if not all(is_within(f, root) and f.is_file() for f in files):
            raise NotFound("the VOI files are missing from the run's folder")
        values = [int(v) for v in row.get("label_values") or []]
        err = await self.jobs.run_in_worker(
            result_worker, str(files[0]), str(files[1]), values, str(out)
        )
        if err:
            raise ValidationProblem(f"Cannot render the VOI: {err}")
        return out
