"""Radiomics service: validate, profiles, selection, estimate, runs, exports (RAD-01..11).

Stateless: routers build one per request. Only this (API) process writes `run.json`,
`units.jsonl`, `errors.jsonl`, profiles and the compacted outputs, under the project lock
(BE-05); workers write only their part files (`worker.py`). Paths are resolved here (BE-02)
and workers get absolute paths. Study variables are never copied into features (ANA-03).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from app.core import reviewer as reviewer_stamp
from app.core.errors import (
    FormatVersionUnsupported,
    JobConflict,
    NotFound,
    Problem,
    ValidationProblem,
    issue_errors,
)
from app.core.fsio import append_jsonl, atomic_write_json, read_json, read_jsonl, write_jsonl_atomic
from app.core.ids import new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.imaging import npy_convert
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.jobs.runs import RunStore
from app.jobs.types import JobInfo, JobSpec, WorkUnit
from app.projects.models import SegmentationSet
from app.projects.service import Workspace
from app.radiomics import causes, ibsi, worker
from app.radiomics import settings as st
from app.radiomics.engine import RadiomicsEngine, get_engine
from app.radiomics.models import (
    RESUMABLE_RUN,
    TERMINAL_RUN,
    Cell,
    EstimateRequest,
    EstimateResult,
    FeaturesTable,
    Issue,
    Profile,
    ProfileCreate,
    ProfileEngine,
    RadiomicsSettings,
    RunCounts,
    RunDetail,
    RunEngine,
    RunError,
    RunInput,
    RunProgress,
    RunRecord,
    RunRequest,
    RunSelection,
    RunStatus,
    RunSummary,
    Selection,
    ValidateRequest,
    ValidateResult,
)
from app.selection import readiness

log = logging.getLogger("app.radiomics")

RADIOMICS = "radiomics"
PROFILES = "profiles"
RUNS = "runs"
UNITS = "units.jsonl"
ERRORS = "errors.jsonl"
FEATURES = "features.parquet"
DIAGNOSTICS = "diagnostics.parquet"
SAMPLE_ITEMS: Final = 3
CANCEL_WAIT_S: Final = 30.0
MSG_NOTHING: Final = "Nothing to extract"
HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
ID_COLS: Final = (
    "run_id", "item_id", "case_id", "scan_idx", "scope", "side", "phase", "phase_at_run", "label"
)  # fmt: skip


def _nothing(loc: list[str | int]) -> Issue:
    return Issue(loc=loc, msg=MSG_NOTHING, rule="nothing")


def _write_parquet_atomic(path: Path, table: pa.Table) -> None:
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def _parse_key(key: str) -> tuple[str, int]:
    item_id, _, label = key.rpartition("__")
    return item_id, int(label)


def _row(item_id: str, label: int, kind: str, code: str, detail: str | None = None) -> RunError:
    """An `errors.jsonl` row with a cause code and its plain text (AUD-A2-05)."""
    return RunError(
        item_id=item_id,
        label=label,
        kind=kind,  # type: ignore[arg-type]
        error=causes.text(code),
        code=code,
        detail=detail,
        at=utc_now(),
    )


def _not_ready(it: Item, seg_id: str) -> str | None:
    """TSK-04 preflight of one item for one set (`readiness.not_ready`): the skip code or None."""
    r = readiness.not_ready(it, seg_id=seg_id)
    if r is None:
        return None
    if r.code == "no_mask":
        return "missing_seg" if seg_id == "imported" else "no_mask"
    return r.params["qc"] if r.code == "blocked" else r.code


def _empty_features() -> pa.Table:
    return worker.FEATURE_SCHEMA.empty_table()


def _load_features(run_dir: Path) -> pa.Table:
    """Compacted `features.parquet`, or the parts so far (running/cancelled runs)."""
    f = run_dir / FEATURES
    if f.is_file():
        return pq.read_table(f)
    parts = sorted((run_dir / worker.PARTS).glob("*.parquet"))
    if not parts:
        return _empty_features()
    tables = [pq.read_table(p).replace_schema_metadata(None) for p in parts]
    return pa.concat_tables(tables)


def _diag_str(v: Any) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v)


def _compact(run_dir: Path) -> int:
    """Parts → `features.parquet` + `diagnostics.parquet`; returns the distinct feature count."""
    run_id = run_dir.name
    parts = sorted((run_dir / worker.PARTS).glob("*.parquet"))
    tables = [pq.read_table(p).replace_schema_metadata(None) for p in parts]
    features = pa.concat_tables(tables) if tables else _empty_features()
    _write_parquet_atomic(run_dir / FEATURES, features)
    rows: list[dict[str, Any]] = []
    for p in parts:
        item_id, label = _parse_key(p.name[: -len(".parquet")])
        d = worker.read_diagnostics(p)
        vc = d.get("Mask-original_VoxelNum")
        row: dict[str, Any] = {
            "run_id": run_id,
            "item_id": item_id,
            "label": label,
            "voxel_count": int(vc) if isinstance(vc, int | float) else None,
            "bbox": _diag_str(d.get("Mask-original_BoundingBox")),
            "spacing": _diag_str(d.get("Image-original_Spacing")),
            "image_hash": _diag_str(d.get("Image-original_Hash")),
            "mask_hash": _diag_str(d.get("Mask-original_Hash")),
        }
        for k, v in d.items():
            row[k] = _diag_str(v)
        rows.append(row)
    fixed = ["run_id", "item_id", "label", "voxel_count", "bbox", "spacing", "image_hash"]
    fixed.append("mask_hash")
    extra = sorted({k for r in rows for k in r} - set(fixed))
    cols: dict[str, pa.Array] = {}
    for name in [*fixed, *extra]:
        typ = pa.int64() if name in ("label", "voxel_count") else pa.string()
        cols[name] = pa.array([r.get(name) for r in rows], type=typ)
    _write_parquet_atomic(run_dir / DIAGNOSTICS, pa.table(cols))
    keys = features.select(["image_type", "feature_class", "feature"]).to_pylist()
    return len({(k["image_type"], k["feature_class"], k["feature"]) for k in keys})


def wide(table: pa.Table) -> pa.Table:
    """One row per (item, label); feature columns `{image_type}_{feature_class}_{feature}`."""
    ids = [c for c in ID_COLS if c in table.column_names]
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    fcols: dict[str, None] = {}
    for r in table.to_pylist():
        key = (r["item_id"], r["label"])
        row = rows.get(key)
        if row is None:
            row = rows[key] = {c: r[c] for c in ids}
        name = f"{r['image_type']}_{r['feature_class']}_{r['feature']}"
        fcols.setdefault(name)
        row[name] = r["value"]
    cols: dict[str, pa.Array] = {}
    for c in ids:
        typ = pa.int64() if c == "label" else pa.string()
        cols[c] = pa.array([r[c] for r in rows.values()], type=typ)
    for name in fcols:
        cols[name] = pa.array([r.get(name) for r in rows.values()], type=pa.float64())
    if not rows:
        return pa.table({c: pa.array([], type=table.schema.field(c).type) for c in ids})
    return pa.table(cols)


def join_phase(table: pa.Table, effective: dict[str, str]) -> pa.Table:
    """PHS-03 at read time (AUD-A5-04): `phase` = effective phase, `phase_at_run` = the run's."""
    run_phase = table["phase"]
    items = table["item_id"].to_pylist()
    phase = [effective.get(i, p) for i, p in zip(items, run_phase.to_pylist(), strict=True)]
    j = table.column_names.index("phase")
    t = table.set_column(j, "phase", pa.array(phase, type=pa.string()))
    return t.add_column(j + 1, "phase_at_run", run_phase)


def _cell(v: Any) -> Cell:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v is None or isinstance(v, str | int | float):
        return v
    return str(v)


def to_csv(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pacsv.write_csv(table, buf)
    return buf.getvalue()


def to_parquet(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


class RadiomicsService:
    def __init__(
        self,
        workspace: Workspace,
        store: IndexStore,
        jobs: JobManager,
        bus: EventBus,
        locks: ProjectLocks,
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.jobs = jobs
        self.bus = bus
        self.locks = locks
        self.runs = RunStore(
            RunRecord,
            self._runs_dir,
            jobs,
            locks,
            terminal=TERMINAL_RUN,
            resumable=RESUMABLE_RUN,
            noun="Run",
        )

    # -- engine / settings (API-30/31, RAD-01/04) -----------------------------------------

    @staticmethod
    def engine() -> RadiomicsEngine:
        return get_engine()

    def validate(self, req: ValidateRequest) -> ValidateResult:
        """API-43: schema checks + rules; selection counts are checked when given."""
        eng = self.engine()
        issues = eng.validate(req.settings.model_dump())
        if req.labels is not None and not req.labels:
            issues.append(_nothing(["labels"]))
        if req.n_items is not None and req.n_items == 0:
            issues.append(_nothing(["n_items"]))
        norm, _ = st.normalize(eng.schema(), req.settings)
        ok = not any(i.severity == "error" for i in issues)
        return ValidateResult(
            ok=ok,
            issues=issues,
            settings=norm,
            profile_hash=self.hash_of(eng, norm) if ok and norm is not None else None,
        )

    @staticmethod
    def hash_of(eng: RadiomicsEngine, norm: RadiomicsSettings) -> str:
        return st.profile_hash(norm, eng.name, st.engine_major(eng.version))

    def normalized(
        self, eng: RadiomicsEngine, raw: RadiomicsSettings | None, loc: str = "settings"
    ) -> RadiomicsSettings:
        """Authoritative validation (RAD-04): 422 with field issues, else normalized settings."""
        raw = raw or RadiomicsSettings()
        issues = eng.validate(raw.model_dump())
        errors = issue_errors(issues, ["body", loc])
        if errors:
            raise ValidationProblem("Invalid radiomics settings", errors=errors)
        norm, _ = st.normalize(eng.schema(), raw)
        assert norm is not None
        return norm

    def _settings_for(
        self, pid: str, eng: RadiomicsEngine, raw: RadiomicsSettings | None, phash: str | None
    ) -> tuple[RadiomicsSettings, str, Profile | None]:
        if raw is not None and phash is not None:
            raise ValidationProblem(
                "Give either settings or profile_hash, not both",
                errors=[{"loc": ["body", "profile_hash"], "msg": "conflicts with settings"}],
            )
        if phash is not None:
            prof = self.get_profile(pid, phash)
            norm = self.normalized(eng, prof.settings)
            h = self.hash_of(eng, norm)
            if h != prof.profile_hash:
                raise FormatVersionUnsupported(
                    f"Profile was saved with {prof.engine.name} {prof.engine.version}; "
                    f"re-save it with {eng.name} {eng.version}"
                )
            return norm, h, prof
        norm = self.normalized(eng, raw)
        return norm, self.hash_of(eng, norm), None

    # -- profiles (API-32, RAD-03) --------------------------------------------------------

    def _profiles_dir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid) / RADIOMICS / PROFILES

    def _profile_path(self, pid: str, phash: str) -> Path:
        m = HASH_RE.match(phash)
        if m is None:
            raise NotFound(f"Profile {phash!r} not found")
        return self._profiles_dir(pid) / f"{m.group(1)}.json"  # no ':' in file names

    def list_profiles(self, pid: str) -> list[Profile]:
        d = self._profiles_dir(pid)
        out = [Profile.model_validate(read_json(p)) for p in d.glob("*.json")] if d.is_dir() else []
        return sorted(out, key=lambda p: (p.name.lower(), p.created_at, p.profile_hash))

    def get_profile(self, pid: str, phash: str) -> Profile:
        path = self._profile_path(pid, phash)
        if not path.is_file():
            raise NotFound(f"Profile {phash!r} not found")
        return Profile.model_validate(read_json(path))

    async def create_profile(self, pid: str, body: ProfileCreate) -> tuple[Profile, bool]:
        """Content-addressed: identical settings return the existing profile (created=False)."""
        eng = self.engine()
        norm = self.normalized(eng, body.settings)
        h = self.hash_of(eng, norm)
        path = self._profile_path(pid, h)
        async with self.locks(pid):
            if path.is_file():
                return Profile.model_validate(read_json(path)), False
            now = utc_now()
            prof = Profile(
                profile_hash=h,
                name=body.name.strip() or "Untitled profile",
                created_at=now,
                updated_at=now,
                engine=ProfileEngine(
                    name=eng.name, version=eng.version, major=st.engine_major(eng.version)
                ),
                settings=norm,
            )
            atomic_write_json(path, prof.model_dump(mode="json"))
        return prof, True

    async def rename_profile(self, pid: str, phash: str, name: str) -> Profile:
        async with self.locks(pid):
            prof = self.get_profile(pid, phash)
            prof = prof.model_copy(update={"name": name.strip(), "updated_at": utc_now()})
            atomic_write_json(self._profile_path(pid, phash), prof.model_dump(mode="json"))
        return prof

    async def delete_profile(self, pid: str, phash: str) -> None:
        async with self.locks(pid):
            path = self._profile_path(pid, phash)
            if not path.is_file():
                raise NotFound(f"Profile {phash!r} not found")
            path.unlink()

    # -- selection (RAD-05) ---------------------------------------------------------------

    def seg_of(self, pid: str, sel: Selection) -> SegmentationSet:
        """RAD-05: the selection's segmentation set (default `default_seg`)."""
        cfg = self.workspace.get(pid)
        seg = cfg.segmentation(sel.seg_id or cfg.default_seg)
        if seg is None:
            raise ValidationProblem(
                f"Unknown segmentation set {sel.seg_id!r}",
                errors=[{"loc": ["body", "selection", "seg_id"], "msg": "unknown seg_id"}],
            )
        return seg

    async def select(self, pid: str, sel: Selection) -> list[Item]:
        issues: list[Issue] = []
        if not sel.labels:
            issues.append(_nothing(["selection", "labels"]))
        for i, lab in enumerate(sel.labels):
            if lab <= 0:
                issues.append(
                    Issue(loc=["selection", "labels", i], msg="Must be positive", rule="type")
                )
        if sel.item_ids is not None and sel.filter is not None:
            issues.append(
                Issue(
                    loc=["selection", "filter"],
                    msg="Use either item_ids or filter",
                    rule="conflict",
                )
            )
        idx = self.store.load(pid)
        ids = readiness.var_ids(self.workspace, self.store, self.locks, self.bus, pid)
        items, problems = await readiness.resolve(idx.items, idx.by_id, sel, ids)
        issues += [Issue(loc=["selection", *p.loc], msg=p.msg, rule=p.rule) for p in problems]
        if not items and not issues:
            issues.append(_nothing(["selection"]))
        if issues:
            errs = issue_errors(issues, ["body"])
            raise ValidationProblem("Invalid selection", errors=errs)
        return items

    @staticmethod
    def filter_text(sel: Selection) -> str | None:
        f = sel.filter
        if f is None:
            return None
        parts = []
        if f.phase:
            parts.append("phase=" + ",".join(f.phase))
        if f.side:
            parts.append("side=" + ",".join(f.side))
        for name, values in sorted((f.var or {}).items()):
            parts.append(f"var.{name}=" + ",".join(values))
        return "&".join(parts) or None

    @staticmethod
    def plan(
        items: Sequence[Item], labels: Sequence[int], seg: SegmentationSet | None = None
    ) -> tuple[list[dict[str, Any]], list[RunError]]:
        """(item, label) units; items and labels that are not ready are skipped (TSK-04).

        `seg` (RAD-05): masks come from that set; project labels map to its values through the
        set's `label_mapping` (ADR-0015). `labels_present` and the IMP-08 codes describe the
        `imported` set only. An item without image or mask, or with a blocking code
        (`readiness.BLOCKING`), is skipped with that code, never failed (AUD-A2-05).
        """
        units: list[dict[str, Any]] = []
        skips: list[RunError] = []
        seg_id = seg.seg_id if seg is not None else "imported"
        inverse = {v: int(k) for k, v in (seg.label_mapping if seg else {}).items() if k.isdigit()}
        for it in items:
            not_ready = _not_ready(it, seg_id)
            for lab in sorted(set(labels)):
                if not_ready is not None:
                    skips.append(_row(it.item_id, lab, "skipped", not_ready))
                    continue
                mask_label = inverse.get(lab, lab)
                if seg_id != "imported" and seg is not None and inverse and lab not in inverse:
                    skips.append(_row(it.item_id, lab, "skipped", "label_not_in_set"))
                    continue
                present = it.labels_present if seg_id == "imported" else []
                if present and lab not in present:
                    skips.append(_row(it.item_id, lab, "skipped", "label_absent"))
                    continue
                units.append(
                    {
                        "key": worker.unit_key(it.item_id, lab),
                        "item": {
                            "item_id": it.item_id,
                            "case_id": it.case_id,
                            "scan_idx": it.scan_idx,
                            "scope": it.scope,
                            "side": it.side,
                            "phase": it.phase.canonical,
                        },
                        "label": lab,
                        "mask_label": mask_label,
                        "seg_id": seg_id,
                        "image": it.image.model_dump(mode="json") if it.image else None,
                        "mask": (
                            it.masks[seg_id].model_dump(mode="json") if seg_id in it.masks else None
                        ),
                        "spacing": it.geometry.spacing if it.geometry else [1.0, 1.0, 1.0],
                        "axis_order": npy_convert.axis_order_of(it.extra.get("axis_order"))
                        or "xyz",
                    }
                )
        return units, skips

    async def _path(
        self, pid: str, vol: dict[str, Any] | None, spacing: list[float], order: str = "xyz"
    ) -> str:
        """Absolute read path for a volume ref (BE-02); legacy `.npy` → cached NIfTI (IMP-10)."""
        if vol is None:
            raise SourceMissingError("volume missing")
        path = self.workspace.resolver(pid).resolve(vol["ref"])
        if not path.is_file():
            raise SourceMissingError("source file missing")
        if vol.get("format") == "npy":
            fp = await asyncio.to_thread(quick_fingerprint, path)
            axis = npy_convert.axis_order_of(order) or "xyz"
            dst = npy_convert.cache_path(self.workspace.project_dir(pid), fp, axis)
            path = await npy_convert.ensure_nifti(self.jobs, path, dst, spacing, axis)
        return str(path)

    async def tasks(
        self,
        pid: str,
        run_dir: Path | None,
        run_id: str,
        units: Sequence[dict[str, Any]],
        settings: RadiomicsSettings,
        engine_name: str,
        check_fp: bool = False,
    ) -> tuple[list[dict[str, Any]], list[RunError]]:
        """Resolve units into worker tasks; unresolvable inputs become per-item errors.

        `check_fp` (resume, RAD-08 / NFR-15; AUD-A5-14): a unit whose image or mask quick
        fingerprint differs from the one recorded at run creation fails with `input_changed`,
        so a resumed run never mixes features of changed inputs with the original parts.
        """
        out: list[dict[str, Any]] = []
        errors: list[RunError] = []
        snap = settings.model_dump(mode="json")
        for u in units:
            iid, lab = u["item"]["item_id"], u["label"]
            try:
                if u["image"] is None:
                    raise SourceMissingError("item has no image")
                if u["mask"] is None:
                    raise SourceMissingError("item has no mask")
                if check_fp and await self._changed(pid, u):
                    errors.append(_row(iid, lab, "failed", "input_changed"))
                    continue
                order = u.get("axis_order", "xyz")
                image = await self._path(pid, u["image"], u["spacing"], order)
                mask = await self._path(pid, u["mask"], u["spacing"], order)
            except (Problem, SourceMissingError, OSError) as exc:
                detail = exc.detail if isinstance(exc, Problem) else str(exc)
                errors.append(
                    _row(iid, lab, "failed", "input_missing", detail or type(exc).__name__)
                )
                continue
            out.append(
                {
                    "key": u["key"],
                    "run_id": run_id,
                    "run_dir": str(run_dir) if run_dir else "",
                    "engine": engine_name,
                    "item": u["item"],
                    "label": u["label"],
                    "mask_label": u.get("mask_label", u["label"]),
                    "image_path": image,
                    "mask_path": mask,
                    "settings": snap,
                }
            )
        return out, errors

    async def _changed(self, pid: str, unit: dict[str, Any]) -> bool:
        """True when the unit's image or mask no longer has its recorded quick fingerprint."""
        resolver = self.workspace.resolver(pid)
        for vol in (unit["image"], unit["mask"]):
            want = vol.get("fp")
            path = resolver.resolve(vol["ref"])
            if want is None or not path.is_file():
                continue  # missing files fail in `_path` as `input_missing`
            if await asyncio.to_thread(quick_fingerprint, path) != want:
                return True
        return False

    # -- estimate (API-44, RAD-11) --------------------------------------------------------

    async def estimate(self, pid: str, req: EstimateRequest) -> EstimateResult:
        eng = self.engine()
        norm, _, _ = self._settings_for(pid, eng, req.settings, req.profile_hash)
        items = await self.select(pid, req.selection)
        units, skips = self.plan(items, req.selection.labels, self.seg_of(pid, req.selection))
        sample_ids: list[str] = []
        for u in units:
            iid = u["item"]["item_id"]
            if iid not in sample_ids:
                sample_ids.append(iid)
            if len(sample_ids) == SAMPLE_ITEMS:
                break
        sample = [u for u in units if u["item"]["item_id"] in sample_ids]
        tasks, pre = await self.tasks(pid, None, "estimate", sample, norm, eng.name)
        results: list[dict[str, Any]] = (
            await self.jobs.run_in_worker(worker.estimate_sample, tasks) if tasks else []
        )
        total = sum(float(r["elapsed_s"]) for r in results)
        timed_items = {r["item_id"] for r in results}
        per_item = total / len(timed_items) if timed_items else None
        per_unit = total / len(results) if results else None
        workers = self.jobs.workers
        errors = [f"{e.item_id} label {e.label}: {e.error}" for e in pre]
        errors += [
            f"{r['item_id']} label {r['label']}: {causes.text(causes.explain(r['error']))}"
            for r in results
            if r["error"]
        ]
        return EstimateResult(
            n_items=len(items),
            n_labels=len(set(req.selection.labels)),
            n_units=len(units),
            n_skipped=len(skips),
            skipped_by=dict(Counter(e.code or "engine" for e in skips)),
            sample_item_ids=sample_ids,
            time_per_item_s=round(per_item, 4) if per_item is not None else None,
            time_per_unit_s=round(per_unit, 4) if per_unit is not None else None,
            workers=workers,
            estimated_total_s=(
                round(per_unit * len(units) / workers, 2) if per_unit is not None else None
            ),
            sample_errors=errors,
        )

    # -- runs (API-45/46, RAD-06..09) -----------------------------------------------------

    def _runs_dir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid) / RADIOMICS / RUNS

    async def start(self, pid: str, req: RunRequest, reviewer: str | None) -> RunDetail:
        """API-45: validate, select, snapshot, then one `radiomics` job (RAD-06)."""
        who = reviewer_stamp.require(reviewer)
        eng = self.engine()
        norm, phash, prof = self._settings_for(pid, eng, req.settings, req.profile_hash)
        items = await self.select(pid, req.selection)
        seg = self.seg_of(pid, req.selection)
        units, skips = self.plan(items, req.selection.labels, seg)
        if not units:
            raise ValidationProblem(
                "No selected item is ready: every item or label was skipped",
                errors=[{"loc": ["body", "selection", "labels"], "msg": MSG_NOTHING}],
            )
        cur = self.jobs.active(pid, "radiomics")
        if cur is not None:
            raise JobConflict(f"A radiomics run is already active: {cur.job_id}")
        run_id = new_ulid()
        run_dir = self._runs_dir(pid) / run_id
        tasks, pre = await self.tasks(pid, run_dir, run_id, units, norm, eng.name)
        now = utc_now()
        rec = RunRecord(
            run_id=run_id,
            name=(req.name or "").strip() or (prof.name if prof else f"Run {now}"),
            status="queued",
            created_at=now,
            reviewer=who,
            engine=RunEngine(name=eng.name, version=eng.version, deps=eng.dependency_versions()),
            ibsi_map_version=ibsi.map_version(),
            profile_hash=phash,
            settings=norm,
            selection=RunSelection(
                scope=req.selection.scope,
                labels=sorted(set(req.selection.labels)),
                filter=self.filter_text(req.selection),
                item_ids=[i.item_id for i in items],
                seg_id=seg.seg_id,
            ),
            inputs=[
                RunInput(
                    item_id=i.item_id,
                    image_fp=i.image.fp if i.image else None,
                    seg_id=seg.seg_id,
                    mask_fp=i.masks[seg.seg_id].fp if seg.seg_id in i.masks else None,
                )
                for i in items
            ],
            counts=RunCounts(items=len(items), skipped=len(skips)),
        )
        async with self.locks(pid):
            (run_dir / worker.PARTS).mkdir(parents=True, exist_ok=True)
            write_jsonl_atomic(run_dir / UNITS, units)
            write_jsonl_atomic(run_dir / ERRORS, [e.model_dump() for e in [*skips, *pre]])
            self.runs.write(run_dir, rec)
        await self._submit(pid, run_dir, tasks)
        return await self.get(pid, run_id)

    async def _submit(self, pid: str, run_dir: Path, tasks: list[dict[str, Any]]) -> None:
        run_id = run_dir.name

        async def on_result(res: dict[str, Any]) -> None:
            if res.get("ok"):
                return
            raw = str(res.get("error") or "extraction failed")
            row = _row(res["item_id"], int(res["label"]), "failed", causes.explain(raw), raw)
            async with self.locks(pid):
                append_jsonl(run_dir / ERRORS, [row.model_dump()])

        async def on_finish(info: JobInfo) -> str | None:
            async with self.locks(pid):
                rec = self.runs.read(run_dir)
                try:
                    await self._finish(run_dir, rec, info)
                except Exception as exc:
                    log.exception("radiomics finish failed", extra={"run_id": run_id})
                    rec.status, rec.error = "failed", f"{type(exc).__name__}: {exc}"
                rec.started_at = rec.started_at or info.started_at
                rec.finished_at = utc_now()
                self.runs.write(run_dir, rec)
            return run_id

        job_id = new_ulid()
        spec = JobSpec(
            project_id=pid,
            kind="radiomics",
            units=[WorkUnit(worker.extract_unit, (t,)) for t in tasks],
            on_result=on_result,
            on_finish=on_finish,
            ref=run_id,
            job_id=job_id,
            meta={"run_id": run_id},
        )
        await self.runs.submit(pid, run_dir, spec)
        await self.runs.set_status(pid, run_dir, "running")

    async def _finish(self, run_dir: Path, rec: RunRecord, info: JobInfo) -> None:
        errors = [RunError.model_validate(r) for r in read_jsonl(run_dir / ERRORS)]
        failed_keys = {(e.item_id, e.label) for e in errors if e.kind == "failed"}
        status: RunStatus
        if info.status == "succeeded":
            n_features = await asyncio.to_thread(_compact, run_dir)
            status = "completed_with_errors" if failed_keys else "completed"
        else:
            n_features = 0
            status = "failed"
            if info.status == "cancelled":
                status = "cancelled"
            elif info.status == "interrupted":
                status = "interrupted"
            rec.error = info.error
        parts = (run_dir / worker.PARTS).glob("*.parquet")
        done = {_parse_key(p.name[: -len(".parquet")]) for p in parts}
        failed_items = {i for i, _ in failed_keys}
        ok_items = {i for i, _ in done} - failed_items
        rec.counts = RunCounts(
            items=len(rec.selection.item_ids),
            ok=len(ok_items),
            failed=len(failed_items),
            features=n_features,
            skipped=sum(1 for e in errors if e.kind == "skipped"),
        )
        rec.status = status

    async def get(self, pid: str, rid: str) -> RunDetail:
        run_dir = self.runs.run_dir(pid, rid)
        rec = await self.runs.reconcile(pid, run_dir)
        job = self.runs.job(rec.job_id)
        progress = None
        if job is not None:
            progress = RunProgress(done=job.done, total=job.total, eta_s=job.eta_s)
        return RunDetail(**rec.model_dump(), progress=progress)

    async def list_runs(self, pid: str) -> list[RunSummary]:
        out = []
        for run_dir in self.runs.run_dirs(pid):
            rec = await self.runs.reconcile(pid, run_dir)
            out.append(RunSummary.model_validate(rec.model_dump()))
        return out

    async def cancel(self, pid: str, rid: str) -> RunDetail:
        """API-46 (RAD-06): cancel the run's job; idempotent for finished runs."""
        await self.runs.cancel(pid, self.runs.run_dir(pid, rid), CANCEL_WAIT_S)
        return await self.get(pid, rid)

    async def resume(self, pid: str, rid: str) -> RunDetail:
        """API-46 / RAD-08: re-run units without a part file; failures are retried."""
        run_dir = self.runs.run_dir(pid, rid)
        rec = await self.runs.resumable(pid, run_dir)
        eng = self.engine()
        if eng.name != rec.engine.name or eng.version != rec.engine.version:
            raise FormatVersionUnsupported(
                f"Run used {rec.engine.name} {rec.engine.version}; installed is "
                f"{eng.name} {eng.version}. Start a new run."
            )
        cur = self.jobs.active(pid, "radiomics")
        if cur is not None:
            raise JobConflict(f"A radiomics run is already active: {cur.job_id}")
        units = read_jsonl(run_dir / UNITS)
        remaining = [u for u in units if not worker.part_path(run_dir, u["key"]).is_file()]
        tasks, pre = await self.tasks(
            pid, run_dir, rid, remaining, rec.settings, eng.name, check_fp=True
        )
        async with self.locks(pid):
            kept = [r for r in read_jsonl(run_dir / ERRORS) if r.get("kind") == "skipped"]
            write_jsonl_atomic(run_dir / ERRORS, [*kept, *(e.model_dump() for e in pre)])
            (run_dir / FEATURES).unlink(missing_ok=True)
            (run_dir / DIAGNOSTICS).unlink(missing_ok=True)
            rec = self.runs.read(run_dir)
            rec.status, rec.finished_at, rec.error = "queued", None, None
            self.runs.write(run_dir, rec)
        await self._submit(pid, run_dir, tasks)
        return await self.get(pid, rid)

    # -- outputs (API-36, API-47, RAD-07/10) ---------------------------------------------------

    def features(self, pid: str, rid: str, item_id: str | None, shape: str) -> pa.Table:
        run_dir = self.runs.run_dir(pid, rid)
        t = _load_features(run_dir)
        if item_id is not None:
            t = t.filter(pc.equal(t["item_id"], item_id))
        t = join_phase(t, self.store.effective_phases(pid))
        return wide(t) if shape == "wide" else t

    @staticmethod
    def features_json(rid: str, table: pa.Table, shape: str) -> FeaturesTable:
        rows = [{k: _cell(v) for k, v in r.items()} for r in table.to_pylist()]
        return FeaturesTable(
            run_id=rid,
            shape="wide" if shape == "wide" else "long",
            columns=list(table.column_names),
            rows=rows,
            total=len(rows),
        )

    def errors(self, pid: str, rid: str) -> list[RunError]:
        run_dir = self.runs.run_dir(pid, rid)
        return [RunError.model_validate(r) for r in read_jsonl(run_dir / ERRORS)]


class SourceMissingError(Exception):
    """An input volume cannot be read; recorded as a per-item error (RAD-07)."""
