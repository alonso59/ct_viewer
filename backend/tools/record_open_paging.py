"""TST-04/SRC-18: record actual later Open pages without changing the shared fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tools.dicom_fixtures import write_series
from tools.make_fixtures import _write_nifti
from tools.record_mock import API, OUT, Recorder, dump, redact

SID = "01JSYNTHOPENPAGING00000000"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rw-open-record-") as folder:
        root = Path(folder)
        data, workspace, derived, plugins = (
            root / name for name in ("data", "workspace", "derived", "plugins")
        )
        derived.mkdir()
        plugins.mkdir()
        affine = np.diag([0.8, 0.8, 1.5, 1.0])
        first = data / "images" / "0000.nii.gz"
        _write_nifti(first, np.arange(360, dtype=np.float32).reshape(8, 9, 5), affine)
        for n in range(1, 503):
            os.link(first, first.parent / f"{n:04}.nii.gz")
        write_series(first.parent / "dicom", shape=(3, 3, 3), marker=(1, 1, 2))
        masks = []
        for n in (1, 2):
            path = data / "masks" / f"mask{n}.nii.gz"
            pixels = np.zeros((8, 9, 5), dtype=np.uint8)
            pixels[2:4, 2:5, 1:3] = n
            _write_nifti(path, pixels, affine)
            masks.append(path)
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()
        }
        settings = Settings(
            workspace_root=workspace,
            allowed_data_roots=str(data),
            allowed_derived_roots=str(derived),
            plugins_root=plugins,
            job_workers=2,
            _env_file=None,
        )  # type: ignore[call-arg]
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            rec = Recorder(client, preserve_paging=True)
            opened = rec.call("POST", f"{API}/open", {"path": str(first.parent)})
            sid = opened["sid"]
            base = f"{API}/open/{sid}"
            for mask in masks:
                response = client.post(f"{base}/items/502/attach", json={"path": str(mask)})
                if response.status_code != 200:
                    raise SystemExit(f"record-open: attachment failed ({response.status_code})")
            rec.get(base)
            for offset in range(0, 504, 50):
                cursor = f"&cursor={offset}" if offset else ""
                rec.get(f"{base}/items?kind=image&limit=50{cursor}")
            for n in (0, 500, 501, 502, 503):
                rec.get(f"{base}?item={n}")
            rec.call(
                "POST",
                f"{base}/items/502/save",
                {"dest_dir": None, "sidecar": False, "anonymize": "none", "axis_order": None},
            )
            rec.call("POST", f"{API}/fs/list", {"path": None, "role": "derived"})
            for path in (data, first.parent, masks[0].parent):
                rec.call("POST", f"{API}/fs/list", {"path": str(path), "role": "source"})
        after = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()
        }
        if before != after:
            raise SystemExit("record-open: sources changed")
        text = redact(
            dump(list(rec.log.values())),
            "__no_project__",
            data,
            workspace,
            derived,
            plugins,
            data_alias="/open-data",
        ).replace(sid, SID)
        additions = json.loads(text)
        recording = json.loads(OUT.read_text())
        keys = {(e["method"], e["path"], e["query"], dump(e["body"])) for e in additions}
        recording["exchanges"] = [
            e
            for e in recording["exchanges"]
            if (e["method"], e["path"], e["query"], dump(e["body"])) not in keys
        ] + additions
        exchanges = recording.pop("exchanges")
        rows = ",\n".join(dump(e) for e in exchanges)
        OUT.write_text(f'{dump(recording)[:-1]},"exchanges":[\n{rows}\n]}}\n')
        print(f"Recorded 504 mixed Open items and {len(additions)} exchanges; sources unchanged")


if __name__ == "__main__":
    main()
