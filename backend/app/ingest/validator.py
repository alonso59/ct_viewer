"""Validator: drafts + worker probe results → items and QC warnings (IMP-08, IMP-06)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.ids import utc_now
from app.imaging.header import compare_geometry
from app.ingest.codes import SEVERITY, QcCode
from app.ingest.indexer import FileProbe, FileResult, ItemProbe, ItemProbeResult
from app.ingest.models import Geometry, Item, QcWarning, VolumeRef
from app.ingest.normalize import Draft, FileDraft


def probes_for(drafts: Sequence[Draft]) -> list[ItemProbe]:
    """Worker inputs for every non-excluded draft with at least one resolved file."""
    out: list[ItemProbe] = []
    for d in drafts:
        if d.status == "excluded_upstream":
            continue
        img = FileProbe(d.image.path, d.spacing) if d.image and d.image.path else None
        msk = FileProbe(d.mask.path, d.spacing, labels=True) if d.mask and d.mask.path else None
        if img or msk:
            out.append(ItemProbe(d.item_id, img, msk))
    return out


def _ref(f: FileDraft, r: FileResult | None) -> VolumeRef | None:
    return VolumeRef(ref=f.ref, format=f.format, fp=r.fp if r else None) if f.ref else None


def finalize(
    drafts: Sequence[Draft],
    results: Mapping[str, ItemProbeResult],
    previous: Mapping[str, Item],
    import_id: str,
) -> tuple[list[Item], list[QcWarning]]:
    now = utc_now()
    items: list[Item] = []
    warnings: list[QcWarning] = []
    for d in drafts:
        item, ws = _finalize_one(d, results.get(d.item_id), previous.get(d.item_id), import_id, now)
        items.append(item)
        warnings += ws
    return items, warnings


def _finalize_one(
    d: Draft, res: ItemProbeResult | None, prev: Item | None, import_id: str, now: str
) -> tuple[Item, list[QcWarning]]:
    img_r, msk_r = (res.image, res.mask) if res else (None, None)
    warnings: list[QcWarning] = []

    def warn(code: QcCode, field: str | None, message: str, path_ref: str | None = None) -> None:
        warnings.append(
            QcWarning(
                code=code,
                severity=SEVERITY[code],
                item_id=d.item_id,
                case_id=d.case_id,
                field=field,
                path_ref=path_ref,
                message=message,
                detected_at=now,
            )
        )

    for p in d.warnings:
        warn(p.code, p.field, p.message, p.path_ref)
    status = d.status
    image = mask = None
    geometry = None
    labels: list[int] = []
    voi = d.scope == "voi"
    live = status != "excluded_upstream"
    if d.image is not None and live:
        image = _ref(d.image, img_r)
        if img_r is None or not img_r.exists:
            status = "missing"
            if voi:
                warn(QcCode.MISSING_VOI_IMAGE, "image", "VOI image missing", d.image.ref)
            else:
                warn(QcCode.MISSING_PATH, "image", "image file does not exist", d.image.ref)
        elif img_r.error:
            warn(QcCode.UNREADABLE_FILE, "image", img_r.error, d.image.ref)
        elif img_r.header is not None:
            geometry = Geometry(**img_r.header.geometry())
            if img_r.header.format == "nifti" and img_r.header.affine is None:
                warn(QcCode.MISSING_AFFINE, "image", "no usable affine", d.image.ref)
    if d.mask is not None and live:
        if msk_r is not None and msk_r.exists:
            mask = _ref(d.mask, msk_r)
            if msk_r.error:
                warn(QcCode.UNREADABLE_FILE, "mask", msk_r.error, d.mask.ref)
            elif msk_r.header is not None:
                labels = list(msk_r.labels)
                if img_r is not None and img_r.header is not None:
                    for issue in compare_geometry(img_r.header, msk_r.header):
                        code = QcCode.SHAPE_MISMATCH if issue == "shape" else QcCode.AFFINE_MISMATCH
                        warn(code, "mask", f"mask {issue} differs from image", d.mask.ref)
        elif voi:
            warn(QcCode.MISSING_VOI_MASK, "mask", "VOI mask missing", d.mask.ref)
        else:
            if d.mask.explicit:
                warn(QcCode.MISSING_PATH, "mask", "seg_path does not exist", d.mask.ref)
            warn(QcCode.MISSING_SEG, "mask", "scan has no SEG", d.mask.ref)
    if prev is not None:
        for role, new, old in (("image", image, prev.image), ("mask", mask, prev.mask)):
            if new and old and new.fp and old.fp and new.fp != old.fp and new.ref == old.ref:
                warn(QcCode.FINGERPRINT_CHANGED, role, f"{role} changed since last index", new.ref)
    item = Item(
        item_id=d.item_id,
        case_id=d.case_id,
        scan_idx=d.scan_idx,
        scope=d.scope,
        side=d.side,
        patient_id=d.patient_id,
        modality=d.modality,
        phase=d.phase,
        image=image,
        mask=mask,
        geometry=geometry,
        labels_present=labels,
        status=status,
        warning_codes=list(dict.fromkeys(w.code for w in warnings)),
        import_id=import_id,
        extra=d.extra,
    )
    return item, warnings
