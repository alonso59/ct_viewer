from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from app.services.volume_metadata import LoadedVolume, loaded_volume_from_array


def load_mask(path: str | Path, is_nifti: bool) -> LoadedVolume:
    mask_path = Path(path)
    if not mask_path.is_file():
        raise FileNotFoundError(f"Segmentation mask not found: {mask_path}")

    affine: np.ndarray | None = None
    if is_nifti:
        try:
            image = nib.load(str(mask_path))
            image = nib.as_closest_canonical(image)
            data = np.asanyarray(image.dataobj)
            affine = np.asarray(image.affine, dtype=np.float64)
        except Exception as exc:
            raise ValueError(
                f"Failed to read NIfTI segmentation '{mask_path.name}': {exc}"
            ) from exc
    else:
        try:
            data = np.load(mask_path, allow_pickle=False, mmap_mode="r")
        except Exception as exc:
            raise ValueError(
                f"Failed to read NumPy segmentation '{mask_path.name}': {exc}"
            ) from exc

    if data.ndim == 4:
        data = data[..., 0]
    if data.ndim != 3:
        raise ValueError(
            f"Segmentation mask '{mask_path.name}' must be 3D after squeeze; got shape {data.shape}"
        )

    return loaded_volume_from_array(
        data=data.astype(np.uint8, copy=False),
        source_path=mask_path,
        source_format="nifti" if is_nifti else "numpy",
        affine=affine,
    )
