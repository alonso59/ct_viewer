from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from app.services.volume_metadata import LoadedVolume, loaded_volume_from_array


def load_nifti(path: str | Path) -> LoadedVolume:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"NIfTI volume not found: {file_path}")

    try:
        image = nib.load(str(file_path))
        image = nib.as_closest_canonical(image)
        data = np.asarray(image.dataobj, dtype=np.float32)
    except Exception as exc:
        raise ValueError(f"Failed to read NIfTI volume '{file_path.name}': {exc}") from exc

    if data.ndim == 4:
        data = data[..., 0]
    if data.ndim != 3:
        raise ValueError(
            f"NIfTI volume '{file_path.name}' must be 3D after canonicalization; got shape {data.shape}"
        )

    return loaded_volume_from_array(
        data=data.astype(np.float32, copy=False),
        source_path=file_path,
        source_format="nifti",
        affine=np.asarray(image.affine, dtype=np.float64),
    )
