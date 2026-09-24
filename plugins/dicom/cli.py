"""Standalone converter CLI (DCM-09): the legacy YAML config, its own resume registry and
`curation.csv`; its output folder is imported into the app as a `source` root (metadata-v1).

    python -m plugins.dicom.cli config/converter.yaml
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

from plugins.dicom import pipeline
from plugins.dicom.identity import Identity

CURATION_COLUMNS = [
    "case_id", "scan_idx", "patient_id", "patient_folder", "filename", "modality", "scan_date",
    "series_description", "protocol_name", "dicom_category", "scan_type", "include_guess",
    "output_role", "exclude_reason", "curated_keep", "curated_role", "curated_phase",
    "curated_quality", "notes",
]  # fmt: skip
MANUAL = ("curated_keep", "curated_role", "curated_phase", "curated_quality", "notes")


def load(path: Path) -> dict[str, Any]:
    import yaml  # the CLI keeps the legacy YAML format (PyYAML is a CLI-only dependency)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    return raw


def main(argv: list[str]) -> int:
    cfg = load(Path(argv[0] if argv else "config/converter.yaml"))
    source = Path(cfg["dataset_root"])
    out = Path(cfg["output_root"])
    conv = cfg.get("conversion") or {}
    outs = cfg.get("outputs") or {}
    settings = pipeline.Settings(
        target_profile=str(cfg.get("target_profile") or "generic"),
        convert_primary=bool(conv.get("convert_primary", True)),
        convert_secondary=bool(conv.get("convert_secondary", True)),
        convert_excluded=bool(conv.get("convert_excluded", False)),
        skip_unsafe_geometry=bool(conv.get("skip_unsafe_geometry", False)),
        mixed_folder_policy=str(cfg.get("mixed_folder_policy") or "split"),
        patient_pattern=str(cfg.get("patient_pattern") or "*"),
        patient_limit=cfg.get("patient_limit"),
        include_modality_prefix=bool(outs.get("include_modality_prefix", True)),
        phase_vocabulary=["NC", "CMP", "NP", "EP", "UNK"],
    )
    registry_path = out / ".rw_identity.json"
    identity = Identity.from_dict(
        json.loads(registry_path.read_text()) if registry_path.is_file() else None
    )
    meta_path = out / str(outs.get("metadata_file") or "metadata.jsonl")
    previous = (
        [json.loads(x) for x in meta_path.read_text().splitlines() if x.strip()]
        if meta_path.is_file()
        else []
    )
    nifti = str(outs.get("nifti_dir") or "nifti")
    result = pipeline.run(
        source, settings, identity, nifti_dir=out / nifti, sidecar_dir=out / "sidecars", ref_rel="",
        ref_alias="DATA", salt="", previous=previous, dry_run=cfg.get("mode") == "dry_run",
    )  # fmt: skip
    for r in result.rows:  # contract v1 relative to the output folder (the imported root)
        r["relative_path"] = f"{nifti}/{r.get('filename', '')}"
        if r.get("dicom_sidecar"):
            r["dicom_sidecar"] = f"sidecars/{r['filename']}.dicom.json"
        # the CLI emits the legacy phase guess (the app uses analyzer annotations instead)
    phases = {a["item_id"]: a for a in result.annotations if a["field"] == "phase"}
    manual: dict[str, dict[str, str]] = {}
    cur_path = out / str(outs.get("curation_file") or "curation.csv")
    if cur_path.is_file():
        with cur_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                manual[f"{row.get('case_id')}|{row.get('scan_idx')}"] = {
                    k: row.get(k, "") for k in MANUAL
                }
    for r in result.rows:
        a = phases.get(f"{r.get('case_id')}.{r.get('scan_idx')}.complete.-")
        if a is not None:
            r["phase_guess"], r["phase_guess_confidence"], r["phase_guess_evidence"] = (
                a["value"],
                a["confidence"],
                a["evidence"],
            )
        r.update(
            {
                k: v
                for k, v in manual.get(f"{r.get('case_id')}|{r.get('scan_idx')}", {}).items()
                if v
            }
        )
    if cfg.get("mode") != "dry_run":
        pipeline.write_jsonl(meta_path, result.rows)
        registry_path.write_text(json.dumps(identity.as_dict(), indent=2))
        with cur_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CURATION_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in result.rows:
                w.writerow({c: r.get(c, "") for c in CURATION_COLUMNS})
    print(json.dumps({"counts": result.counts, "storage": result.storage}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
