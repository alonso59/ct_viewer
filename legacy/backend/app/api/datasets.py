from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.models.dataset import DatasetSummary, PatientSummary, SeriesInfo
from app.services.discovery import (
    discover_patients,
    discover_series,
    list_datasets,
)
from app.services.workspace import require_workspace_dataset_path, validate_workspace_dataset_id


router = APIRouter(tags=["datasets"])


def _dataset_path(dataset_id: str) -> Path:
    try:
        return validate_workspace_dataset_id(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/datasets", response_model=list[DatasetSummary])
def datasets() -> list[DatasetSummary]:
    try:
        dataset_path = require_workspace_dataset_path()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return list_datasets(dataset_path)


@router.get("/api/datasets/{dataset_id}/patients", response_model=list[PatientSummary])
def patients(dataset_id: str) -> list[PatientSummary]:
    return discover_patients(_dataset_path(dataset_id))


@router.get(
    "/api/datasets/{dataset_id}/patients/{patient_id}/series",
    response_model=list[SeriesInfo],
)
def series(dataset_id: str, patient_id: str) -> list[SeriesInfo]:
    return discover_series(_dataset_path(dataset_id), patient_id)
