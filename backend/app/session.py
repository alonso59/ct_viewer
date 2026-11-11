"""Sign-in gate for an app that other users of the host can reach (the scheduler-job deployment).

Off unless `SESSION_CREDENTIAL_FILE` is set. Then every request needs a session, except the health
probe and the sign-in page: a browser trades the credential for a cookie once, a script sends the
credential as a bearer token. Sessions live in memory, so they end with the process.
"""

from __future__ import annotations

import secrets
import time
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import PROBLEM_MEDIA_TYPE, problem_body

COOKIE = "rw_session"
SIGN_IN = "/sign-in"
OPEN_PATHS = frozenset({"/api/v1/health", SIGN_IN})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MIN_CREDENTIAL = 32
MAX_FORM_BYTES = 4096
MAX_SESSIONS = 64
MAX_FAILURES = 5
LOCK_SECONDS = 30.0

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Radiology Workbench: sign in</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d1117;color:#e6edf3;
font:14px system-ui,sans-serif}}
form{{width:min(360px,90vw);padding:24px;border:1px solid #30363d;border-radius:6px;
background:#161b22}}
h1{{margin:0 0 8px;font-size:16px}} p{{margin:0 0 16px;color:#8d96a0}}
input{{box-sizing:border-box;width:100%;padding:6px 8px;border:1px solid #30363d;border-radius:6px;
background:#0d1117;color:inherit;font:inherit}}
button{{margin-top:12px;padding:6px 16px;border:1px solid #2ea043;border-radius:6px;
background:#238636;color:#fff;font:inherit;cursor:pointer}}
.error{{color:#f85149}}
</style></head><body><form method="post" action="/sign-in">
<h1>Radiology Workbench</h1>
<p>Enter the session code of this application job. Its start command tells you how to show it.</p>
{error}<label for="credential">Session code</label>
<input id="credential" name="credential" type="password" autocomplete="off" autofocus required>
<button type="submit">Sign in</button>
</form></body></html>
"""


def read_credential(path: Path) -> str:
    credential = path.read_text(encoding="utf-8").strip()
    if len(credential) < MIN_CREDENTIAL:
        raise ValueError(f"SESSION_CREDENTIAL_FILE must hold at least {MIN_CREDENTIAL} characters")
    return credential


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


class SessionGate:
    def __init__(self, app: ASGIApp, credential: str) -> None:
        self.app = app
        self.credential = credential
        self.sessions: dict[str, None] = {}
        self.failures = 0
        self.locked_until = 0.0

    def _authorized(self, headers: Headers, cookies: dict[str, str]) -> bool:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and _same(token.strip(), self.credential):
            return True
        return cookies.get(COOKIE, "") in self.sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request = Request(scope) if scope["type"] == "websocket" else Request(scope, receive)
        authorized = self._authorized(request.headers, request.cookies)
        if scope["type"] == "websocket":
            if authorized:
                await self.app(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        path = scope["path"]
        response: Response | None = None
        if request.method not in SAFE_METHODS and not _same_origin(request.headers):
            response = _problem("cross-origin", path)
        elif path == SIGN_IN:
            response = await self._sign_in(request)
        elif not authorized and path not in OPEN_PATHS:
            if path == "/api" or path.startswith("/api/"):
                response = _problem("session-required", path)
            else:
                response = RedirectResponse(SIGN_IN, status_code=303)
        if response is None:
            await self.app(scope, receive, send)
        else:
            await response(scope, receive, send)

    async def _sign_in(self, request: Request) -> Response:
        if request.method in SAFE_METHODS:
            return _page("")
        if time.monotonic() < self.locked_until:
            return _page("Too many attempts. Wait half a minute and try again.", 429)
        if int(request.headers.get("content-length") or MAX_FORM_BYTES + 1) > MAX_FORM_BYTES:
            return _page("The request was too large.", 413)
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        if not _same(form.get("credential", [""])[0].strip(), self.credential):
            self.failures += 1
            if self.failures >= MAX_FAILURES:
                self.failures = 0
                self.locked_until = time.monotonic() + LOCK_SECONDS
            return _page("That session code is not valid for this job.", 401)
        self.failures = 0
        token = secrets.token_urlsafe(32)
        self.sessions[token] = None
        while len(self.sessions) > MAX_SESSIONS:
            del self.sessions[next(iter(self.sessions))]
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE,
            token,
            path="/",
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return response


def _same_origin(headers: Headers) -> bool:
    """Browsers name the origin of a state-changing request; scripts send none."""
    origin = headers.get("origin")
    return origin is None or urlsplit(origin).netloc == headers.get("host")


def _page(error: str, status: int = 200) -> HTMLResponse:
    block = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        PAGE.format(error=block), status_code=status, headers={"Cache-Control": "no-store"}
    )


def _problem(slug: str, path: str) -> JSONResponse:
    body = problem_body(slug, "", path)
    return JSONResponse(body, status_code=body["status"], media_type=PROBLEM_MEDIA_TYPE)
