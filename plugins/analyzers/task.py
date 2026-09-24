"""Standalone analyzer tasks (`input: rows`, ANZ-02): the same `analyze` as inside the converter."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from plugins.analyzers import Annotation, phase, readiness, target
from plugins.protocol import Job

Analyze = Callable[[Sequence[dict[str, Any]], dict[str, Any]], list[Annotation]]


def _run(job_dir: str, analyze: Analyze, version: str) -> int:
    job = Job(job_dir)
    anns = analyze(job.rows, {**job.context, **job.settings})
    by_key: dict[str, list[Annotation]] = {}
    for a in anns:
        by_key.setdefault(str(a["key"]), []).append(a)
    path = job.rel("annotations.jsonl")
    with path.open("w", encoding="utf-8") as fh:
        for a in anns:
            fh.write(json.dumps({**a, "item_id": a["key"]}, ensure_ascii=False) + "\n")
    for row in job.rows:
        iid = str(row.get("item_id"))
        job.counts["items"] += 1
        job.item(iid, "ok", [{"kind": "annotation", "n": len(by_key.get(iid, []))}])
    job.outputs_manifest.append({"kind": "annotations", "path": "annotations.jsonl"})
    job.finish(versions={"rules": version})
    return 0


def run_phase(job_dir: str) -> int:
    return _run(job_dir, phase.analyze, phase.RULES_VERSION)


def run_target(job_dir: str) -> int:
    return _run(job_dir, target.analyze, target.RULES_VERSION)


def run_readiness(job_dir: str) -> int:
    return _run(job_dir, readiness.analyze, readiness.RULES_VERSION)
