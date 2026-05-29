from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.database import (
    CaseDossier,
    CaseInventoryRow,
    CaseSummary,
    DatabaseValidationReport,
    Scope,
)
from app.models.dataset import VolumeInfo
from app.services.curation_store import latest_case_status_map, latest_row_status_map
from app.services.database import (
    get_case_dossier,
    get_case_load_source,
    has_database,
    list_case_inventory,
    list_case_summaries,
    normalize_phase,
)
from app.services.discovery import discover_patients
from app.services.qc_validator import validate_database
from app.services.volume_cache import volume_cache
from app.services.workspace import validate_workspace_dataset_id


router = APIRouter(tags=["cases"])


def _dataset_path(dataset_id: str):
    try:
        return validate_workspace_dataset_id(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected case API error")


@router.get(
    "/api/datasets/{dataset_id}/database/validation",
    response_model=DatabaseValidationReport,
)
def database_validation(dataset_id: str) -> DatabaseValidationReport:
    try:
        return validate_database(_dataset_path(dataset_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/api/datasets/{dataset_id}/cases", response_model=list[CaseSummary])
def cases(dataset_id: str) -> list[CaseSummary]:
    dataset_path = _dataset_path(dataset_id)
    try:
        if has_database(dataset_path):
            summaries = list_case_summaries(dataset_path)
        else:
            summaries = _legacy_case_summaries(dataset_path)
        latest = latest_case_status_map(dataset_path, dataset_id)
        return [
            summary.model_copy(
                update={
                    "latest_curation_status": latest.get(summary.case_id, (None, False))[0],
                    "has_comments": latest.get(summary.case_id, (None, False))[1],
                }
            )
            for summary in summaries
        ]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/api/datasets/{dataset_id}/cases/{case_id}/inventory",
    response_model=list[CaseInventoryRow],
)
def case_inventory(dataset_id: str, case_id: str) -> list[CaseInventoryRow]:
    dataset_path = _dataset_path(dataset_id)
    try:
        rows = list_case_inventory(dataset_path, case_id)
        if not rows:
            raise FileNotFoundError(f"Case '{case_id}' not found in database.csv")
        latest = latest_row_status_map(dataset_path, dataset_id)
        return [
            row.model_copy(update={"latest_curation_status": latest.get(row.row_id)})
            for row in rows
        ]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/api/datasets/{dataset_id}/cases/{case_id}/dossier",
    response_model=CaseDossier,
)
def case_dossier(dataset_id: str, case_id: str) -> CaseDossier:
    try:
        return get_case_dossier(_dataset_path(dataset_id), case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/api/datasets/{dataset_id}/cases/{case_id}/load",
    response_model=VolumeInfo,
)
def load_case_source(
    dataset_id: str,
    case_id: str,
    row_id: str = Query(...),
    scope: Scope = Query(default="complete"),
) -> VolumeInfo:
    try:
        source = get_case_load_source(_dataset_path(dataset_id), case_id, row_id, scope)
        return volume_cache.load_case_source(
            dataset_id=dataset_id,
            case_id=case_id,
            series_id=source.series_id,
            image_path=source.image_path,
            mask_path=source.mask_path,
            source_type=source.source_type,
            cache_key_suffix=f"{source.scope}:{source.row_id}",
            spacing_override=source.spacing,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


def _legacy_case_summaries(dataset_path) -> list[CaseSummary]:
    summaries: list[CaseSummary] = []
    for patient in discover_patients(dataset_path):
        phases = [
            normalize_phase(phase)[0]
            for phase in patient.phases
        ]
        summaries.append(
            CaseSummary(
                case_id=patient.patient_id,
                patient_id=patient.source_patient_id or patient.patient_id,
                group=patient.group,
                available_phases=list(dict.fromkeys(phases)),
                scan_count=patient.series_count,
                seg_count=patient.seg_count,
                voi_image_count=patient.voi_count,
                voi_mask_count=patient.voi_count,
            )
        )
    return summaries
