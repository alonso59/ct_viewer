from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.models.settings import DatasetViewerSettings
from app.services.workspace import workspace_file


class SettingsStore:
    def load(self) -> dict[str, DatasetViewerSettings]:
        path = workspace_file("settings.json", create=False)
        if not path.exists():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Settings file '{path}' is not valid JSON") from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to read settings file '{path}'") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Settings file '{path}' must contain a JSON object")

        return {
            dataset_id: DatasetViewerSettings.model_validate(value)
            for dataset_id, value in payload.items()
        }

    def save(
        self,
        settings: dict[str, DatasetViewerSettings],
    ) -> dict[str, DatasetViewerSettings]:
        path = workspace_file("settings.json", create=True)
        merged = self.load()
        merged.update(settings)
        payload = {
            dataset_id: config.model_dump(mode="json")
            for dataset_id, config in merged.items()
        }
        self._atomic_write(path, payload)
        return merged

    def _atomic_write(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with NamedTemporaryFile(
                "w",
                dir=path.parent,
                prefix=path.stem + ".",
                suffix=".tmp",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temp_path = Path(handle.name)
            temp_path.replace(path)
        except OSError as exc:
            raise RuntimeError(f"Unable to write settings file '{path}'") from exc


settings_store = SettingsStore()
