from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.models.workspace import DatasetKind, RecentDataset, WorkspaceStatus
from app.services.path_policy import dataset_key
from app.services.state_dir import dataset_state_dir


SCHEMA_VERSION = 2
MAX_RECENT_DATASETS = 5


class WorkspaceStore:
    def __init__(self, path: Path | None = None):
        self.path = path or self._default_path()

    def get(self) -> WorkspaceStatus:
        payload = self._normalized_payload(self._load_payload())
        recent = [RecentDataset.model_validate(item) for item in payload["recent_dataset_paths"]]
        active_path = payload.get("active_dataset_path")
        if not active_path:
            return WorkspaceStatus(configured=False, recent_datasets=recent)

        resolved = Path(str(active_path)).expanduser().resolve(strict=False)
        active_key = dataset_key(resolved)
        active_recent = next((item for item in recent if item.dataset_key == active_key), None)
        active_kind = payload.get("active_dataset_kind") or (
            active_recent.dataset_kind if active_recent else None
        )
        return WorkspaceStatus(
            configured=True,
            dataset_id=resolved.name,
            dataset_key=active_key,
            dataset_kind=active_kind,
            dataset_path=str(resolved),
            workspace_dir=str(dataset_state_dir(resolved)),
            recent_datasets=recent,
        )

    def set(self, dataset_path: Path, dataset_kind: DatasetKind) -> WorkspaceStatus:
        resolved = dataset_path.expanduser().resolve(strict=True)
        payload = self._normalized_payload(self._load_payload())
        key = dataset_key(resolved)
        now = datetime.now(timezone.utc).isoformat()
        next_recent = [
            item for item in payload["recent_dataset_paths"] if item.get("dataset_key") != key
        ]
        next_recent.insert(
            0,
            {
                "dataset_path": str(resolved),
                "display_name": resolved.name,
                "dataset_key": key,
                "dataset_kind": dataset_kind,
                "last_opened_at": now,
            },
        )
        payload.update(
            {
                "schema_version": SCHEMA_VERSION,
                "active_dataset_path": str(resolved),
                "active_dataset_kind": dataset_kind,
                "recent_dataset_paths": next_recent[:MAX_RECENT_DATASETS],
            }
        )
        self._write_payload(payload)
        return self.get()

    def clear(self) -> WorkspaceStatus:
        payload = self._normalized_payload(self._load_payload())
        payload["active_dataset_path"] = None
        payload["active_dataset_kind"] = None
        self._write_or_remove(payload)
        return self.get()

    def remove_recent(self, recent_key: str) -> WorkspaceStatus:
        payload = self._normalized_payload(self._load_payload())
        payload["recent_dataset_paths"] = [
            item
            for item in payload["recent_dataset_paths"]
            if item.get("dataset_key") != recent_key
        ]
        self._write_or_remove(payload)
        return self.get()

    def _write_or_remove(self, payload: dict[str, Any]) -> None:
        if payload.get("active_dataset_path") or payload.get("recent_dataset_paths"):
            self._write_payload(payload)
            return
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError as exc:
            raise RuntimeError(f"Unable to clear workspace file '{self.path}'") from exc

    def _write_payload(self, payload: dict[str, Any]) -> None:
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

    def _load_payload(self) -> dict[str, Any]:
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

    def _normalized_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("schema_version") == SCHEMA_VERSION:
            recent = payload.get("recent_dataset_paths")
            return {
                "schema_version": SCHEMA_VERSION,
                "active_dataset_path": payload.get("active_dataset_path"),
                "active_dataset_kind": payload.get("active_dataset_kind"),
                "recent_dataset_paths": recent if isinstance(recent, list) else [],
            }

        legacy_path = payload.get("dataset_path")
        recent: list[dict[str, Any]] = []
        if isinstance(legacy_path, str) and legacy_path:
            resolved = Path(legacy_path).expanduser().resolve(strict=False)
            try:
                timestamp = datetime.fromtimestamp(
                    self.path.stat().st_mtime,
                    timezone.utc,
                ).isoformat()
            except OSError:
                timestamp = datetime.now(timezone.utc).isoformat()
            recent.append(
                {
                    "dataset_path": str(resolved),
                    "display_name": resolved.name,
                    "dataset_key": dataset_key(resolved),
                    "dataset_kind": None,
                    "last_opened_at": timestamp,
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "active_dataset_path": legacy_path,
            "active_dataset_kind": None,
            "recent_dataset_paths": recent,
        }

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
