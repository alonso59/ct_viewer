"""The CTFlow script library (CTF-17): saved scripts and procedures, the only files `source`
reads and the only ones a script run starts from by name.

Lookup order: the project (`{project}/plugins/ctflow/scripts/`), the workspace
(`WORKSPACE_ROOT/plugins/ctflow/scripts/`), then the first-party examples shipped with the app
(read-only). App state only: never a source root (R1).

A script's leading `#` lines describe it: the first plain line is its summary, and
`# param <name> [default]  <help>` declares a parameter (no default = required).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_bytes
from app.ctflow.lang import ScriptError, parse_script
from app.projects.service import Workspace

SHIPPED = Path(__file__).with_name("scripts")
NAMESPACE = ("plugins", "ctflow", "scripts")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\.ctf$")
SCRIPT_MAX = 100_000
_PARAM = re.compile(r"^#\s*param\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(\S+))?(?:\s+(.*))?$")
Scope = Literal["project", "workspace", "shipped"]


class ScriptParam(BaseModel):
    name: str
    default: str | None = None  # None: required
    help: str = ""


class ScriptInfo(BaseModel):
    name: str
    scope: Scope
    summary: str = ""
    params: list[ScriptParam] = Field(default_factory=list)


class ScriptText(ScriptInfo):
    text: str


def header(text: str) -> tuple[str, list[ScriptParam]]:
    summary, params = "", []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("#"):
            break
        m = _PARAM.match(line)
        if m:
            default = m.group(2)
            params.append(
                ScriptParam(
                    name=m.group(1),
                    default=None if default in (None, "-") else default,
                    help=(m.group(3) or "").strip(),
                )
            )
        elif not summary and line.lstrip("#").strip():
            summary = line.lstrip("#").strip()
    return summary, params


def checked_name(name: str) -> None:
    if not NAME.match(name):
        raise ValidationProblem("Name a library script like nightly.ctf (letters, digits, . _ -)")


class Library:
    def __init__(self, settings: Settings, workspace: Workspace) -> None:
        self.settings, self.workspace = settings, workspace

    def _dirs(self, project: str | None) -> list[tuple[Scope, Path]]:
        dirs: list[tuple[Scope, Path]] = []
        if project is not None:
            dirs.append(("project", self.workspace.project_dir(project).joinpath(*NAMESPACE)))
        dirs.append(("workspace", self.settings.workspace_root.joinpath(*NAMESPACE)))
        dirs.append(("shipped", SHIPPED))
        return dirs

    def list(self, project: str | None) -> list[ScriptInfo]:
        seen: dict[str, ScriptInfo] = {}
        for scope, folder in self._dirs(project):
            for path in sorted(folder.glob("*.ctf")) if folder.is_dir() else []:
                if path.name in seen or not NAME.match(path.name):
                    continue  # a project script hides a workspace or shipped one of that name
                summary, params = header(path.read_text(encoding="utf-8"))
                seen[path.name] = ScriptInfo(
                    name=path.name, scope=scope, summary=summary, params=params
                )
        return sorted(seen.values(), key=lambda s: s.name)

    def read(self, name: str, project: str | None) -> ScriptText:
        checked_name(name)
        for scope, folder in self._dirs(project):
            path = folder / name
            if path.is_file():
                if path.stat().st_size > SCRIPT_MAX:
                    raise ValidationProblem(f"{name} is larger than {SCRIPT_MAX} bytes")
                text = path.read_text(encoding="utf-8")
                summary, params = header(text)
                return ScriptText(name=name, scope=scope, summary=summary, params=params, text=text)
        raise NotFound(f"No script {name!r} in the CTFlow library")

    def save(self, name: str, text: str, project: str | None) -> ScriptInfo:
        checked_name(name)
        if len(text.encode()) > SCRIPT_MAX:
            raise ValidationProblem(f"A library script has at most {SCRIPT_MAX} bytes")
        try:
            parse_script(text)
        except ScriptError as exc:
            where = f"line {exc.line}: " if exc.line else ""
            raise ValidationProblem(f"The script does not parse: {where}{exc.message}") from None
        scope, folder = self._dirs(project)[0]
        atomic_write_bytes(folder / name, text.encode())
        summary, params = header(text)
        return ScriptInfo(name=name, scope=scope, summary=summary, params=params)

    def delete(self, name: str, project: str | None) -> None:
        checked_name(name)
        scope, folder = self._dirs(project)[0]
        path = folder / name
        if not path.is_file():
            raise NotFound(f"No {scope} script {name!r}; shipped examples cannot be removed")
        path.unlink()
