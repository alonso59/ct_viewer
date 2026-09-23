from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def dataset_state_dir(dataset_path: Path | str, dataset_id: str | None = None) -> Path:
    resolved_dataset = Path(dataset_path).expanduser().resolve()
    resolved_dataset_id = dataset_id or resolved_dataset.name
    configured = get_settings().webui_state_dir
    if configured:
        return (Path(configured).expanduser().resolve() / resolved_dataset_id).resolve()
    return resolved_dataset / ".webui"


def writable_dataset_state_dir(
    dataset_path: Path | str,
    dataset_id: str | None = None,
    *,
    create: bool = False,
) -> Path:
    state_dir = dataset_state_dir(dataset_path, dataset_id)
    if create:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Unable to create WebUI state directory '{state_dir}'. "
                "Set WEBUI_STATE_DIR to a writable external location for read-only datasets."
            ) from exc

    if not _is_writable(state_dir):
        raise RuntimeError(
            f"WebUI state directory '{state_dir}' is not writable. "
            "Set WEBUI_STATE_DIR to a writable external location for read-only datasets."
        )
    return state_dir


def dataset_state_file(
    dataset_path: Path | str,
    filename: str,
    dataset_id: str | None = None,
    *,
    create: bool = False,
) -> Path:
    state_dir = (
        writable_dataset_state_dir(dataset_path, dataset_id, create=True)
        if create
        else dataset_state_dir(dataset_path, dataset_id)
    )
    return state_dir / filename


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
