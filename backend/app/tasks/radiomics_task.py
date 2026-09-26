"""`radiomics.pyradiomics` behind the generic task endpoints (RAD-13, ADR-0016 §3).

The radiomics service stays the implementation (RAD-*); run records stay in `radiomics/runs/`.
This adapter maps task payloads to radiomics ones and back.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.errors import ValidationProblem
from app.core.ids import is_ulid
from app.radiomics.models import (
    EstimateRequest,
    RadiomicsSettings,
    RunDetail,
    RunRequest,
    RunSummary,
    Selection,
    SelectionFilter,
    ValidateRequest,
)
from app.radiomics.service import RadiomicsService
from app.tasks.models import (
    PreflightRequest,
    SettingsIssue,
    TaskEstimate,
    TaskItemError,
    TaskRef,
    TaskRunCounts,
    TaskRunDetail,
    TaskRunInput,
    TaskRunOutput,
    TaskRunProgress,
    TaskRunRequest,
    TaskRunStarted,
    TaskRunSummary,
    TaskSelection,
    TaskValidateResult,
)
from app.tasks.registry import RADIOMICS_TASK

VERSION = "1.0.0"  # app/radiomics/task.json


def _settings(raw: dict[str, Any]) -> tuple[RadiomicsSettings | None, str | None]:
    """Task settings = RadiomicsSettings, or `{profile_hash}` (RAD-03)."""
    phash = raw.get("profile_hash")
    body = {k: v for k, v in raw.items() if k != "profile_hash"}
    try:
        settings = RadiomicsSettings.model_validate(body) if body or phash is None else None
    except ValidationError as exc:
        raise ValidationProblem(
            "Invalid radiomics settings",
            errors=[
                {"loc": ["body", "settings", *e["loc"]], "msg": e["msg"]} for e in exc.errors()
            ],
        ) from None
    return settings, phash if isinstance(phash, str) else None


def _selection(sel: TaskSelection) -> Selection:
    f = sel.filter
    return Selection(
        item_ids=sel.item_ids,
        filter=SelectionFilter(phase=f.phase, side=f.side, var=f.var) if f else None,
        scope=sel.scope,
        labels=sel.labels,
        seg_id=sel.seg_id,
    )


def _ref() -> TaskRef:
    return TaskRef(id=RADIOMICS_TASK, version=VERSION, manifest_hash="")


def _summary(r: RunSummary | RunDetail) -> TaskRunSummary:
    return TaskRunSummary(
        run_id=r.run_id,
        task=_ref(),
        name=r.name,
        status=r.status,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        reviewer=r.reviewer,
        job_id=r.job_id,
        counts=TaskRunCounts(
            items=r.counts.items, ok=r.counts.ok, failed=r.counts.failed, skipped=r.counts.skipped
        ),
    )


class RadiomicsTask(RadiomicsService):
    def validate_task(self, raw: dict[str, Any]) -> TaskValidateResult:
        settings, _ = _settings(raw)
        req = ValidateRequest(settings=settings or RadiomicsSettings(), labels=None, n_items=None)
        res = self.validate(req)
        return TaskValidateResult(
            ok=res.ok,
            issues=[
                SettingsIssue(loc=i.loc, msg=i.msg, rule=i.rule, severity=i.severity)
                for i in res.issues
            ],
            settings=res.settings.model_dump(mode="json") if res.settings else None,
            settings_hash=res.profile_hash,
        )

    async def estimate_task(self, pid: str, req: PreflightRequest) -> TaskEstimate:
        settings, phash = _settings(req.settings)
        res = await self.estimate(
            pid,
            EstimateRequest(
                settings=settings, profile_hash=phash, selection=_selection(req.selection)
            ),
        )
        return TaskEstimate(
            n_units=res.n_units,
            n_skipped=res.n_skipped,
            seconds_per_item=res.time_per_item_s,
            estimated_total_s=res.estimated_total_s,
            basis="sample" if res.time_per_item_s is not None else "unknown",
            sample_item_ids=res.sample_item_ids,
            sample_errors=res.sample_errors,
            detail={"skipped_by": res.skipped_by} if res.skipped_by else {},
        )

    async def start_task(
        self, pid: str, req: TaskRunRequest, reviewer: str | None
    ) -> TaskRunStarted:
        settings, phash = _settings(req.settings)
        body = RunRequest(
            name=req.name,
            settings=settings,
            profile_hash=phash,
            selection=_selection(req.selection),
        )
        d = await self.start(pid, body, reviewer)
        return TaskRunStarted(run_id=d.run_id, job_id=d.job_id, status=d.status)

    def has_run(self, pid: str, rid: str) -> bool:
        if not is_ulid(rid):
            return False
        return (self._runs_dir(pid) / rid / "run.json").is_file()

    async def task_summaries(self, pid: str) -> list[TaskRunSummary]:
        return [_summary(r) for r in await self.list_runs(pid)]

    async def task_detail(self, pid: str, rid: str) -> TaskRunDetail:
        d = await self.get(pid, rid)
        return TaskRunDetail(
            **_summary(d).model_dump(),
            runtime="builtin",
            settings=d.settings.model_dump(mode="json"),
            settings_hash=d.profile_hash,
            selection=TaskSelection(
                item_ids=d.selection.item_ids,
                scope=d.selection.scope,
                labels=d.selection.labels,
                seg_id=d.selection.seg_id,
            ),
            item_ids=d.selection.item_ids,
            inputs=[
                TaskRunInput(
                    item_id=i.item_id, image_fp=i.image_fp, seg_id=i.seg_id, mask_fp=i.mask_fp
                )
                for i in d.inputs
            ],
            versions={"engine": f"{d.engine.name} {d.engine.version}", **d.engine.deps},
            outputs=self.task_outputs(pid, rid),
            progress=(
                TaskRunProgress(
                    done=d.progress.done, total=d.progress.total, eta_s=d.progress.eta_s
                )
                if d.progress
                else None
            ),
            detail_url=f"/api/v1/projects/{pid}/radiomics/runs/{rid}",
        )

    def task_errors(self, pid: str, rid: str) -> list[TaskItemError]:
        return [
            TaskItemError(
                item_id=e.item_id,
                status="skipped" if e.kind == "skipped" else "failed",
                message=f"label {e.label}: {e.error}" + (f" ({e.code})" if e.code else ""),
            )
            for e in self.errors(pid, rid)
        ]

    def task_outputs(self, pid: str, rid: str) -> list[TaskRunOutput]:
        return [
            TaskRunOutput(
                kind="features",
                ref=f"radiomics/runs/{rid}/features.parquet",
                detail=f"/api/v1/projects/{pid}/radiomics/runs/{rid}/features",
            )
        ]
