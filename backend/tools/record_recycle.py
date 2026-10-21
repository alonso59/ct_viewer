"""Record CUR-16 / API-66 against a disposable dataset; leave the existing demo intact.

cd backend && .venv/bin/python -m tools.record_recycle
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tools.make_fixtures import generate
from tools.record_mock import API, OUT, Recorder, dump, redact, wait_jobs


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rw-recycle-record-") as folder:
        tmp = Path(folder)
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
            pid = client.post(
                f"{API}/projects", json={"name": "Recycle demo", "packs": ["ccrcc"]}
            ).json()["project_id"]
            base = f"{API}/projects/{pid}"
            pv = client.post(
                f"{base}/imports/preview", json={"root": str(data / "Dataset900")}
            ).json()
            client.post(f"{base}/imports", json={"preview_id": pv["preview_id"]})
            wait_jobs(client)
            rec = Recorder(client)
            url = f"{base}/items/case_00001.01.complete.-/recycle"
            plan = rec.get(url)
            rec.call(
                "POST", url, {"confirmed": True, "token": plan["token"]}, {"X-Reviewer": "Dr. AP"}
            )
        recording = json.loads(OUT.read_text())
        paths = {e["path"].replace(pid, recording["project_id"]) for e in rec.log.values()}
        recording["exchanges"] = [e for e in recording["exchanges"] if e["path"] not in paths]
        recording["exchanges"] += json.loads(
            redact(dump(list(rec.log.values())), pid, data, workspace, derived, plugins)
        )
        exchanges = recording.pop("exchanges")
        rows = ",\n".join(dump(e) for e in exchanges)
        OUT.write_text(f'{dump(recording)[:-1]},"exchanges":[\n{rows}\n]}}\n')
        print(f"Recorded {len(rec.log)} recycle exchanges")


if __name__ == "__main__":
    main()
