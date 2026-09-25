"""Reconstructed DICOM sidecars for `metadata-v1` imports (IMP-15, ADR-0025 §2).

Opt-in per import (`options.reconstruct_sidecars`). For each scan whose row has no resolvable
`dicom_sidecar`, the DICOM-shaped fields the row already carries are mapped to a DICOM JSON
Model (PS3.18 §F.2), the shape of a real DCM-04 sidecar, marked `_provenance: {fidelity:
"partial"}`. A real sidecar always wins. Files go to the project's derived root only (DCM-05, R1):
`{DERIVED}/{project}/imports/{import_id}/sidecars/{name}.dicom.json`; the planning runs where the
index is prepared, the writing in job workers (BE-12). Patient-identifying fields are not mapped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.core.errors import Problem
from app.core.fsio import atomic_write_json
from app.core.paths import PathResolver
from app.ingest.normalize import Draft
from app.projects.models import PathRoot

OPTION: Final = "reconstruct_sidecars"
SOURCE: Final = "metadata-v1-import"

# flat row field → (DICOM tag, VR): DICOM_CONVERTER §Row fields extras that have a header home
TAGS: Final[dict[str, tuple[str, str]]] = {
    "image_type": ("00080008", "CS"),
    "sop_class_uid": ("00080016", "UI"),
    "study_date": ("00080020", "DA"),
    "series_date": ("00080021", "DA"),
    "acquisition_date": ("00080022", "DA"),
    "content_date": ("00080023", "DA"),
    "study_time": ("00080030", "TM"),
    "series_time": ("00080031", "TM"),
    "acquisition_time": ("00080032", "TM"),
    "modality": ("00080060", "CS"),
    "manufacturer": ("00080070", "LO"),
    "institution": ("00080080", "LO"),
    "study_description": ("00081030", "LO"),
    "series_description": ("0008103E", "LO"),
    "manufacturer_model": ("00081090", "LO"),
    "contrast_agent": ("00180010", "LO"),
    "body_part": ("00180015", "CS"),
    "scanning_sequence": ("00180020", "CS"),
    "sequence_variant": ("00180021", "CS"),
    "slice_thickness": ("00180050", "DS"),
    "kvp": ("00180060", "DS"),
    "repetition_time": ("00180080", "DS"),
    "echo_time": ("00180081", "DS"),
    "magnetic_field_strength": ("00180087", "DS"),
    "spacing_between_slices": ("00180088", "DS"),
    "protocol_name": ("00181030", "LO"),
    "exposure_time": ("00181150", "IS"),
    "xray_tube_current": ("00181151", "IS"),
    "exposure": ("00181152", "IS"),
    "convolution_kernel": ("00181210", "SH"),
    "flip_angle": ("00181314", "DS"),
    "study_uid": ("0020000D", "UI"),
    "series_uid": ("0020000E", "UI"),
    "series_number": ("00200011", "IS"),
    "acquisition_number": ("00200012", "IS"),
    "number_of_frames": ("00280008", "IS"),
    "window_center": ("00281050", "DS"),
    "window_width": ("00281051", "DS"),
    "rescale_intercept": ("00281052", "DS"),
    "rescale_slope": ("00281053", "DS"),
    "rescale_type": ("00281054", "LO"),
}
_EXT = re.compile(r"\.(nii\.gz|nii|npy)$", re.IGNORECASE)

Spec = tuple[str, dict[str, Any]]  # (absolute path, DICOM JSON Model)


def _value(vr: str, raw: Any) -> Any | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if vr in ("DS", "IS"):
        try:
            x = float(str(raw).replace(",", "."))
        except ValueError:
            return None
        return int(x) if vr == "IS" or x.is_integer() else x
    if vr == "DA":
        digits = re.sub(r"\D", "", str(raw))[:8]
        return digits if len(digits) == 8 else None
    if vr == "TM":
        return re.sub(r"[^\d.]", "", str(raw)) or None
    return str(raw)


def json_model(fields: dict[str, Any], generated_at: str) -> dict[str, Any] | None:
    """The row's DICOM-shaped fields as a DICOM JSON Model; None when there is none."""
    model: dict[str, Any] = {}
    for name, (tag, vr) in TAGS.items():
        raw = fields.get(name)
        vals = [_value(vr, v) for v in (raw if isinstance(raw, list) else [raw])]
        vals = [v for v in vals if v is not None]
        if vals:
            model[tag] = {"vr": vr, "Value": vals}
    if not model:
        return None
    model["_provenance"] = {"source": SOURCE, "fidelity": "partial", "generated_at": generated_at}
    model["_omitted"] = [
        "Reconstructed from an already-flattened metadata.jsonl row, not a DICOM header: only "
        "the fields that row carried are here (ADR-0025)."
    ]
    return model


def _resolves(resolver: PathResolver, ref: Any) -> bool:
    if not isinstance(ref, str) or not ref:
        return False
    try:
        return resolver.resolve(ref).is_file()
    except (Problem, ValueError, OSError):
        return False


def plan(
    drafts: Sequence[Draft],
    resolver: PathResolver,
    root: PathRoot,
    project_id: str,
    import_id: str,
    generated_at: str,
) -> list[Spec]:
    """Give every draft of a scan without a real sidecar a `dicom_sidecar` ref to its
    reconstructed one; returns the files the workers write. Drafts are updated in place."""
    rel_dir = f"{project_id}/imports/{import_id}/sidecars"
    by_scan: dict[tuple[str, str], str | None] = {}
    specs: list[Spec] = []
    for d in sorted(drafts, key=lambda x: x.scope != "complete"):  # the scan's own row first
        key = (d.case_id, d.scan_idx)
        if key not in by_scan:
            by_scan[key] = None
            if _resolves(resolver, d.extra.get("dicom_sidecar")):
                continue  # a real sidecar always wins (IMP-15)
            model = json_model({"modality": d.modality, **d.extra}, generated_at)
            if model is None:
                continue
            base = d.image.ref.rsplit("/", 1)[-1].split(":")[-1] if d.image and d.image.ref else ""
            name = _EXT.sub("", base) or f"{d.case_id}_{d.scan_idx}"
            rel = f"{rel_dir}/{name}.dicom.json"
            by_scan[key] = f"{root.alias}:{rel}"
            specs.append((str(Path(root.path) / rel), model))
        ref = by_scan[key]
        if ref is not None and not _resolves(resolver, d.extra.get("dicom_sidecar")):
            d.extra = {**d.extra, "dicom_sidecar": ref}
    return specs


def write_batch(specs: Sequence[Spec]) -> list[Any]:
    """Worker unit: write the planned sidecars (deterministic, so a re-index rewrites the same
    bytes). Returns no probe results."""
    for path, model in specs:
        atomic_write_json(Path(path), model)
    return []
