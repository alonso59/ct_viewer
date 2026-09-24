"""DICOM JSON Model sidecars (DCM-04, PS3.18 §F.2) and `anonymize: basic` (DCM-05, NFR-17).

A sidecar holds every header attribute except PixelData; bulk values over 64 KiB are omitted
and listed in `_omitted`. `basic` applies a subset of the PS3.15 Basic Application Level
Confidentiality Profile (Table E.1-1): identifying attributes removed, private tags removed,
UIDs replaced by deterministic `2.25.` UIDs, and `patient_id` replaced by the `case_id`.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

BULK_LIMIT = 64 * 1024
# PS3.15 E.1-1 attributes (X/Z/D actions) that identify people, places or dates.
BASIC_PROFILE = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientSex",
    "PatientAge",
    "PatientSize",
    "PatientWeight",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientMotherBirthName",
    "OtherPatientIDs",
    "OtherPatientIDsSequence",
    "OtherPatientNames",
    "PatientBirthName",
    "MilitaryRank",
    "BranchOfService",
    "EthnicGroup",
    "Occupation",
    "AdditionalPatientHistory",
    "PatientComments",
    "MedicalRecordLocator",
    "PatientReligiousPreference",
    "PregnancyStatus",
    "ResponsiblePerson",
    "ResponsibleOrganization",
    "AccessionNumber",
    "StudyID",
    "IssuerOfPatientID",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "InstitutionCodeSequence",
    "ReferringPhysicianName",
    "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    "ReferringPhysicianIdentificationSequence",
    "PerformingPhysicianName",
    "PerformingPhysicianIdentificationSequence",
    "NameOfPhysiciansReadingStudy",
    "PhysiciansOfRecord",
    "PhysiciansOfRecordIdentificationSequence",
    "OperatorsName",
    "OperatorIdentificationSequence",
    "RequestingPhysician",
    "RequestingService",
    "ScheduledPerformingPhysicianName",
    "StationName",
    "DeviceSerialNumber",
    "PlateID",
    "DetectorID",
    "StudyDate",
    "StudyTime",
    "SeriesDate",
    "SeriesTime",
    "AcquisitionDate",
    "AcquisitionTime",
    "AcquisitionDateTime",
    "ContentDate",
    "ContentTime",
    "InstanceCreationDate",
    "InstanceCreationTime",
    "OverlayDate",
    "OverlayTime",
    "CurveDate",
    "CurveTime",
    "PerformedProcedureStepStartDate",
    "PerformedProcedureStepStartTime",
    "PerformedProcedureStepEndDate",
    "PerformedProcedureStepEndTime",
    "PerformedProcedureStepID",
    "RequestedProcedureID",
    "ScheduledProcedureStepID",
    "AdmissionID",
    "AdmittingDiagnosesDescription",
    "RequestAttributesSequence",
    "ReferencedPatientSequence",
    "ReferencedStudySequence",
    "ReferencedPerformedProcedureStepSequence",
    "ImageComments",
    "StudyComments",
    "InterpretationText",
    "TextString",
    "TextComments",
    "FrameComments",
    "ProtocolName",
    "PerformedProcedureStepDescription",
    "DerivationDescription",
    "ContrastBolusStartTime",
    "ContrastBolusStopTime",
    "ContentCreatorName",
    "ScheduledProcedureStepStartDate",
)
UID_KEYWORDS = (
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "MediaStorageSOPInstanceUID",
    "FrameOfReferenceUID",
    "ReferencedSOPInstanceUID",
    "SynchronizationFrameOfReferenceUID",
    "IrradiationEventUID",
    "StorageMediaFileSetUID",
)
# Row fields (DICOM_CONVERTER.md §Row fields) derived from Basic Profile attributes.
ROW_PHI = (
    "patient_folder",
    "institution",
    "study_date",
    "study_time",
    "series_date",
    "series_time",
    "acquisition_date",
    "acquisition_time",
    "content_date",
    "content_time",
    "scan_date",
    "scan_time",
    "scan_datetime",
    "contrast_start_time",
    "contrast_stop_time",
    "protocol_name",
)


def anon_uid(uid: str, salt: str) -> str:
    """Deterministic replacement UID (`2.25.` + UUID5), so reruns keep series identity."""
    return f"2.25.{uuid.uuid5(uuid.NAMESPACE_OID, f'{salt}|{uid}').int}"


def anonymize_dataset(ds: Any, case_id: str, salt: str) -> Any:
    out = ds.copy()
    out.remove_private_tags()
    for kw in BASIC_PROFILE:
        if kw in out:
            delattr(out, kw)
    for kw in UID_KEYWORDS:
        if kw in out:
            setattr(out, kw, anon_uid(str(getattr(out, kw)), salt))
    out.PatientID = case_id
    out.PatientName = case_id
    out.PatientIdentityRemoved = "YES"
    out.DeidentificationMethod = "rw basic (PS3.15 E.1-1 subset)"
    return out


def anonymize_row(row: dict[str, Any], case_id: str, salt: str) -> None:
    for key in ROW_PHI:
        if key in row:
            row[key] = ""
    row["patient_id"] = case_id
    for key in ("study_uid", "series_uid"):
        if row.get(key):
            row[key] = anon_uid(str(row[key]), salt)
    row["anonymized"] = "basic"


def to_json_model(ds: Any) -> dict[str, Any]:
    """DICOM JSON Model without PixelData; bulk values > 64 KiB omitted (`_omitted` lists tags)."""
    omitted: list[str] = []

    def bulk(elem: Any) -> str:
        omitted.append(f"{elem.tag.group:04X}{elem.tag.element:04X}")
        return ""

    clean = ds.copy()
    if "PixelData" in clean:
        del clean.PixelData
    model: dict[str, Any] = clean.to_json_dict(
        bulk_data_threshold=BULK_LIMIT, bulk_data_element_handler=bulk
    )
    for tag in omitted:
        model.pop(tag, None)
    model["_omitted"] = sorted(omitted)
    return model


def write_sidecar(ds: Any, out: Path) -> str:
    """Write once (never rewritten); returns the sha256."""
    data = (json.dumps(to_json_model(ds), ensure_ascii=False, sort_keys=True) + "\n").encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return hashlib.sha256(data).hexdigest()
