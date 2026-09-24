"""Generate the deterministic synthetic fixture dataset (TST-11, docs/ops/TESTING.md).

Layout mirrors a converter/preprocessor dataset (docs/domain/INPUT_METADATA.md):

    <out>/
      Dataset900/                  data root (register-in-place target)
        metadata.jsonl, phase.json, voi/voi_catalog.jsonl
        nifti/  seg/  voi/images/{subdir}/{phase}/  voi/mask/{subdir}/{phase}/
      outside/                     files that exist but lie outside the data root
      dicom/                       small DICOM source (2 patients, 3 series): converter, Open mode
      expected.json                every deliberate defect -> expected QC code

Study variables (TESTING.md §Variables; VARIABLES.md): there is no `group` field. A healthy
cohort (`COHORT` cases, two scans each) carries invented case-level study variables — a
compositional pair `marker_a + marker_b = 100` present for about half the cases, a
numeric-discrete `grade`, a continuous `score` — plus scan-level acquisition fields with
vendor strings that need a recode, one MRI scan, dates, a UID, an accession number, an
absolute path and a `raw_metadata` blob. Tumor size and intensity depend on the variables,
so radiomics features differ between groups; one case is a deliberate radiomics outlier.
Values are synthetic; nothing is copied from real metadata.

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
VOI_SUBDIR = "A"  # an upstream folder level; never read as a variable (INPUT_METADATA.md)
COHORT = range(30, 62)  # healthy cohort case numbers (32 cases, TESTING.md: >= 30)
OUTLIER_CASE = "case_00062"  # radiomics outlier: oversized, very bright tumor mask
MRI_SCAN = ("case_00061", "02")
VENDORS = (  # raw strings that need a recode into 3 vendors (VAR-06)
    ("SIEMENS", "SOMATOM Force"),
    ("Siemens Healthineers", "SOMATOM go.Top"),
    ("Philips Medical Systems", "IQon"),
    ("PHILIPS", "Brilliance 64"),
    ("GE MEDICAL SYSTEMS", "Revolution CT"),
)


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


def _labels(shape: tuple[int, int, int] = SHAPE, tumor_r: float = 5.0) -> NDArray[np.uint8]:
    """1 kidney (ellipsoid), 2 tumor (sphere inside kidney), 3 cyst (small sphere)."""
    zz, yy, xx = np.indices(shape)
    lab = np.zeros(shape, dtype=np.uint8)
    kidney = ((xx - 20) / 9) ** 2 + ((yy - 32) / 12) ** 2 + ((zz - 24) / 14) ** 2 < 1
    tumor = (xx - 22) ** 2 + (yy - 36) ** 2 + (zz - 26) ** 2 < tumor_r**2
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


def _acquisition(case: str, idx: str) -> dict[str, Any]:
    """Scan-level converter fields (VAR-04 Acquisition group), deterministic per scan."""
    n, i = int(case[-5:]), int(idx)
    vendor, model = VENDORS[n % len(VENDORS)]
    day = 1 + (n * 7 + i) % 28
    return {
        "manufacturer": vendor,
        "manufacturer_model": model,
        "kvp": ("100", "120", "140")[(n + i) % 3],
        "slice_thickness": ("1", "1.25", "2.5", "5")[n % 4],
        "convolution_kernel": ("B30f", "Br40", "STANDARD", "FC18")[n % 4],
        "modality": "MR" if (case, idx) == MRI_SCAN else "CT",
        "scan_date": f"2021-{1 + n % 12:02d}-{day:02d}",
        "acquisition_date": f"2021{1 + n % 12:02d}{day:02d}",
        "xray_tube_current": str(180 + (n * 37 + i * 11) % 240),
        "study_uid": f"1.2.826.0.2.{n}.{i}",
        "accession_number": f"ACC{n:05d}{i}",
        "first_file": f"/dicom/{case}/{idx}/IM000001.dcm",
        "phase_guess_evidence": f"series {n}-{i}: contrast timing note {(n * i) % 29}",
        "raw_metadata": {
            "PatientSex": "F" if n % 2 else "M",
            "PatientAge": f"{40 + n % 37:03d}Y",
            "AccessionNumber": f"ACC{n:05d}{i}",
            "StudyInstanceUID": f"1.2.826.0.2.{n}.{i}",
        },
    }


def _scan_row(case: str, idx: str, phase: str, **extra: Any) -> dict[str, Any]:
    return {
        "dataset_id": DATASET,
        "case_id": case,
        "patient_id": f"P{case[-3:]}",
        "scan_idx": idx,
        "filename": f"{idx}_{case}_0000.nii.gz",
        "relative_path": f"nifti/{idx}_{case}_0000.nii.gz",
        "phase": phase,
        "series_uid": f"1.2.826.0.1.{case[-5:]}.{idx}",
        "status": "converted",
        **_acquisition(case, idx),
        **extra,
    }


def study_variables(n: int, rng: np.random.Generator) -> dict[str, str]:
    """Invented case-level study variables (strings, like converter output; '' = missing)."""
    a = round(float(rng.uniform(5, 95)), 1)
    present = n % 2 == 0  # about half of the cohort (VAR-01 missing %, REC-MISSING)
    return {
        "marker_a": f"{a:g}" if present else "",
        "marker_b": f"{100 - a:g}" if present else "",
        "grade": str(1 + n % 4) if n % 5 else "",
        "score": f"{float(rng.normal(50, 12)):.2f}",
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
        img_rel = f"voi/images/{VOI_SUBDIR}/{phase}/{idx}_{case}_{side}.nii.gz"
        msk_rel = f"voi/mask/{VOI_SUBDIR}/{phase}/{idx}_{case}_{side}.nii.gz"
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
    plan.metadata[-1]["seg_path"] = f"seg/01_{c}.mha"  # not an accepted format (SRC-02)
    (root / f"seg/01_{c}.mha").write_bytes(b"ObjectType = Image\n")
    plan.expect(QcCode.MISSING_SEG, c, "no seg file", scan_idx="01")
    plan.expect(QcCode.UNSUPPORTED_FORMAT, c, "seg_path is a .mha file", scan_idx="01")

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
    npy_img = f"voi/images/{VOI_SUBDIR}/NP/01_{c}_L.npy"
    npy_msk = f"voi/mask/{VOI_SUBDIR}/NP/01_{c}_L.npy"
    crop = (slice(8, 40), slice(16, 48), slice(8, 40))
    for rel, arr in ((npy_img, ct[crop]), (npy_msk, lab[crop])):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        np.save(root / rel, arr)
    plan.voi.append(
        {
            "case_id": c,
            "scan_idx": "01",
            "side": "L",
            "phase": "NP",
            "image_path": npy_img,
            "mask_path": npy_msk,
            "spacing": list(SPACING),
        }
    )
    # The R crop declares an axis order that is neither xyz nor zyx (SRC-12).
    npy_img_r, npy_msk_r = npy_img.replace("_L.npy", "_R.npy"), npy_msk.replace("_L.npy", "_R.npy")
    for rel, arr in ((npy_img_r, ct[crop]), (npy_msk_r, lab[crop])):
        np.save(root / rel, arr)
    plan.voi.append(
        {
            "case_id": c,
            "scan_idx": "01",
            "side": "R",
            "phase": "NP",
            "image_path": npy_img_r,
            "mask_path": npy_msk_r,
            "spacing": list(SPACING),
            "axis_order": "yxz",
        }
    )
    plan.expect(QcCode.AMBIGUOUS_AXIS_ORDER, c, "catalog axis_order 'yxz'", scan_idx="01", side="R")

    # --- Healthy cohort with study variables (VAR/ANA fixtures), then the radiomics outlier.
    for n in COHORT:
        case = f"case_{n:05d}"
        study = study_variables(n, rng)
        marker = float(study["marker_a"]) if study["marker_a"] else float(rng.uniform(5, 95))
        # Tumor grows with `score`; tumor intensity rises with `marker_a` (group signal).
        radius = float(np.clip(3.5 + (float(study["score"]) - 50) / 12, 2.5, 7.0))
        lab_n = _labels(tumor_r=radius)
        for idx, ph in (("01", "NP"), ("02", "ART")):
            vol = _ct(rng).astype(np.int32)
            tumor = lab_n == 2
            vol[tumor] = rng.normal(20 + 0.8 * marker, 12, int(tumor.sum())).astype(np.int32)
            plan.metadata.append(_scan_row(case, idx, ph, **study))
            _write_nifti(root / f"nifti/{idx}_{case}_0000.nii.gz", vol.astype(np.int16), _affine())
            _write_nifti(root / f"seg/{idx}_{case}.nii.gz", lab_n, _affine())
    c = OUTLIER_CASE
    vol = _ct(rng).astype(np.int32)
    lab_o = _labels(tumor_r=11.0)
    vol[lab_o == 2] = rng.normal(900, 250, int((lab_o == 2).sum())).astype(np.int32)
    plan.metadata.append(_scan_row(c, "01", "NP", **study_variables(62, rng)))
    _write_nifti(root / f"nifti/01_{c}_0000.nii.gz", vol.astype(np.int16), _affine())
    _write_nifti(root / f"seg/01_{c}.nii.gz", lab_o, _affine())

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
        "cohort": [f"case_{n:05d}" for n in COHORT],
        "radiomics_outlier": [OUTLIER_CASE],
        "mri_scan": list(MRI_SCAN),
        "variables": {
            "study": ["marker_a", "marker_b", "grade", "score", "patient_sex", "patient_age"],
            "compositional": ["marker_a", "marker_b"],
            "numeric_discrete": ["grade"],
            "excluded": ["study_uid", "series_uid", "accession_number", "first_file"],
        },
    }
    _dicom(out / "dicom")
    expected["dicom"] = {"patients": ["P900", "P901"], "series": 3, "folder": "dicom"}
    (out / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return plan


def _dicom(root: Path) -> None:
    """A small DICOM source for `dicom.convert` and Open mode (SRC-13): 2 patients, 3 series."""
    from tools.dicom_fixtures import write_series

    info = write_series(root / "P900" / "ct_np", patient_id="P900", seed="fx")
    write_series(
        root / "P900" / "scout", patient_id="P900", description="SCOUT", shape=(12, 10, 3),
        study_uid=info["study_uid"], series_number=9, seed="fx",
    )  # fmt: skip
    write_series(root / "P901" / "ct_nc", patient_id="P901", description="NON CONTRAST", seed="fx")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--out", type=Path, default=Path("../.fixtures/synthetic"))
    args = ap.parse_args()
    generate(args.out)
    print(f"fixtures -> {args.out.resolve()}  digest {tree_digest(args.out)[:12]}")


if __name__ == "__main__":
    main()
