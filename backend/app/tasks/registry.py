"""Task manifest registry (TSK-01): builtin manifests + admin-installed `PLUGINS_ROOT/*/task.json`.

Builtin: `app/radiomics/task.json` and every `{builtin_plugins_root}/*/task*.json` whose runtime
is `builtin` (external manifests shipped next to them, e.g. the CI `segment.threshold`, are for
`PLUGINS_ROOT`). External: `PLUGINS_ROOT/*/task.json`, which must use the external runtime.
Invalid manifests are listed with their error and never loaded.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.core.errors import NotFound
from app.tasks.models import InvalidManifest, RunnerInfo, TaskInfo, TaskManifest
from app.tasks.schema import check_schema

RADIOMICS_MANIFEST = Path(__file__).resolve().parents[1] / "radiomics" / "task.json"
RADIOMICS_TASK = "radiomics.pyradiomics"
RUNNER_FRESH_S = 30.0  # 3 missed 10 s heartbeats (TASKS.md §External runtime)


def ensure_importable(builtin_root: Path) -> None:
    """Make the `plugins` package importable (workers inherit `sys.path` under spawn)."""
    parent = str(builtin_root.resolve().parent)
    if builtin_root.is_dir() and parent not in sys.path:
        sys.path.append(parent)


def manifest_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_manifest(path: Path) -> tuple[TaskManifest, str]:
    """Raise ValueError with a readable reason for any invalid manifest."""
    data = path.read_bytes()
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON: {exc}") from None
    try:
        m = TaskManifest.model_validate(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join(str(x) for x in e["loc"]) or "manifest"
        raise ValueError(f"{loc}: {e['msg']}") from None
    check_schema(m.settings_schema)
    return m, manifest_hash(data)


def _entry_available(entry: str) -> str | None:
    module = entry.partition(":")[0]
    try:
        found = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        found = False
    return None if found else f"entry module {module!r} is not installed"


@dataclass
class Registry:
    tasks: dict[str, TaskInfo] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)
    invalid: list[InvalidManifest] = field(default_factory=list)

    def add(
        self,
        m: TaskManifest,
        mhash: str,
        source: Literal["builtin", "plugins_root"],
        path: Path | None = None,
    ) -> None:
        if m.id in self.tasks:
            self.invalid.append(
                InvalidManifest(path=str(path or m.id), error=f"duplicate task id {m.id!r}")
            )
            return
        reason = _entry_available(m.runtime.entry) if m.runtime.entry else None
        if (
            m.id == RADIOMICS_TASK
            and reason is None
            and importlib.util.find_spec("radiomics") is None
        ):
            reason = "PyRadiomics is not installed (the [radiomics] extra)"
        self.tasks[m.id] = TaskInfo(
            manifest=m,
            source=source,
            manifest_hash=mhash,
            available=reason is None,
            unavailable_reason=reason,
            settings_schema_url="/api/v1/radiomics/schema" if m.id == RADIOMICS_TASK else None,
        )
        if path is not None:
            self.paths[m.id] = path

    def load(self, files: Iterable[Path], source: Literal["builtin", "plugins_root"]) -> None:
        for p in sorted(files):
            try:
                m, h = parse_manifest(p)
                if source == "plugins_root" and m.runtime.type != "external":
                    raise ValueError("manifests under PLUGINS_ROOT must use the external runtime")
            except (OSError, ValueError) as exc:
                self.invalid.append(InvalidManifest(path=str(p), error=str(exc)))
                continue
            if source == "builtin" and m.runtime.type != "builtin":
                continue  # shipped for PLUGINS_ROOT (e.g. the CI plugin)
            self.add(m, h, source, p)

    def get(self, task_id: str) -> TaskInfo:
        info = self.tasks.get(task_id)
        if info is None:
            raise NotFound(f"Task {task_id!r} not found")
        return info

    def plugin_dir(self, task_id: str) -> Path | None:
        p = self.paths.get(task_id)
        return p.parent if p is not None else None


def build_registry(builtin_root: Path, plugins_root: Path | None) -> Registry:
    ensure_importable(builtin_root)
    reg = Registry()
    reg.load([RADIOMICS_MANIFEST], "builtin")
    if builtin_root.is_dir():
        reg.load(builtin_root.glob("*/task*.json"), "builtin")
    if plugins_root is not None and plugins_root.is_dir():
        reg.load(plugins_root.glob("*/task.json"), "plugins_root")
    return reg


def runners(queue_dir: Path, now: datetime | None = None) -> list[RunnerInfo]:
    """Runner heartbeats `queue/runners/{runner_id}.json` (TSK-11)."""
    now = now or datetime.now(UTC)
    out: list[RunnerInfo] = []
    for p in sorted((queue_dir / "runners").glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            at = datetime.fromisoformat(str(raw["at"]).replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out.append(
            RunnerInfo(
                runner_id=p.stem,
                tasks=[str(t) for t in raw.get("tasks") or []],
                gpu=raw.get("gpu"),
                pid=raw.get("pid"),
                at=str(raw["at"]),
                fresh=(now - at).total_seconds() <= RUNNER_FRESH_S,
            )
        )
    return out


def runner_online(queue_dir: Path, task_id: str) -> bool:
    return any(r.fresh and (not r.tasks or task_id in r.tasks) for r in runners(queue_dir))
