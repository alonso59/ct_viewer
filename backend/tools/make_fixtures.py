"""Generate the deterministic synthetic fixture dataset (TST-11, docs/ops/TESTING.md).

Layout mirrors a converter/preprocessor dataset (docs/domain/INPUT_METADATA.md):

    <out>/
      Dataset900/                  data root (register-in-place target)
        metadata.jsonl, phase.json, voi/voi_catalog.jsonl
        nifti/  seg/  voi/images/{group}/{phase}/  voi/mask/{group}/{phase}/
      outside/                     files that exist but lie outside the data root
      expected.json                every deliberate defect -> expected QC code

Byte output is deterministic: fixed RNG seed, gzip mtime=0, sorted JSON keys.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from numpy.typing import NDArray

from app.ingest.codes import QcCode

SEED = 20260923
SHAPE = (64, 64, 48)
SPACING = (0.8, 0.8, 1.5)
DATASET = "Dataset900"
GROUP = "A"


@dataclass
class Plan:
    metadata: list[dict[str, Any]] = field(default_factory=list)
    voi: list[dict[str, Any]] = field(default_factory=list)
    phase_overrides: list[dict[str, str]] = field(default_factory=list)
    expected: list[dict[str, Any]] = field(default_factory=list)

    def expect(self, code: QcCode, case_id: str, note: str, **extra: Any) -> None:
        self.expected.append({"code": code.value, "case_id": case_id, "note": note, **extra})


def _affine(spacing: tuple[float, float, float] = SPACING, shift: float = 0.0) -> NDArray[Any]:
    aff = np.diag([*spacing, 1.0])
    aff[:3, 3] = [-shift, -shift, 0.0]
    return aff


def _ct(rng: np.random.Generator, shape: tuple[int, int, int] = SHAPE) -> NDArray[np.int16]:
    vol = rng.normal(-900, 30, shape)  # air-ish background
    _, yy, xx = np.indices(shape)
    c = np.array(shape) / 2
    body = ((xx - c[2]) / (shape[2] * 0.45)) ** 2 + ((yy - c[1]) / (shape[1] * 0.4)) ** 2 < 1
    vol[body] = rng.normal(40, 15, int(body.sum()))  # soft tissue
    return np.asarray(np.clip(vol, -1024, 3071), dtype=np.int16)


def _labels(shape: tuple[int, int, int] = SHAPE) -> NDArray[np.uint8]:
    """1 kidney (ellipsoid), 2 tumor (sphere inside kidney), 3 cyst (small sphere)."""
    zz, yy, xx = np.indices(shape)
    lab = np.zeros(shape, dtype=np.uint8)
    kidney = ((xx - 20) / 9) ** 2 + ((yy - 32) / 12) ** 2 + ((zz - 24) / 14) ** 2 < 1
    tumor = (xx - 22) ** 2 + (yy - 36) ** 2 + (zz - 26) ** 2 < 5**2
    cyst = (xx - 18) ** 2 + (yy - 26) ** 2 + (zz - 18) ** 2 < 3**2
    lab[kidney] = 1
    lab[cyst & kidney] = 3
    lab[tumor] = 2
    return lab


def _write_nifti(
    path: Path, data: NDArray[Any], affine: NDArray[Any], *, no_affine: bool = False
) -> None:
    # With an affine, nibabel re-stamps the sform on save; no affine gives sform/qform code 0.
    img = nib.Nifti1Image(data, None if no_affine else affine)
    img.header.set_zooms(SPACING[: data.ndim])
    if not no_affine:
        img.header.set_sform(affine, code=1)
        img.header.set_qform(affine, code=1)
    raw = img.to_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0) if path.suffix == ".gz" else raw)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _scan_row(case: str, idx: str, phase: str, **extra: Any) -> dict[str, Any]:
    return {
        "dataset_id": DATASET,
        "case_id": case,
        "patient_id": f"P{case[-3:]}",
        "scan_idx": idx,
        "group": GROUP,
        "filename": f"{idx}_{case}_0000.nii.gz",
        "relative_path": f"nifti/{idx}_{case}_0000.nii.gz",
        "phase": phase,
        "series_uid": f"1.2.826.0.1.{case[-5:]}.{idx}",
        "status": "converted",
        **extra,
    }


def build(out: Path) -> Plan:
    rng = np.random.default_rng(SEED)
    root = out / DATASET
    plan = Plan()
    ct, lab = _ct(rng), _labels()

    def scan(case: str, idx: str, phase: str, *, seg: bool = True, **extra: Any) -> None:
        plan.metadata.append(_scan_row(case, idx, phase, **extra))
        _write_nifti(root / f"nifti/{idx}_{case}_0000.nii.gz", ct, _affine())
        if seg:
            _write_nifti(root / f"seg/{idx}_{case}.nii.gz", lab, _affine())

    def voi(
        case: str,
        idx: str,
        phase: str,
        side: str,
        *,
        image: bool = True,
        mask: bool = True,
        side_value: str | None = None,
    ) -> None:
        img_rel = f"voi/images/{GROUP}/{phase}/{idx}_{case}_{side}.nii.gz"
        msk_rel = f"voi/mask/{GROUP}/{phase}/{idx}_{case}_{side}.nii.gz"
        crop = (slice(8, 40), slice(16, 48), slice(8, 40))
        if image:
            _write_nifti(root / img_rel, ct[crop], _affine())
        if mask:
            _write_nifti(root / msk_rel, lab[crop], _affine())
        plan.voi.append(
            {
                "case_id": case,
                "scan_idx": idx,
                "side": side_value or side,
                "group": GROUP,
                "phase": phase,
                "image_path": img_rel,
                "mask_path": msk_rel,
            }
        )

    # --- Healthy cases: raw phases exercise normalization (ART->CMP, VEN->NP, DELAY->EP).
    healthy = [["NC", "ART", "VEN"], ["NC", "CMP", "NP", "EP"], ["VEN", "DELAY"]]
    for n, phases in enumerate(healthy, 1):
        case = f"case_{n:05d}"
        for i, ph in enumerate(phases, 1):
            scan(case, f"{i:02d}", ph)
        norm = {"ART": "CMP", "VEN": "NP", "DELAY": "EP"}.get(phases[-1], phases[-1])
        voi(case, f"{len(phases):02d}", norm, "L")
        voi(case, f"{len(phases):02d}", norm, "R")
    plan.phase_overrides.append({"case_id": "case_00003", "scan_idx": "02", "phase": "EP"})

    # --- Deliberate defects, one per QC code.
    c = "case_00010"
    plan.metadata.append(_scan_row(c, "01", "NP"))
    plan.expect(QcCode.MISSING_PATH, c, "image file never written", scan_idx="01")

    c = "case_00011"
    scan(c, "01", "NP", seg=False)
    (root / f"nifti/01_{c}_0000.nii.gz").write_bytes(b"not a nifti file")
    plan.expect(QcCode.UNREADABLE_FILE, c, "garbage bytes", scan_idx="01")

    c = "case_00012"
    escape = f"../outside/01_{c}_0000.nii.gz"
    plan.metadata.append(_scan_row(c, "01", "NP", filename="", relative_path=escape))
    _write_nifti(out / "outside/01_case_00012_0000.nii.gz", ct, _affine())
    plan.expect(QcCode.OUTSIDE_ROOT, c, "relative path escapes data root", scan_idx="01")

    c = "case_00013"
    scan(c, "01", "NP", seg=False)
    plan.expect(QcCode.MISSING_SEG, c, "no seg file", scan_idx="01")

    c = "case_00014"
    scan(c, "01", "NP")
    voi(c, "01", "NP", "L", image=False)
    voi(c, "01", "NP", "R", mask=False)
    plan.expect(QcCode.MISSING_VOI_IMAGE, c, "VOI L image missing", scan_idx="01", side="L")
    plan.expect(QcCode.MISSING_VOI_MASK, c, "VOI R mask missing", scan_idx="01", side="R")

    c = "case_00015"
    scan(c, "01", "NP", seg=False)
    _write_nifti(root / f"nifti/01_{c}_0000.nii.gz", ct, _affine(), no_affine=True)
    plan.expect(QcCode.MISSING_AFFINE, c, "sform/qform codes 0", scan_idx="01")

    c = "case_00016"
    scan(c, "01", "NP", seg=False)
    _write_nifti(root / f"seg/01_{c}.nii.gz", lab, _affine(shift=10.0))
    plan.expect(QcCode.AFFINE_MISMATCH, c, "seg origin shifted 10 mm", scan_idx="01")

    c = "case_00017"
    scan(c, "01", "NP", seg=False)
    _write_nifti(root / f"seg/01_{c}.nii.gz", lab[:, :, :40], _affine())
    plan.expect(QcCode.SHAPE_MISMATCH, c, "seg has 40 slices, image 48", scan_idx="01")

    c = "case_00018"
    scan(c, "01", "UNDEFINED")
    plan.expect(QcCode.AMBIGUOUS_PHASE, c, "phase UNDEFINED -> UNK", scan_idx="01")

    c = "case_00019"
    scan(c, "01", "NP")
    voi(c, "01", "NP", "L", side_value="X")
    plan.expect(QcCode.AMBIGUOUS_SIDE, c, "side value 'X'", scan_idx="01")

    c = "case_00020"
    scan(c, "01", "NP")
    plan.metadata.append(_scan_row(c, "01", "CMP"))
    plan.expect(QcCode.DUPLICATE_ROW_IDENTITY, c, "two rows for scan 01", scan_idx="01")

    c = "case_00021"
    scan(c, "01", "NP")
    plan.expect(
        QcCode.FINGERPRINT_CHANGED,
        c,
        "test must run mutate_after_index, then revalidate",
        scan_idx="01",
        mutate_after_index=f"nifti/01_{c}_0000.nii.gz",
    )

    # --- Upstream exclusion (IMP-07) and legacy .npy VOI (IMP-10): not warnings.
    plan.metadata.append(
        {
            "dataset_id": DATASET,
            "case_id": "case_00022",
            "scan_idx": "01",
            "status": "skipped",
            "planned_conversion": "false",
        }
    )
    c = "case_00023"
    scan(c, "01", "NP")
    npy_img = f"voi/images/{GROUP}/NP/01_{c}_L.npy"
    npy_msk = f"voi/mask/{GROUP}/NP/01_{c}_L.npy"
    crop = (slice(8, 40), slice(16, 48), slice(8, 40))
    for rel, arr in ((npy_img, ct[crop]), (npy_msk, lab[crop])):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        np.save(root / rel, arr)
    plan.voi.append(
        {
            "case_id": c,
            "scan_idx": "01",
            "side": "L",
            "group": GROUP,
            "phase": "NP",
            "image_path": npy_img,
            "mask_path": npy_msk,
            "spacing": list(SPACING),
        }
    )

    _write_jsonl(root / "metadata.jsonl", plan.metadata)
    _write_jsonl(root / "voi/voi_catalog.jsonl", plan.voi)
    (root / "phase.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-23T00:00:00Z",
                "phases": plan.phase_overrides,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return plan


def tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(f.relative_to(path).as_posix().encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def generate(out: Path) -> Plan:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    plan = build(out)
    expected = {
        "dataset": DATASET,
        "seed": SEED,
        "defects": plan.expected,
        "excluded_upstream": ["case_00022"],
        "legacy_npy": ["case_00023"],
    }
    (out / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return plan


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--out", type=Path, default=Path("../.fixtures/synthetic"))
    args = ap.parse_args()
    generate(args.out)
    print(f"fixtures -> {args.out.resolve()}  digest {tree_digest(args.out)[:12]}")


if __name__ == "__main__":
    main()
