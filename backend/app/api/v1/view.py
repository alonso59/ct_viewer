"""API-60 view-only links (PRJ-17, ADR-0019 §5): `/view/{token}` mirrors a read-only subset of
the project GET endpoints and never exposes `project_id` or an absolute server path.

The token is resolved to the project and the request is forwarded, unchanged except for its path,
to the matching `/projects/{pid}/…` route. Only paths in `READ_ONLY` are served; there is no
write route on this prefix, so any other method is 405 and any other path 404. Text responses
(JSON, JSON lines, CSV, SSE) come back through a `Redactor`: the project id becomes
`view-{token}`, root paths become alias refs and other server folders are elided (AUD-A5-03).
Binary responses (volumes, thumbnails, meshes, Parquet) pass through unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.core.errors import NotFound
from app.core.redact import Redactor
from app.jobs.types import JobInfo
from app.projects.models import ProjectDetail

router = APIRouter(tags=["view"])

# Suffixes after `/projects/{pid}` that a view-only link may read (GET, no side effects beyond
# disposable caches such as meshes).
READ_ONLY = re.compile(
    r"^/(?:"
    r"cases(?:/[^/]+)?"
    r"|items/[^/]+(?:/(?:image|mask|thumbnail|dicom-tags|mesh/\d+))?"
    r"|warnings|segmentations|variables|annotations|annotation-sources|events"
    r"|curation/(?:state|events|queue)"
    r"|phase/(?:state|events)"
    r"|radiomics/runs/[^/]+/features"
    r"|task-runs(?:/[^/]+(?:/(?:errors|outputs))?)?"
    r"|exports/dataset-table|layers"
    r")$"
)
# Labeling (LBL-05) lives under the plugin prefix: `/plugins/labeling/projects/{pid}/…`.
PLUGIN_READ_ONLY = re.compile(
    r"^/plugins/labeling/(?:tables(?:/[^/]+(?:/cells|/export|/history)?)?)$"
)


def view_pid(token: str) -> str:
    """The pseudo project id the view-only UI uses; it only carries the token."""
    return f"view-{token}"


def view_redactor(ctx: AppContext, pid: str, token: str) -> Redactor:
    """Root paths → alias refs, other server folders elided, `pid` → `view-{token}`."""
    cfg = ctx.workspace.get(pid)
    s = ctx.settings
    folders = [str(s.workspace_root), *map(str, ctx.guard.allowed_roots)]
    folders += map(str, ctx.workspace.derived_guard.allowed_roots)
    return Redactor(
        aliases=[(r.alias, r.path) for r in cfg.path_roots],
        folders=folders,
        ids=[(pid, view_pid(token))],
    )


def _mode(content_type: str) -> str | None:
    ct = content_type.split(";")[0].strip().lower()
    if ct == "text/event-stream":
        return "sse"
    if ct == "application/x-ndjson":
        return "jsonl"
    if ct == "application/json" or ct.endswith("+json"):
        return "json"
    if ct.startswith("text/"):
        return "text"
    return None  # binary: volumes, thumbnails, meshes, Parquet


class _Forward(Response):
    """Re-dispatches the request to the app under another path; text bodies are redacted
    (a buffered body at once, an SSE stream chunk by chunk), binary bodies pass through."""

    def __init__(self, scope: Scope, redactor: Redactor) -> None:
        super().__init__()
        self._scope = scope
        self._red = redactor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        red = self._red
        mode: str | None = None
        start: Message | None = None
        chunks: list[bytes] = []

        async def redacting(message: Message) -> None:
            nonlocal mode, start
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=list(message["headers"]))
                encoded = headers.get("content-encoding", "identity") != "identity"
                mode = None if encoded else _mode(headers.get("content-type", ""))
                if mode is None:
                    await send(message)
                elif mode == "sse":
                    await send(message)  # streamed: no content-length to fix
                else:
                    start = {**message, "headers": headers.raw}
                return
            if message["type"] != "http.response.body" or mode is None:
                await send(message)
                return
            body: bytes = message.get("body", b"")
            if mode == "sse":
                await send({**message, "body": red.sse_bytes(body) if body else body})
                return
            chunks.append(body)
            if message.get("more_body", False):
                return
            data = b"".join(chunks)
            data = (
                red.json_bytes(data)
                if mode == "json" and data
                else red.jsonl_bytes(data)
                if mode == "jsonl"
                else red.text(data.decode("utf-8", "replace")).encode("utf-8")
            )
            assert start is not None
            headers = MutableHeaders(raw=start["headers"])
            headers["content-length"] = str(len(data))
            await send({**start, "headers": headers.raw})
            await send({"type": "http.response.body", "body": data, "more_body": False})

        await self._scope["app"](self._scope, receive, redacting)


@router.get("/view/{token}", response_model=ProjectDetail)
def view_project(ctx: Ctx, token: str) -> ProjectDetail:
    """The project as a view-only link sees it: no `project_id`, no server paths."""
    pid = ctx.workspace.by_view_token(token)
    d = ctx.workspace.detail(pid)
    roots = [r.model_copy(update={"path": ""}) for r in d.path_roots]
    view = d.model_copy(
        update={
            "project_id": view_pid(token),
            "share_url": ctx.workspace.view_url(token),
            "view_url": ctx.workspace.view_url(token),
            "path_roots": roots,
            "read_only": True,
        }
    )
    red = view_redactor(ctx, pid, token)
    return ProjectDetail.model_validate(red.value(view.model_dump(mode="json")))


@router.get("/view/{token}/jobs", response_model=list[JobInfo])
def view_jobs(ctx: Ctx, token: str) -> list[JobInfo]:
    """The project's jobs (API-41) as the view-only link sees them: no `project_id`, no paths."""
    pid = ctx.workspace.by_view_token(token)
    red = view_redactor(ctx, pid, token)
    return [
        JobInfo.model_validate(red.value(j.model_dump(mode="json"))) for j in ctx.jobs.list(pid)
    ]


@router.get("/view/{token}/{rest:path}", responses={404: {"description": "Not a read route"}})
def view_read(ctx: Ctx, token: str, rest: str, request: Request) -> Response:
    pid = ctx.workspace.by_view_token(token)
    suffix = "/" + rest
    if READ_ONLY.match(suffix):
        path = f"/api/v1/projects/{pid}{suffix}"
    elif (m := PLUGIN_READ_ONLY.match(suffix)) is not None:
        path = f"/api/v1/plugins/labeling/projects/{pid}" + suffix.removeprefix("/plugins/labeling")
        del m
    else:
        raise NotFound(f"{suffix!r} is not available on a view-only link")
    scope: dict[str, Any] = dict(request.scope)
    scope["path"] = path
    scope["raw_path"] = path.encode()
    # uncompressed bodies only, so the redactor can read them
    scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"accept-encoding"]
    return _Forward(scope, view_redactor(ctx, pid, token))
