"""API-60 view-only links (PRJ-17, ADR-0019 §5): `/view/{token}` mirrors a read-only subset of
the project GET endpoints and never exposes `project_id`.

The token is resolved to the project and the request is forwarded, unchanged except for its path,
to the matching `/projects/{pid}/…` route. Only paths in `READ_ONLY` are served; there is no
write route on this prefix, so any other method is 405 and any other path 404.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.api.v1.deps import Ctx
from app.core.errors import NotFound
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
    r"|radiomics/runs(?:/[^/]+(?:/(?:features|errors))?)?"
    r"|task-runs(?:/[^/]+)?"
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


class _Forward(Response):
    """Re-dispatches the request to the app under another path (streams pass through)."""

    def __init__(self, scope: Scope) -> None:
        super().__init__()
        self._scope = scope

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._scope["app"](self._scope, receive, send)


@router.get("/view/{token}", response_model=ProjectDetail)
def view_project(ctx: Ctx, token: str) -> ProjectDetail:
    """The project as a view-only link sees it: no `project_id`, no server paths."""
    pid = ctx.workspace.by_view_token(token)
    d = ctx.workspace.detail(pid)
    roots = [r.model_copy(update={"path": ""}) for r in d.path_roots]
    return d.model_copy(
        update={
            "project_id": view_pid(token),
            "share_url": ctx.workspace.view_url(token),
            "view_url": ctx.workspace.view_url(token),
            "path_roots": roots,
            "read_only": True,
        }
    )


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
    return _Forward(scope)
