"""Synthetic DICOM series for TST-13 (orientation), the converter tests (DCM-*) and the fixtures.

`write_series` writes an axial CT series (LPS patient coordinates, as in DICOM) with one bright
marker voxel at a known (column, row, slice), so a converted NIfTI can be checked in RAS mm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, CTImageStorage, ExplicitVRLittleEndian, generate_uid

MARKER = 2000


def _uid(seed: str | None, *parts: str) -> UID:
    """Random UIDs, or deterministic ones for a seed (TST-11 fixtures are reproducible)."""
    return generate_uid() if seed is None else generate_uid(entropy_srcs=[seed, *parts])


def _ds(
    *,
    patient_id: str,
    study_uid: str,
    series_uid: str,
    series_number: int,
    description: str,
    seed: str | None,
    k: int,
    rows: int,
    cols: int,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float],
    modality: str,
    extra: dict[str, Any],
) -> Dataset:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = _uid(seed, series_uid, str(k))
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientID = patient_id
    ds.PatientName = f"Doe^{patient_id}"
    ds.PatientBirthDate = "19600101"
    ds.InstitutionName = "Test Hospital"
    ds.AccessionNumber = "ACC123"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = k + 1
    ds.Modality = modality
    ds.StudyDate = ds.SeriesDate = ds.AcquisitionDate = "20240102"
    ds.StudyTime = "100000"
    ds.SeriesTime = ds.AcquisitionTime = "100100"
    ds.StudyDescription = "CT ABDOMEN KIDNEY"
    ds.SeriesDescription = description
    ds.BodyPartExamined = "ABDOMEN"
    ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [origin[0], origin[1], origin[2] + k * spacing[2]]
    ds.PixelSpacing = [spacing[1], spacing[0]]  # row spacing (y), column spacing (x)
    ds.SliceThickness = spacing[2]
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation = 1
    ds.RescaleIntercept, ds.RescaleSlope = 0, 1
    for key, value in extra.items():
        setattr(ds, key, value)
    return ds


def write_series(
    folder: Path,
    *,
    patient_id: str = "P001",
    description: str = "NEPHROGRAPHIC PHASE",
    shape: tuple[int, int, int] = (12, 10, 14),  # (columns x, rows y, slices z)
    spacing: tuple[float, float, float] = (0.7, 0.9, 2.5),
    origin: tuple[float, float, float] = (-20.0, -30.0, 100.0),
    marker: tuple[int, int, int] = (2, 7, 9),  # (column i, row j, slice k)
    modality: str = "CT",
    study_uid: str | None = None,
    series_number: int = 3,
    extra: dict[str, Any] | None = None,
    seed: str | None = None,
) -> dict[str, Any]:
    """One file per slice; returns the marker's LPS position in mm and the series UID."""
    folder.mkdir(parents=True, exist_ok=True)
    cols, rows, n = shape
    study_uid = study_uid or _uid(seed, patient_id, "study")
    series_uid = _uid(seed, patient_id, description, str(series_number))
    for k in range(n):
        ds = _ds(
            patient_id=patient_id, study_uid=study_uid, series_uid=series_uid,
            series_number=series_number, description=description, seed=seed, k=k, rows=rows,
            cols=cols, spacing=spacing, origin=origin, modality=modality, extra=extra or {},
        )  # fmt: skip
        px = np.full((rows, cols), -100, np.int16)
        if k == marker[2]:
            px[marker[1], marker[0]] = MARKER
        ds.PixelData = px.tobytes()
        ds.save_as(folder / f"IM{k:04d}.dcm", enforce_file_format=True)
    lps = (
        origin[0] + marker[0] * spacing[0],
        origin[1] + marker[1] * spacing[1],
        origin[2] + marker[2] * spacing[2],
    )
    return {"series_uid": series_uid, "study_uid": study_uid, "marker_lps": lps}
