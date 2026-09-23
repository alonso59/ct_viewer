"""TST-12 support (no tests here): a project imported from the synthetic fixtures, a
synthetic radiomics run written straight to `radiomics/runs/{rid}/`, and external group
variables with known structure. Shared by `test_analytics_*` and `test_dashboard_*`.

Known structure of the run (label 2 = main, label 1 = noisy copy, not for the outlier):
- `arm` (A = even case number, B = odd; the outlier case is missing): B has larger
  MeshVolume (x1.5) and higher firstorder Mean (+8). SurfaceArea and Energy follow volume.
- firstorder Median ~= Mean (redundant); CMP items are +25 brighter than NP.
- `arm3` (X/Y/Z = case number mod 3) shifts glcm Contrast.
- `site` (S1 when case number mod 5 in {0, 1}) is confounded with `manufacturer`.
- `tiny` has groups of 3 / 6 / 24 cases; `coin` is random.
- The outlier case (`case_00062`) is 20x larger and +200 brighter.
- Skewness has NaN for 3 items and inf for one; glcm Idm is absent for one item.
"""

from __future__ import annotations

import io
import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.core.ids import new_ulid
from app.main import create_app
from tests.conftest import make_settings
from tests.test_api_ingest import API, ctx_of, do_import
from tools.make_fixtures import DATASET

COHORT = range(30, 63)  # healthy cohort + the outlier case_00062
OUTLIER = "case_00062"
PHASES = ("NP", "CMP")
NOISE = (
    "original_glcm_Correlation",
    "original_glszm_ZoneEntropy",
    "original_glrlm_RunEntropy",
    "original_gldm_DependenceEntropy",
    "original_ngtdm_Busyness",
)
MEAN = "original_firstorder_Mean"
MEDIAN = "original_firstorder_Median"
VOLUME = "original_shape_MeshVolume"
SURFACE = "original_shape_SurfaceArea"
ENERGY = "original_firstorder_Energy"
CONTRAST = "original_glcm_Contrast"
SKEW = "original_firstorder_Skewness"
IDM = "original_glcm_Idm"
FAILED_ITEM = "case_00001.01.complete.-"


def case_n(case_id: str) -> int:
    return int(case_id[-5:])


def groups_for(n: int, rng: np.random.Generator) -> dict[str, str]:
    return {
        "arm": "" if n == 62 else ("A" if n % 2 == 0 else "B"),
        "arm3": "XYZ"[n % 3],
        "site": "S1" if n % 5 in (0, 1) else "S2",
        "tiny": "small" if n <= 32 else "mid" if n <= 38 else "big",
        "coin": "H" if rng.random() < 0.5 else "T",
    }


@dataclass
class Synthetic:
    pid: str
    run_id: str
    pdir: Path
    groups: dict[str, dict[str, str]]  # case_id -> external variables
    values: dict[tuple[str, int], dict[str, float]] = field(default_factory=dict)
    items: dict[str, dict[str, str]] = field(default_factory=dict)  # item_id -> attrs

    def unit_first(self, feature: str, label: int = 2) -> dict[str, float]:
        """ANA-03 default unit: per case, the NP item (first in the phase priority)."""
        out: dict[str, float] = {}
        for iid, a in sorted(self.items.items()):
            if a["phase"] == "NP" and (iid, label) in self.values:
                out.setdefault(a["case_id"], self.values[(iid, label)][feature])
        return out

    def unit_mean(self, feature: str, label: int = 2) -> dict[str, float]:
        acc: dict[str, list[float]] = {}
        for iid, a in self.items.items():
            if (iid, label) in self.values:
                acc.setdefault(a["case_id"], []).append(self.values[(iid, label)][feature])
        return {c: float(np.mean(v)) for c, v in acc.items()}


def _features(
    n: int, phase: str, g: dict[str, str], case_vol: float, rng: np.random.Generator
) -> dict[str, float]:
    b = g["arm"] == "B"
    vol = case_vol * (1 + rng.normal(0, 0.02))
    mean = 40 + 8 * b + 25 * (phase == "CMP") + rng.normal(0, 2)
    if n == 62:
        vol *= 20
        mean += 200
    f = {
        VOLUME: vol,
        SURFACE: 4.84 * vol ** (2 / 3) * (1 + rng.normal(0, 0.01)),
        MEAN: mean,
        MEDIAN: mean + rng.normal(0, 0.3),
        ENERGY: vol * mean**2,
        CONTRAST: 10 + 3 * "XYZ".index(g["arm3"]) + rng.normal(0, 1),
        SKEW: rng.normal(0, 1),
        IDM: rng.normal(0.5, 0.05),
    }
    for name in NOISE:
        f[name] = rng.normal(10, 2)
    return f


def write_run(pdir: Path, items: list[Any], groups: dict[str, dict[str, str]]) -> Synthetic:
    """Write `features.parquet`, `run.json`, `errors.jsonl` for cohort items (labels 1, 2)."""
    rng = np.random.default_rng(12)
    run_id = new_ulid()
    syn = Synthetic("", run_id, pdir, groups)
    case_vol = {c: float(np.exp(rng.normal(8, 0.3))) * (1.5 if g["arm"] == "B" else 1.0)
                for c, g in sorted(groups.items())}  # fmt: skip
    rows: dict[str, list[Any]] = {k: [] for k in (
        "run_id", "item_id", "case_id", "scan_idx", "scope", "side", "phase", "label",
        "image_type", "feature_class", "feature", "value", "ibsi_code", "ibsi_status",
    )}  # fmt: skip
    skew_bad = 0
    for it in sorted(items, key=lambda i: i.item_id):
        g = groups[it.case_id]
        syn.items[it.item_id] = {"case_id": it.case_id, "phase": it.phase.canonical}
        for label in (1, 2):
            if label == 1 and it.case_id == OUTLIER:
                continue  # label 2 is the most frequent (ANA-03 default label)
            f = _features(case_n(it.case_id), it.phase.canonical, g, case_vol[it.case_id], rng)
            if label == 1:
                f = {k: v * (1 + rng.normal(0, 0.05)) for k, v in f.items()}
            if label == 2 and skew_bad < 4:
                f[SKEW] = float("inf") if skew_bad == 0 else float("nan")
                skew_bad += 1
            if label == 2 and it.item_id == "case_00040.01.complete.-":
                del f[IDM]
            syn.values[(it.item_id, label)] = f
            for key, value in f.items():
                image_type, fclass, feat = key.split("_", 2)
                rows["run_id"].append(run_id)
                rows["item_id"].append(it.item_id)
                rows["case_id"].append(it.case_id)
                rows["scan_idx"].append(it.scan_idx)
                rows["scope"].append(it.scope)
                rows["side"].append(it.side)
                rows["phase"].append(it.phase.canonical)
                rows["label"].append(label)
                rows["image_type"].append(image_type)
                rows["feature_class"].append(fclass)
                rows["feature"].append(feat)
                rows["value"].append(float(value))
                rows["ibsi_code"].append(None)
                rows["ibsi_status"].append("mapped")
    d = pdir / "radiomics" / "runs" / run_id
    d.mkdir(parents=True)
    schema = pa.schema(
        [(k, pa.int64() if k == "label" else pa.float64() if k == "value" else pa.string())
         for k in rows]
    )  # fmt: skip
    pq.write_table(pa.Table.from_pydict(rows, schema=schema), d / "features.parquet")
    inputs = [{"item_id": i} for i in [*sorted(syn.items), FAILED_ITEM]]
    run = {
        "run_id": run_id, "name": "synthetic", "status": "completed_with_errors",
        "created_at": "2026-09-23T10:00:00Z", "started_at": "2026-09-23T10:00:00Z",
        "finished_at": "2026-09-23T10:02:30Z", "selection": {"scope": "complete",
        "labels": [1, 2]}, "inputs": inputs,
        "counts": {"items": len(inputs), "ok": len(syn.items), "failed": 1, "features": 13},
    }  # fmt: skip
    (d / "run.json").write_text(json.dumps(run))
    err = {"item_id": FAILED_ITEM, "case_id": "case_00001", "label": 2, "message": "empty mask"}
    (d / "errors.jsonl").write_text(json.dumps(err) + "\n")
    return syn


def external_csv(groups: dict[str, dict[str, str]]) -> bytes:
    cols = ["arm", "arm3", "site", "tiny", "coin"]
    lines = [",".join(["case_id", *cols])]
    lines += [",".join([c, *(g[k] for k in cols)]) for c, g in sorted(groups.items())]
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture(scope="module")
def mod_client(
    tmp_path_factory: pytest.TempPathFactory, fixtures_src: Path
) -> Iterator[TestClient]:
    tmp = tmp_path_factory.mktemp("analytics")
    fx = tmp / "synthetic"
    shutil.copytree(fixtures_src, fx)
    app = create_app(make_settings(tmp, [fx / DATASET]), inline_jobs=True)
    with TestClient(app) as c:
        c.app.state.fx_root = fx / DATASET  # type: ignore[attr-defined]
        yield c


@pytest.fixture(scope="module")
def syn(mod_client: TestClient) -> Synthetic:
    c = mod_client
    r = c.post(f"{API}/projects", json={"name": "analytics"})
    assert r.status_code == 201, r.text
    pid = str(r.json()["project_id"])
    do_import(c, pid, c.app.state.fx_root)  # type: ignore[attr-defined]
    ctx = ctx_of(c)
    rng = np.random.default_rng(7)
    groups = {f"case_{n:05d}": groups_for(n, rng) for n in COHORT}
    r = c.post(
        f"{API}/projects/{pid}/variables/external",
        files={"file": ("groups.csv", io.BytesIO(external_csv(groups)), "text/csv")},
    )
    assert r.status_code == 201, r.text
    items = [
        i
        for i in ctx.index.load(pid).items
        if i.case_id in groups and i.scope == "complete" and i.phase.canonical in PHASES
    ]
    s = write_run(ctx.workspace.project_dir(pid), items, groups)
    s.pid = pid
    return s


def view(c: TestClient, s: Synthetic, slug: str, body: dict[str, Any] | None = None) -> Any:
    return c.post(f"{API}/projects/{s.pid}/radiomics/runs/{s.run_id}/views/{slug}", json=body)


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


def analyze(c: TestClient, s: Synthetic, **spec: Any) -> Any:
    return c.post(f"{API}/projects/{s.pid}/analyses", json={"run_id": s.run_id, **spec})
