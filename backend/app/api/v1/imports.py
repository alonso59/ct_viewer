"""API-11..15 import preview/commit/history, warnings, full-hash job (IMP-*)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.core.errors import ValidationProblem
from app.ingest.codes import QcCode, Severity
from app.ingest.hashing import HashJobRequest, HashJobStarted, start_hash_job
from app.ingest.models import QcWarning
from app.ingest.parsers import FileKind
from app.ingest.schemas import (
    DEFAULT_ALIAS,
    CommitRequest,
    CommitResult,
    ImportHistory,
    ImportPreview,
    PreviewRequest,
)
from app.ingest.service import IngestService

router = APIRouter(tags=["imports"])

UPLOAD_FIELDS: tuple[FileKind, ...] = ("metadata", "phase", "voi_catalog")
_FILE = {"type": "string", "format": "binary"}
PREVIEW_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": PreviewRequest.model_json_schema()},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["root", "metadata"],
                    "properties": {
                        "root": {"type": "string"},
                        "alias": {"type": "string", "default": DEFAULT_ALIAS},
                        **dict.fromkeys(UPLOAD_FIELDS, _FILE),
                    },
                }
            },
        },
    }
}


def ingest_service(ctx: Ctx) -> IngestService:
    return IngestService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks, ctx.after_index)


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]


@router.post(
    "/projects/{pid}/imports/preview", response_model=ImportPreview, openapi_extra=PREVIEW_BODY
)
async def preview_import(pid: str, request: Request, ctx: Ctx) -> ImportPreview:
    """IMP-02/03: JSON `{root, detect: true, alias?}` or multipart uploads of the inputs."""
    svc = ingest_service(ctx)
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        root, alias = form.get("root"), form.get("alias") or DEFAULT_ALIAS
        if not isinstance(root, str) or not isinstance(alias, str):
            raise ValidationProblem(
                "root is required", errors=[{"loc": ["body", "root"], "msg": "required"}]
            )
        uploads: dict[FileKind, tuple[str, bytes]] = {}
        for kind in UPLOAD_FIELDS:
            f = form.get(kind)
            if isinstance(f, UploadFile):
                uploads[kind] = (f.filename or "", await f.read())
        if "metadata" not in uploads:
            raise ValidationProblem(
                "metadata file is required",
                errors=[{"loc": ["body", "metadata"], "msg": "required"}],
            )
        return await svc.preview(pid, root, alias=alias, uploads=uploads)
    try:
        body = PreviewRequest.model_validate_json(await request.body())
    except ValidationError as exc:
        raise ValidationProblem("Invalid preview request", errors=_errors(exc)) from None
    if not body.detect:
        raise ValidationProblem(
            "JSON previews require detect=true; upload files as multipart instead",
            errors=[{"loc": ["body", "detect"], "msg": "must be true"}],
        )
    return await svc.preview(
        pid, body.root, alias=body.alias, adapter=body.adapter, options=body.options, add=body.add
    )


@router.post("/projects/{pid}/imports", response_model=CommitResult, status_code=202)
async def commit_import(pid: str, body: CommitRequest, ctx: Ctx) -> CommitResult:
    """IMP-04/05: snapshot + start the index job."""
    return await ingest_service(ctx).commit(pid, body.preview_id)


@router.get("/projects/{pid}/imports", response_model=ImportHistory)
async def list_imports(pid: str, ctx: Ctx, paging: Paging) -> ImportHistory:
    """API-13: import history (newest first) plus the current index status."""
    svc = ingest_service(ctx)
    page = paginate(svc.imports(pid), paging)
    return ImportHistory(
        items=page.items,
        next_cursor=page.next_cursor,
        total=page.total,
        index=await svc.index_status(pid),
    )


@router.get("/projects/{pid}/warnings", response_model=Page[QcWarning])
def list_warnings(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    code: Annotated[QcCode | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    case_id: Annotated[str | None, Query()] = None,
    item_id: Annotated[str | None, Query()] = None,
) -> Page[QcWarning]:
    """API-14 (IMP-08)."""
    rows = ingest_service(ctx).warnings(
        pid, code=code, severity=severity, case_id=case_id, item_id=item_id
    )
    return paginate(rows, paging)


@router.post("/projects/{pid}/hash-jobs", response_model=HashJobStarted, status_code=202)
async def start_hash(pid: str, ctx: Ctx, body: HashJobRequest | None = None) -> HashJobStarted:
    """API-15 (IMP-09): full SHA-256 of every indexed image/mask file, in job workers.

    Results land in `index/hashes.json` and show up as `image.sha256` / `mask.sha256` on item
    records (API-21/22). One `hash` job per project (`job-conflict`).
    """
    ctx.workspace.project_dir(pid)  # 404 for unknown or archived projects
    return await start_hash_job(
        project_id=pid,
        index_dir=ctx.index.index_dir(pid),
        items=ctx.index.load(pid).items,
        resolve=ctx.workspace.resolver(pid).resolve,
        jobs=ctx.jobs,
        locks=ctx.locks,
        on_written=lambda: ctx.index.invalidate(pid),
        force=body.force if body is not None else False,
    )
