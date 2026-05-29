from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.models.workspace import WorkspaceStatus
from app.services.state_dir import dataset_state_dir


class WorkspaceStore:
    def __init__(self, path: Path | None = None):
        self.path = path or self._default_path()

    def get(self) -> WorkspaceStatus:
        payload = self._load_payload()
        dataset_path = payload.get("dataset_path")
        if not dataset_path:
            return WorkspaceStatus(configured=False)

        resolved = Path(dataset_path).expanduser().resolve()
        database_csv_path = payload.get("database_csv_path")
        resolved_database = (
            Path(database_csv_path).expanduser().resolve()
            if database_csv_path
            else None
        )
        return WorkspaceStatus(
            configured=True,
            dataset_id=resolved.name,
            dataset_path=str(resolved),
            database_csv_path=str(resolved_database) if resolved_database else None,
            workspace_dir=str(dataset_state_dir(resolved)),
        )

    def set(self, dataset_path: Path, database_csv_path: Path | None = None) -> WorkspaceStatus:
        resolved = dataset_path.expanduser().resolve()
        payload = {"dataset_path": str(resolved)}
        if database_csv_path is not None:
            payload["database_csv_path"] = str(database_csv_path.expanduser().resolve())
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with NamedTemporaryFile(
                "w",
                dir=self.path.parent,
                prefix=self.path.stem + ".",
                suffix=".tmp",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temp_path = Path(handle.name)
            temp_path.replace(self.path)
        except OSError as exc:
            raise RuntimeError(f"Unable to write workspace file '{self.path}'") from exc

        return self.get()

    def clear(self) -> WorkspaceStatus:
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError as exc:
            raise RuntimeError(f"Unable to clear workspace file '{self.path}'") from exc
        return WorkspaceStatus(configured=False)

    def _load_payload(self) -> dict[str, str]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Workspace file '{self.path}' is not valid JSON") from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to read workspace file '{self.path}'") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Workspace file '{self.path}' must contain a JSON object")
        return payload

    @staticmethod
    def _default_path() -> Path:
        home_path = Path.home() / ".radiology-webui" / "workspace.json"
        if SettingsFilesystem._is_writable(home_path.parent):
            return home_path
        return Path("/tmp/radiology-webui/workspace.json")


class SettingsFilesystem:
    @staticmethod
    def _is_writable(directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False


workspace_store = WorkspaceStore()
