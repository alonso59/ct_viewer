from __future__ import annotations

from pathlib import Path

import numpy as np

from app.services.volume_metadata import LoadedVolume, loaded_volume_from_array


def load_numpy(path: str | Path) -> LoadedVolume:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"NumPy volume not found: {file_path}")

    try:
        data = np.load(file_path, allow_pickle=False, mmap_mode="r")
    except Exception as exc:
        raise ValueError(f"Failed to read NumPy volume '{file_path.name}': {exc}") from exc

    if data.ndim == 4:
        data = data[..., 0]
    if data.ndim != 3:
        raise ValueError(
            f"NumPy volume '{file_path.name}' must be 3D after squeeze; got shape {data.shape}"
        )

    return loaded_volume_from_array(
        data=data.astype(np.float32, copy=False),
        source_path=file_path,
        source_format="numpy",
        affine=None,
    )
