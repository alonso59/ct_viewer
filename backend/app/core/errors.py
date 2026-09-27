"""RFC 9457 problem+json errors with stable slugs (BE-08, API.md §Errors).

Services raise `Problem` subclasses; `install_handlers` maps them (and FastAPI's own
validation/HTTP errors) to `application/problem+json` responses.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

# slug -> (status, title); the single source for API.md §Errors.
SLUGS: dict[str, tuple[int, str]] = {
    "not-found": (404, "Not found"),
    "validation": (422, "Validation failed"),
    "path-outside-root": (403, "Path outside allowed roots"),
    "source-missing": (409, "Source file missing"),
    "format-version-unsupported": (409, "Unsupported format version"),
    "job-conflict": (409, "Conflicting job"),
    "reviewer-required": (428, "Reviewer required"),
    "server-busy": (503, "Server busy"),
    "unsupported-format": (415, "Unsupported format"),
    "ambiguous-axis-order": (422, "Ambiguous axis order"),
    "geometry-mismatch": (422, "Geometry mismatch"),
    "derived-root-required": (409, "Derived root required"),
    "roots-overlap": (409, "Roots overlap"),
    "precondition-failed": (412, "Precondition failed"),
    "precondition-required": (428, "Precondition required"),
}


class Problem(Exception):
    """`actions`: next steps the UI offers, e.g. `import_as:nifti-files` (SRC-11)."""

    slug = "server-busy"

    def __init__(
        self,
        detail: str = "",
        *,
        errors: list[dict[str, Any]] | None = None,
        actions: list[str] | None = None,
    ) -> None:
        super().__init__(detail or self.slug)
        self.detail = detail
        self.errors = errors
        self.actions = actions

    @property
    def status(self) -> int:
        return SLUGS[self.slug][0]

    @property
    def title(self) -> str:
        return SLUGS[self.slug][1]


class NotFound(Problem):
    slug = "not-found"


class ValidationProblem(Problem):
    slug = "validation"


class _Issue(Protocol):
    @property
    def loc(self) -> Sequence[str | int]: ...
    @property
    def msg(self) -> str: ...
    @property
    def rule(self) -> str: ...
    @property
    def severity(self) -> str: ...


def issue_errors(
    issues: Iterable[_Issue], prefix: Sequence[str | int] = ()
) -> list[dict[str, Any]]:
    """Settings issues of severity `error` → `ValidationProblem.errors` rows (TSK-02, RAD-04)."""
    return [
        {"loc": [*prefix, *i.loc], "msg": i.msg, "type": i.rule}
        for i in issues
        if i.severity == "error"
    ]


class PathOutsideRoot(Problem):
    slug = "path-outside-root"


class SourceMissing(Problem):
    slug = "source-missing"


class FormatVersionUnsupported(Problem):
    slug = "format-version-unsupported"


class JobConflict(Problem):
    slug = "job-conflict"


class ReviewerRequired(Problem):
    slug = "reviewer-required"


class ServerBusy(Problem):
    slug = "server-busy"


class UnsupportedFormat(Problem):
    slug = "unsupported-format"


class AmbiguousAxisOrder(Problem):
    slug = "ambiguous-axis-order"


class GeometryMismatch(Problem):
    slug = "geometry-mismatch"


class DerivedRootRequired(Problem):
    slug = "derived-root-required"


class RootsOverlap(Problem):
    slug = "roots-overlap"


class PreconditionFailed(Problem):
    slug = "precondition-failed"


class PreconditionRequired(Problem):
    slug = "precondition-required"


def problem_body(
    slug: str,
    detail: str,
    instance: str,
    errors: list[dict[str, Any]] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    status, title = SLUGS[slug]
    body: dict[str, Any] = {
        "type": f"/problems/{slug}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    if errors is not None:
        body["errors"] = errors
    if actions is not None:
        body["actions"] = actions
    return body


def _response(body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=body["status"], media_type=PROBLEM_MEDIA_TYPE)


def install_handlers(app: FastAPI) -> None:
    async def on_problem(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, Problem)
        return _response(
            problem_body(exc.slug, exc.detail, request.url.path, exc.errors, exc.actions)
        )

    async def on_validation(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        errors = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _response(
            problem_body("validation", "Request validation failed", request.url.path, errors)
        )

    async def on_http(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        slug = {404: "not-found", 405: "not-found", 422: "validation", 503: "server-busy"}.get(
            exc.status_code
        )
        if slug is None:
            body = {
                "type": "about:blank",
                "title": str(exc.detail),
                "status": exc.status_code,
                "detail": str(exc.detail),
                "instance": request.url.path,
            }
        else:
            body = problem_body(slug, str(exc.detail), request.url.path)
            body["status"] = exc.status_code
        return JSONResponse(
            body, status_code=exc.status_code, media_type=PROBLEM_MEDIA_TYPE, headers=exc.headers
        )

    app.add_exception_handler(Problem, on_problem)
    app.add_exception_handler(RequestValidationError, on_validation)
    app.add_exception_handler(StarletteHTTPException, on_http)
