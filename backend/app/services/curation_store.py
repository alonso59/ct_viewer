from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
import uuid

from app.models.curation import (
    CURATION_FIELDS,
    CorrectionQueueResponse,
    CurationDecision,
    CurationDecisionRequest,
    PhaseCorrectionRequest,
    PhaseCorrectionResponse,
)
from app.services.database import get_database_index
from app.services.state_dir import dataset_state_file


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = Lock()


def get_curation_history(dataset_path: Path | str, dataset_id: str, case_id: str) -> list[CurationDecision]:
    return [
        decision
        for decision in _read_decisions(_review_path(dataset_path, dataset_id, create=False))
        if decision.case_id == case_id
    ]


def save_curation_decision(
    dataset_path: Path | str,
    dataset_id: str,
    payload: CurationDecisionRequest,
) -> CurationDecision:
    dataset = Path(dataset_path).expanduser().resolve()
    lock = _dataset_lock(dataset_id)
    with lock:
        decision = _build_decision(dataset, dataset_id, payload)
        review_path = _review_path(dataset, dataset_id, create=True)
        decisions = _read_decisions(review_path)
        decisions.append(decision)
        _write_decisions(review_path, decisions)

        if payload.add_to_queue:
            queue_path = _queue_path(dataset, dataset_id, create=True)
            queue = _read_decisions(queue_path)
            queue.append(decision)
            _write_decisions(queue_path, queue)
        return decision


def list_correction_queue(dataset_path: Path | str, dataset_id: str) -> CorrectionQueueResponse:
    return CorrectionQueueResponse(
        dataset_id=dataset_id,
        items=_read_decisions(_queue_path(dataset_path, dataset_id, create=False)),
    )


def save_phase_correction(
    dataset_path: Path | str,
    dataset_id: str,
    payload: PhaseCorrectionRequest,
) -> PhaseCorrectionResponse:
    """Record a phase-correction proposal for every scope of every row that shares
    the given case_id + scan_idx.  For each matching DatabaseRow, one decision is
    created per available scope (complete and/or VOI).
    """
    from app.services.path_resolver import path_exists as _path_exists

    dataset = Path(dataset_path).expanduser().resolve()
    lock = _dataset_lock(dataset_id)

    with lock:
        index = get_database_index(dataset)

        matching = [
            row
            for row in index.rows
            if row.case_id == payload.case_id
            and (payload.scan_idx is None or row.scan_idx == payload.scan_idx)
        ]

        now = datetime.now(timezone.utc).isoformat()
        decisions: list[CurationDecision] = []

        for row in matching:
            has_complete = _path_exists(row.nifti_path)
            has_voi = _path_exists(row.voi_image_path)

            for scope, present in (("complete", has_complete), ("voi", has_voi)):
                if not present:
                    continue
                decisions.append(
                    CurationDecision(
                        review_id=uuid.uuid4().hex,
                        dataset_id=dataset_id,
                        case_id=row.case_id,
                        patient_id=row.patient_id,
                        source_row_id=row.source_row_id,
                        row_id=row.row_id,
                        scan_idx=row.scan_idx,
                        raw_phase=row.raw_phase,
                        canonical_phase=row.canonical_phase,
                        proposed_phase=payload.proposed_phase.strip() or None,
                        side=row.side,
                        scope=scope,  # type: ignore[arg-type]
                        target="phase_issue",
                        status="wrong_phase_suspected",
                        priority="medium",
                        comment=payload.comment.strip(),
                        reviewer=payload.reviewer.strip(),
                        reviewed_at=now,
                        nifti_path=row.nifti_path.resolved if row.nifti_path.resolved else None,
                        seg_path=row.seg_path.resolved if row.seg_path.resolved else None,
                        voi_image_path=row.voi_image_path.resolved if row.voi_image_path.resolved else None,
                        voi_mask_path=row.voi_mask_path.resolved if row.voi_mask_path.resolved else None,
                    )
                )

        if decisions:
            review_path = _review_path(dataset, dataset_id, create=True)
            existing = _read_decisions(review_path)
            existing.extend(decisions)
            _write_decisions(review_path, existing)

            if payload.add_to_queue:
                queue_path = _queue_path(dataset, dataset_id, create=True)
                queue = _read_decisions(queue_path)
                queue.extend(decisions)
                _write_decisions(queue_path, queue)

        complete_rows = sum(1 for d in decisions if d.scope == "complete")
        voi_rows = sum(1 for d in decisions if d.scope == "voi")

        return PhaseCorrectionResponse(
            case_id=payload.case_id,
            scan_idx=payload.scan_idx,
            proposed_phase=payload.proposed_phase.strip(),
            total_rows=len(decisions),
            complete_rows=complete_rows,
            voi_rows=voi_rows,
            decisions=decisions,
        )


def correction_queue_csv(dataset_path: Path | str, dataset_id: str) -> str:
    queue = _read_decisions(_queue_path(dataset_path, dataset_id, create=False))
    output: list[str] = []
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CURATION_FIELDS)
    writer.writeheader()
    for decision in queue:
        writer.writerow(_decision_to_row(decision))
    output.append(buffer.getvalue())
    return "".join(output)


def latest_case_status_map(dataset_path: Path | str, dataset_id: str) -> dict[str, tuple[str, bool]]:
    latest: dict[str, CurationDecision] = {}
    for decision in _read_decisions(_review_path(dataset_path, dataset_id, create=False)):
        current = latest.get(decision.case_id)
        if current is None or decision.reviewed_at > current.reviewed_at:
            latest[decision.case_id] = decision
    return {
        case_id: (decision.status, bool(decision.comment.strip()))
        for case_id, decision in latest.items()
    }


def latest_row_status_map(dataset_path: Path | str, dataset_id: str) -> dict[str, str]:
    latest: dict[str, CurationDecision] = {}
    for decision in _read_decisions(_review_path(dataset_path, dataset_id, create=False)):
        if not decision.row_id:
            continue
        current = latest.get(decision.row_id)
        if current is None or decision.reviewed_at > current.reviewed_at:
            latest[decision.row_id] = decision
    return {row_id: decision.status for row_id, decision in latest.items()}


def _build_decision(
    dataset_path: Path,
    dataset_id: str,
    payload: CurationDecisionRequest,
) -> CurationDecision:
    row = None
    if payload.row_id:
        row = next(
            (
                candidate
                for candidate in get_database_index(dataset_path).rows
                if candidate.case_id == payload.case_id and candidate.row_id == payload.row_id
            ),
            None,
        )
    elif payload.case_id:
        row = next(
            (candidate for candidate in get_database_index(dataset_path).rows if candidate.case_id == payload.case_id),
            None,
        )

    return CurationDecision(
        review_id=uuid.uuid4().hex,
        dataset_id=dataset_id,
        case_id=payload.case_id,
        patient_id=row.patient_id if row else None,
        source_row_id=row.source_row_id if row else None,
        row_id=row.row_id if row else payload.row_id,
        scan_idx=row.scan_idx if row else None,
        raw_phase=row.raw_phase if row else None,
        canonical_phase=row.canonical_phase if row else None,
        proposed_phase=(payload.proposed_phase or "").strip() or None,
        side=row.side if row else None,
        scope=payload.scope,
        target=payload.target,
        status=payload.status,
        priority=payload.priority,
        comment=payload.comment.strip(),
        reviewer=payload.reviewer.strip(),
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        nifti_path=row.nifti_path.resolved if row and row.nifti_path.resolved else None,
        seg_path=row.seg_path.resolved if row and row.seg_path.resolved else None,
        voi_image_path=row.voi_image_path.resolved if row and row.voi_image_path.resolved else None,
        voi_mask_path=row.voi_mask_path.resolved if row and row.voi_mask_path.resolved else None,
    )


def _read_decisions(path: Path) -> list[CurationDecision]:
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                CurationDecision.model_validate(_normalize_row(row))
                for row in csv.DictReader(handle)
            ]
    except OSError as exc:
        raise RuntimeError(f"Unable to read curation file '{path}'") from exc


def _write_decisions(path: Path, decisions: list[CurationDecision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=path.stem + ".",
            suffix=".tmp",
            encoding="utf-8",
            newline="",
            delete=False,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=CURATION_FIELDS)
            writer.writeheader()
            for decision in decisions:
                writer.writerow(_decision_to_row(decision))
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        raise RuntimeError(f"Unable to write curation file '{path}'") from exc


def _decision_to_row(decision: CurationDecision) -> dict[str, str]:
    dumped = decision.model_dump(mode="json")
    return {field: "" if dumped.get(field) is None else str(dumped.get(field, "")) for field in CURATION_FIELDS}


def _normalize_row(row: dict[str, str | None]) -> dict[str, str | None]:
    optional_fields = {
        "patient_id",
        "source_row_id",
        "row_id",
        "scan_idx",
        "raw_phase",
        "canonical_phase",
        "proposed_phase",
        "side",
        "nifti_path",
        "seg_path",
        "voi_image_path",
        "voi_mask_path",
    }
    return {
        key: (None if key in optional_fields and value == "" else value)
        for key, value in row.items()
    }


def _review_path(dataset_path: Path | str, dataset_id: str, *, create: bool) -> Path:
    return dataset_state_file(dataset_path, "curation_review.csv", dataset_id, create=create)


def _queue_path(dataset_path: Path | str, dataset_id: str, *, create: bool) -> Path:
    return dataset_state_file(dataset_path, "correction_queue.csv", dataset_id, create=create)


def _dataset_lock(dataset_id: str) -> RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(dataset_id)
        if lock is None:
            lock = RLock()
            _LOCKS[dataset_id] = lock
        return lock
