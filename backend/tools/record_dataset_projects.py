"""Record PRJ-19 create/open exchanges against a disposable dataset, preserving the demo."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tools.make_fixtures import generate
from tools.record_mock import API, OUT, Recorder, dump, redact


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rw-project-record-") as scratch:
        tmp = Path(scratch)
        data, workspace, derived, plugins = (
            tmp / n for n in ("data", "workspace", "derived", "plugins")
        )
        generate(data)
        derived.mkdir()
        plugins.mkdir()
        settings = Settings(
            workspace_root=workspace,
            allowed_data_roots=str(data),
            allowed_derived_roots=str(derived),
            plugins_root=plugins,
            _env_file=None,
        )  # type: ignore[call-arg]
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            rec = Recorder(client)
            root = str(data / "Dataset900")
            result = rec.call(
                "POST",
                f"{API}/projects",
                {
                    "name": "Dataset project",
                    "description": "",
                    "default_modality": "CT",
                    "dataset_root": root,
                },
            )
            rec.call("POST", f"{API}/projects/open", {"dataset_root": root})
            pid = result["project_id"]
        recording = json.loads(OUT.read_text())
        additions = json.loads(
            redact(dump(list(rec.log.values())), pid, data, workspace, derived, plugins)
        )
        keys = {(e["method"], e["path"], dump(e["body"])) for e in additions}
        exchanges = [
            e
            for e in recording.pop("exchanges")
            if (e["method"], e["path"], dump(e["body"])) not in keys
        ] + additions
        rows = ",\n".join(dump(e) for e in exchanges)
        OUT.write_text(f'{dump(recording)[:-1]},"exchanges":[\n{rows}\n]}}\n')
        print("Recorded dataset project create/open")


if __name__ == "__main__":
    main()
