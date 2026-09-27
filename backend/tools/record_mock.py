"""Record the mock API from the real backend on the synthetic fixtures (TST-04, AUD-A6-03).

cd backend && .venv/bin/python -m tools.record_mock      # or `make record-mock`

Runs the app in-process (inline jobs) on a temporary workspace with ALLOWED_DATA_ROOTS = the
fixtures (read only, R1), plays one demo scenario through the HTTP API (project, import,
curation decisions, a phase selection, label tables, a radiomics run, a DICOM conversion) and
writes every exchange to `frontend/src/api/mock/recorded.json`. The frontend's mock mode
(`VITE_API_MODE=mock`, unit tests) replays these responses and computes nothing itself.

Redaction: the project id becomes a fixed id; the fixture folder is `/data`, the workspace
`/workspace`, the derived folder `/derived`; the recording fails if any other absolute host path
is left. The fixtures are synthetic (no PHI).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / ".fixtures" / "synthetic"
OUT = REPO / "frontend" / "src" / "api" / "mock" / "recorded.json"
DEMO_PID = "01JSYNTH900PROJECT00000000"
API = "/api/v1"
# Paging parameters are not part of a recording's key (the replay drops them as well)
PAGING = {"limit", "cursor"}
AP, MK = {"X-Reviewer": "Dr. AP"}, {"X-Reviewer": "Dr. MK"}


class Recorder:
    def __init__(self, client: Any) -> None:
        self.c = client
        self.log: dict[str, dict[str, Any]] = {}

    def call(
        self,
        method: str,
        url: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        *,
        ok: tuple[int, ...] = (200, 201, 202, 204),
    ) -> Any:
        r = self.c.request(method, url, json=body, headers=headers or {})
        if r.status_code not in ok:
            raise SystemExit(f"record-mock: {method} {url} → {r.status_code} {r.text[:400]}")
        data = r.json() if r.content and "json" in r.headers.get("content-type", "") else None
        parts = urlsplit(url)
        query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k not in PAGING))
        key_body = body if method != "GET" else None
        key = f"{method} {parts.path}?{query}#{json.dumps(key_body, sort_keys=True)}"
        # a later call of the same request wins: GETs keep the final state of the scenario
        self.log.pop(key, None)
        self.log[key] = {
            "method": method,
            "path": parts.path,
            "query": query,
            "body": key_body,
            "status": r.status_code,
            "response": data,
        }
        return data

    def get(self, url: str, **k: Any) -> Any:
        sep = "&" if "?" in url else "?"
        return self.call("GET", f"{url}{sep}limit=2000" if k.pop("paged", False) else url, **k)


def wait_jobs(c: Any, pid: str | None = None, timeout: float = 240) -> None:
    deadline = time.monotonic() + timeout
    q = f"?project={pid}" if pid else ""
    while time.monotonic() < deadline:
        jobs = c.get(f"{API}/jobs{q}").json()
        if all(j["status"] not in ("queued", "running") for j in jobs):
            return
        time.sleep(0.1)
    raise SystemExit("record-mock: jobs did not finish in time")


def scenario(rec: Recorder, data: Path, derived: Path) -> None:
    c = rec.c
    call, get = rec.call, rec.get
    p = call("POST", f"{API}/projects", {"name": "Dataset900 (synthetic)", "description": ""})
    pid = p["project_id"]
    P = f"{API}/projects/{pid}"
    call("POST", f"{P}/packs", {"pack_id": "ccrcc"})
    call("PUT", f"{P}/roots/DERIVED", {"path": str(derived), "role": "derived"})
    root = str(data / "Dataset900")
    pv = call(
        "POST",
        f"{P}/imports/preview",
        {
            "root": root,
            "alias": "DATA",
            "detect": True,
            "adapter": None,
            "options": {},
            "add": False,
        },
    )
    call("POST", f"{P}/imports", {"preview_id": pv["preview_id"]})
    wait_jobs(c, pid)

    # PRJ-15/17: a stale settings write (412), a fresh one, a view link created and revoked
    etag = get(P)["etag"]
    call("PATCH", P, {"description": "stale"}, {"If-Match": '"stale"'}, ok=(412,))
    call("PATCH", P, {"description": "Synthetic demo dataset (TST-11)"}, {"If-Match": etag})
    call("POST", f"{P}/view-token")
    call("DELETE", f"{P}/view-token")
    etag = get(P)["etag"]
    labels = get(P)["label_map"]
    call("PATCH", P, {"label_map": labels}, {"If-Match": etag})

    # CUR-*: the demo review story (two reviewers, one case in the queue, one rejected)
    def decide(who: dict[str, str], item: str, target: str, status: str, **extra: Any) -> None:
        ev = {
            "item_id": item,
            "case_id": item.split(".")[0],
            "target": target,
            "status": status,
            "priority": "medium",
            "comment": "",
            "add_to_queue": False,
            "context": {},
            "source": "ui",
        }
        call("POST", f"{P}/curation/events", {**ev, **extra}, who)

    for n in ("01", "02", "03"):
        decide(AP, f"case_00001.{n}.complete.-", "seg", "accepted")
    decide(AP, "case_00002.01.complete.-", "seg", "accepted")
    decide(
        AP,
        "case_00002.03.complete.-",
        "label:2",
        "needs_minor_correction",
        comment="Tumor boundary leaks into renal sinus on slices 20-26",
        context={"viewer": {"axis": "axial", "slice": 24, "ww": 400, "wl": 50}},
    )
    decide(MK, "case_00003.01.complete.-", "seg", "accepted")
    decide(
        MK,
        "case_00014.01.complete.-",
        "label:2",
        "needs_major_correction",
        priority="high",
        comment="Tumor under-segmented; lower pole missing",
        add_to_queue=True,
    )
    decide(
        AP,
        "case_00016.01.complete.-",
        "seg",
        "rejected",
        priority="high",
        comment="Mask shifted ~10 mm against the image",
    )
    # PHS-01/03: one native phase selection (case_00002 scan 02, CMP at import → NP)
    call(
        "POST",
        f"{P}/phase/events",
        {
            "case_id": "case_00002",
            "scan_idx": "02",
            "value": "NP",
            "source": "manual",
            "session_id": "record",
        },
        AP,
    )
    get(f"{P}/phase/events?case_id=case_00002&scan_idx=02&limit=500")

    # LBL-*: a case table with values, a scan table with a reference column, a deleted table
    T = f"{API}/plugins/labeling/projects/{pid}/tables"
    review = call(
        "POST",
        T,
        {
            "name": "Review",
            "level": "case",
            "columns": [
                {"name": "Grade", "type": "category", "levels": ["G1", "G2"]},
                {"name": "Size", "type": "number", "unit": "mm", "max": 100},
                {"name": "Smoker", "type": "bool"},
                {"name": "Note", "type": "text"},
            ],
        },
    )
    grade, size = (col["column_id"] for col in review["columns"][:2])
    call(
        "POST",
        f"{T}/{review['table_id']}/cells",
        {
            "cells": [
                {"column_id": grade, "target": "case_00001", "value": "G1"},
                {"column_id": size, "target": "case_00001", "value": 42},
                {"column_id": grade, "target": "case_00002", "value": "G2"},
            ]
        },
        AP,
    )
    # LBL-02: a column patch (no change), the answer the table's edits replay
    call(
        "PATCH",
        f"{T}/{review['table_id']}",
        {"columns": [{"column_id": size, "name": "Size", "unit": "mm"}]},
    )
    phase_tab = call(
        "POST",
        T,
        {
            "name": "Phase check",
            "level": "scan",
            "columns": [
                {"name": "App phase", "ref": "phase.effective"},
                {"name": "Mine", "type": "text"},
            ],
        },
    )
    # LBL-09: a reference column is read-only (the refusal is recorded)
    ref = phase_tab["columns"][0]["column_id"]
    call(
        "POST",
        f"{T}/{phase_tab['table_id']}/cells",
        {"cells": [{"column_id": ref, "target": "case_00001.01", "value": "NC"}]},
        AP,
        ok=(400, 409, 422),
    )
    mine = phase_tab["columns"][1]["column_id"]
    call(
        "POST",
        f"{T}/{phase_tab['table_id']}/cells",
        {"cells": [{"column_id": mine, "target": "case_00001.02", "value": "arterial?"}]},
        AP,
    )
    scratch = call(
        "POST",
        T,
        {"name": "Scratch", "level": "case", "columns": [{"name": "Note", "type": "text"}]},
    )
    call("PATCH", f"{T}/{scratch['table_id']}", {"hidden": True})
    for t in (review, phase_tab):
        get(f"{T}/{t['table_id']}/cells", paged=True)
    get(f"{T}/{review['table_id']}/history?target=case_00001&column_id={size}")

    # VAR-06: one derived grouping variable
    call(
        "POST",
        f"{P}/variables/derived",
        {
            "op": "bin",
            "name": "marker_group",
            "source": "marker_a",
            "quantiles": [0.5],
            "labels": ["low", "high"],
        },
    )

    # RAD-*: the engine defaults as a profile, one run (first-order + shape, NP, tumor)
    # validate, estimate and runs are the task routes of `radiomics.pyradiomics` (RAD-13)
    rad = "radiomics.pyradiomics"
    schema = get(f"{API}/radiomics/schema")
    check = {"settings": {}, "labels": [2], "n_items": 10}
    call("POST", f"{API}/tasks/{rad}/validate", check)
    call("POST", f"{P}/radiomics/profiles", {"name": "Engine defaults", "settings": {}})
    settings = {"features": {"firstorder": None, "shape": ["MeshVolume"]}}
    sel = {"scope": "complete", "labels": [2], "filter": {"phase": ["NP"]}, "seg_id": "imported"}
    call("POST", f"{P}/tasks/{rad}/estimate", {"settings": settings, "selection": sel})
    run = call(
        "POST",
        f"{P}/task-runs",
        {"task_id": rad, "name": "NP tumor first-order", "settings": settings, "selection": sel},
        AP,
    )
    wait_jobs(c, pid)
    rid = run["run_id"]
    R = f"{P}/radiomics/runs/{rid}"
    get(f"{P}/task-runs?task={rad}")
    get(f"{P}/task-runs/{rid}")
    get(f"{R}/features?format=json&shape=long")
    get(f"{P}/task-runs/{rid}/errors")
    for view, body in (
        ("run-overview", {}),
        ("outliers", {"threshold": 3}),
        ("missing-matrix", {}),
        ("feature-distribution", {"feature": "original_firstorder_Mean"}),
        ("feature-vs-volume", {"feature": "original_firstorder_Mean"}),
        ("correlation", {}),
        ("embedding", {}),
        ("phase-side-consistency", {"feature": "original_firstorder_Mean"}),
        ("balance", {"variable": "marker_group", "other": "phase.effective"}),
        ("association", {"variable": "marker_a"}),
        ("group-comparison", {"variable": "marker_group", "feature": "original_firstorder_Mean"}),
    ):
        call("POST", f"{R}/views/{view}", body, ok=(200, 422))
    get(f"{P}/analyses")
    del schema

    # TSK-*: the catalogue, the threshold task's validate / preflight / estimate
    tasks = get(f"{API}/tasks")
    for t in tasks["tasks"]:
        get(f"{API}/tasks/{t['manifest']['id']}")
    call("POST", f"{API}/tasks/segment.threshold/validate", {"settings": {}})
    call("POST", f"{P}/tasks/segment.threshold/preflight", {"selection": {}, "settings": {}})
    call("POST", f"{P}/tasks/segment.threshold/estimate", {"selection": {}, "settings": {}})
    get(f"{P}/task-runs")

    # DCM-* / UI-25: dry run and conversion of one DICOM patient folder into the workspace
    src = {"source": str(data / "dicom" / "P900")}
    call("POST", f"{API}/tasks/dicom.convert/estimate", {"selection": src, "settings": {}})
    ws = call(
        "POST",
        f"{API}/task-runs",
        {"task_id": "dicom.convert", "settings": {}, "selection": src, "name": None},
    )
    wait_jobs(c)
    get(f"{API}/task-runs")
    get(f"{API}/task-runs/{ws['run_id']}")

    # Reads of the final state (what the workbench fetches)
    get(f"{API}/health")
    get(f"{API}/projects?archived=false")
    get(f"{API}/projects?archived=true")
    get(P)
    get(f"{P}/roots")
    get(f"{API}/packs")
    get(f"{API}/plugins")
    get(f"{API}/plugins?project={pid}")
    get(f"{P}/imports")
    get(f"{P}/warnings", paged=True)
    get(f"{P}/variables")
    get(f"{P}/segmentations")
    get(f"{P}/layers")
    get(f"{P}/annotations")
    get(f"{P}/curation/state")
    get(f"{P}/curation/queue?format=json")
    get(f"{P}/curation/events", paged=True)
    get(f"{P}/phase/events?limit=500")
    get(f"{P}/radiomics/profiles", paged=True)
    get(f"{T}", paged=False)
    get(f"{T}?deleted=true")
    get(f"{API}/jobs?project={pid}")
    cases = get(f"{P}/cases", paged=True)
    for q in (
        "phase=NP",
        "curation_status=accepted",
        "curation_status=needs_major_correction",
        "q=case_0001",
    ):
        get(f"{P}/cases?{q}", paged=True)
    for cs in cases["items"]:
        d = get(f"{P}/cases/{cs['case_id']}")
        for scan in d["scans"]:
            for it in scan["items"]:
                get(f"{P}/items/{it['item_id']}")
    # FolderBrowser (API-10) and source detection (SRC-*) over the fixtures
    call("POST", f"{API}/fs/list", {"path": None, "role": "source"})
    for sub in ("", "Dataset900", "Dataset900/nifti", "dicom"):
        call(
            "POST",
            f"{API}/fs/list",
            {"path": str(data / sub) if sub else str(data), "role": "source"},
        )
    call("POST", f"{API}/sources/detect", {"path": root})


def dump(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def redact(text: str, pid: str, data: Path, workspace: Path, derived: Path, plugins: Path) -> str:
    builtin = REPO / "plugins"
    pairs = (
        (derived, "/derived"),
        (workspace, "/workspace"),
        (plugins, "/plugins"),
        (builtin, "/app/plugins"),
        (data, "/data"),
    )
    for real, alias in pairs:
        for form in sorted({str(real), str(real.resolve())}, key=len, reverse=True):
            text = text.replace(form, alias)
    text = text.replace(pid, DEMO_PID).replace("http://testserver", "http://localhost")
    left = re.findall(
        r"(?:/Users/|/Volumes/|/home/|/private/|/tmp/|/var/folders/)[^\"]{0,60}", text
    )
    if left:
        raise SystemExit(f"record-mock: absolute host paths left after redaction: {left[:3]}")
    return text


def main() -> None:
    if not (FIXTURES / "expected.json").exists():
        raise SystemExit("record-mock: run `make fixtures` first (.fixtures/synthetic)")
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="rw-record-"))
    try:
        workspace, derived, plugins = tmp / "workspace", tmp / "derived", tmp / "plugins"
        derived.mkdir()
        plugins.mkdir()
        # external manifests: the CI threshold plugin only, as in the E2E setup (TST-14)
        (plugins / "threshold").symlink_to(REPO / "plugins" / "threshold")
        settings = Settings(
            workspace_root=workspace,
            allowed_data_roots=str(FIXTURES.resolve()),
            allowed_derived_roots=str(derived.resolve()),
            plugins_root=plugins,
            job_workers=2,
            _env_file=None,  # type: ignore[call-arg]
        )
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            rec = Recorder(client)
            scenario(rec, FIXTURES.resolve(), derived.resolve())
            pid = next(
                e["response"]["project_id"]
                for e in rec.log.values()
                if e["method"] == "POST" and e["path"] == f"{API}/projects"
            )
            version = client.get(f"{API}/health").json().get("version")
        head = {
            "format": 1,
            "note": "Written by `make record-mock` (backend/tools/record_mock.py); do not edit.",
            "backend_version": version,
            "project_id": DEMO_PID,
        }
        # one exchange per line keeps re-recordings reviewable in a diff
        rows = ",\n".join(dump(e) for e in rec.log.values())
        text = f'{dump(head)[:-1]},"exchanges":[\n{rows}\n]}}'

        OUT.write_text(
            redact(text, pid, FIXTURES, workspace, derived, plugins) + "\n", encoding="utf-8"
        )
        kib = OUT.stat().st_size // 1024
        print(f"record-mock: {len(rec.log)} exchanges → {OUT.relative_to(REPO)} ({kib} KiB)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
