# ADR-0024 Open mode shows images only (segmentations by attach); nnU-Net naming moves to the nnU-Net plugin
Status: Accepted · Date: 2026-09-25
Amends: ADR-0013 §3 (Open mode) and SRC-04 defaults
**ADR-0027 (Proposed)** amends §1 (attach from anywhere under ALLOWED_DATA_ROOTS) and §2 (the wizard pre-fills the converter's naming when every name follows it).

**Context.** Open mode guessed label maps from values (integer dtype, ≤ 256 distinct values in the middle slice). Small or quantized integer CTs passed the rule (the synthetic Dataset900 CTs: int16, 240 values, −1024…110), were loaded as their own segmentation, and the viewer refused them (label values are never negative): a false "The segmentation could not be loaded". Separately, the `nifti-files` adapter's defaults were nnU-Net dataset naming (`{scan}_{MOD}_{case}_{channel:04d}` stems, `imagesTr/`/`labelsTr/`), although nnU-Net is a pending plugin (TSK-08).

**Decision.**
1. **Open mode: an opened file is always an image.** No label guessing from values or names. A segmentation exists only when the user attaches one to an image: a NIfTI file (`.nii`, `.nii.gz`) whose geometry matches (SRC-10: same shape, affines within the IMP-08 tolerance, never resampled). NumPy attach, the image ↔ label switch and "a label map opened alone" are removed.
2. **nnU-Net dataset naming is not a core convention.** The `nifti-files` default pattern is one case per file stem (`^(?P<case_id>.+)$`); `imagesTr/`/`labelsTr/` and the `_0000` channel suffix are no longer special. A user pattern may still name a `channel` group. nnU-Net import/export naming comes back with the nnU-Net plugin.
3. **Kept (owner, pending):** the metadata-v1 `seg_path` convention `seg/{filename minus _0000}` (INPUT_METADATA) and the converter's output names (DICOM_CONVERTER). They are the owner's dataset contract, not nnU-Net plugin logic; the `nifti-files` `seg/{name}` convention keeps matching that layout.

**Consequences.**
- \+ No false segmentation errors; what is a mask is always the user's explicit choice in Open mode.
- \+ Core import has no hidden nnU-Net assumptions.
- − A label file opened alone shows as a grey image; attach it to its image to see it as an overlay.
- − An nnU-Net-style folder imports with the generic defaults (one case per stem, `labelsTr/` files as items) until the nnU-Net plugin, or with a user pattern and `seg/` layout. Old import options naming `labelsTr/{case}.nii.gz` are refused with the allowed list.

**Rejected.**
- Keeping the value heuristic with a non-negative check: still a guess, still wrong for quantized images.
- Moving the metadata-v1 / converter `_0000` naming now: it would break importing existing converted datasets (left pending by the owner).
