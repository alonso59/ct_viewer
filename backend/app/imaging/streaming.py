"""Volume/thumbnail byte responses: original bytes, HTTP Range, ETag = quick fingerprint (BE-04).

The API process never decodes volumes here; Starlette's `FileResponse` streams the file
(opened `rb`) and handles `Range` / `If-Range` / `HEAD`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, Response

VOLUME_MEDIA_TYPE = "application/octet-stream"
WEBP_MEDIA_TYPE = "image/webp"


def quote_etag(fp: str) -> str:
    return f'"{fp}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison of an `If-None-Match` list against a quoted `etag`."""
    if not if_none_match:
        return False
    for raw in if_none_match.split(","):
        tag = raw.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag == etag:
            return True
    return False


def not_modified(etag: str) -> Response:
    return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})


def is_not_modified(request: Request, fp: str) -> bool:
    return etag_matches(request.headers.get("if-none-match"), quote_etag(fp))


def volume_response(path: Path, fp: str, name: str, request: Request) -> Response:
    """Stream `path` as `name` (NiiVue needs the extension); 304 when the client has `fp`."""
    etag = quote_etag(fp)
    if is_not_modified(request, fp):
        return not_modified(etag)
    return FileResponse(
        path,
        media_type=VOLUME_MEDIA_TYPE,
        filename=name,
        content_disposition_type="inline",
        headers={
            "ETag": etag,
            "Cache-Control": "no-cache",
            "Accept-Ranges": "bytes",
            "X-Volume-Name": name if name.isascii() else quote(name),
        },
    )


def webp_response(path: Path, fp: str, request: Request) -> Response:
    etag = quote_etag(fp)
    if is_not_modified(request, fp):
        return not_modified(etag)
    return FileResponse(
        path, media_type=WEBP_MEDIA_TYPE, headers={"ETag": etag, "Cache-Control": "no-cache"}
    )
