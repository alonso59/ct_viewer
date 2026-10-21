# nnU-Net segmentation generation

Scope: generation of immutable segmentation sets with nnU-Net v2; model profiles, GPU partitioning, validation and indexing.
Read when: configuring or implementing `segment.nnunet`, running it on a GPU host, or consuming its outputs.
Depends: ADR-0015, ADR-0016, ADR-0032, TASKS.md, PROJECT_FORMAT.md, ops/DEPLOYMENT.md.

## Boundary

This phase generates masks and registers them as task-produced segmentation sets. It does not edit, correct, merge or overwrite masks. Training, model installation, VOI extraction and other segmentation pipelines are separate phases.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| SEG-01 | `segment.nnunet` is a first-party, project-scoped external task with item input and mask output. It runs in the existing host conda environment through TSK-11; nnU-Net, torch and CUDA stay outside the OCI image. | M |
| SEG-02 | An administrator creates a static, versioned model profile under `plugins/nnunet/profiles/`. Profiles are the allowlist shown in task settings; browser requests cannot supply executable names, arbitrary arguments or host paths. | M |
| SEG-03 | A profile records the dataset name/ID, channels, normalized output labels, one or more prediction configurations (trainer, plans, configuration, folds and checkpoint), optional upstream ensemble/postprocessing stages, CPU worker limits and a fingerprint of every model artifact. Invalid or missing artifacts make the profile unavailable. | M |
| SEG-04 | Preflight accepts ready NIfTI items whose modality and channel count match the profile. This phase supports one image channel per item; unsupported formats, missing files and blocking geometry warnings are skipped through TSK-04. | M |
| SEG-05 | Pending items are staged as read-only symlinks in the queue job using opaque case tokens and nnU-Net channel suffixes (`_0000`). A mapping file relates tokens to `item_id`; source and existing masks are never renamed or written. | M |
| SEG-06 | The plugin invokes official nnU-Net v2 entry points for prediction, ensemble and postprocessing. It does not reimplement preprocessing, sliding-window prediction, fold ensembling, resampling or export. Profile validation resolves labels from nnU-Net v2 `dataset.json`, including `regions_class_order`, or fails closed. | M |
| SEG-07 | One prediction stage uses `P = min(pending items, visible GPUs, profile/task cap)` concurrent `nnUNetv2_predict` processes. Each gets one `CUDA_VISIBLE_DEVICES` value and the same input with `-num_parts P -part_id K`; prediction configurations in an ensemble run as sequential stages. | M |
| SEG-08 | The runner uses `--concurrency 1` for `segment.nnunet`. Per-process preprocessing/export worker counts come from the profile so multiple GPUs cannot multiply CPU or RAM use without a declared bound. The UI may lower the GPU cap but cannot select GPUs outside the runner's visible set. | M |
| SEG-09 | Each part writes to its own scratch output. Successful parts are merged without overwriting, optional ensemble/postprocessing consumes only complete case artifacts, and final masks are geometry-checked against their input before atomic publication inside the run's `output_dir`. | M |
| SEG-10 | Each valid final mask emits one TSK-07 `ok` item output with value-to-name labels. TSK-09 registers all successful masks under one new `seg_id`, appends provenance to the derived ledger and rebuilds the index; imported and earlier task sets remain unchanged. | M |
| SEG-11 | A part failure marks only its assigned items failed when the remaining pipeline can still finish. Cancel terminates every child process. Resume stages only non-`ok` items and uses upstream continue behavior without rewriting registered outputs. | M |
| SEG-12 | `run.json` records the task/profile/settings hashes, input fingerprints, nnU-Net/torch/CUDA versions, visible GPU identifiers, effective official commands without absolute patient paths, model fingerprints, part assignment and final output hashes. | M |
| SEG-13 | Runtime network access is unnecessary and forbidden by R5. Logs and errors use case tokens or item IDs, never absolute patient paths at info level. | M |

## Model profile

```jsonc
{
  "profile": 1,
  "id": "kidney-d820",
  "title": "Kidney model (Dataset820)",
  "dataset": "Dataset820_Name",
  "channels": {"0": "CT"},
  "labels": {"1": "kidney", "2": "tumor"},
  "predictors": [
    {"configuration": "3d_fullres", "trainer": "nnUNetTrainer",
     "plans": "nnUNetPlans", "folds": [0, 1, 2, 3, 4],
     "checkpoint": "checkpoint_final"}
  ],
  "ensemble": null,
  "postprocessing": null,
  "processes": {"preprocessing_per_gpu": 2, "export_per_gpu": 2},
  "artifacts_sha256": "sha256:..."
}
```

`configure.py` will inspect `nnUNet_results`, `dataset.json` and, when present, `inference_instructions.txt` / `inference_information.json`; it writes structured fields, never a shell command. The checked-in example profile uses fake paths and model metadata only.

## Run sequence

1. The generic Tasks flow validates settings, selection, derived root and a fresh runner heartbeat.
2. The plugin validates the chosen profile and stages only pending items.
3. Each predictor fans out with the official part flags across the visible GPU pool; later predictors wait for the current stage.
4. The plugin merges part artifacts, then runs the profile's official ensemble and postprocessing stages when declared.
5. Final geometry checks publish per-item mask outputs; the existing task driver creates and indexes one segmentation set.

## Implementation plan

| Wave | Deliverable | Verification |
|---|---|---|
| 1 | Profile schema/configurator, manifest and startup diagnostics | Invalid profile/artifact/label fixtures fail closed; no arbitrary argv/path from the API |
| 2 | Single-GPU staging and official prediction wrapper | Fake nnU-Net executable proves names, commands, cancellation, partial failures, resume and source immutability |
| 3 | Multi-GPU partition controller | Fake GPUs prove disjoint `part_id` assignment, bounded workers and deterministic merge |
| 4 | Output geometry/provenance and task registration | Backend test registers one new set, reindexes it and leaves imported masks byte-identical |
| 5 | Generic Tasks UI integration and kirck acceptance | One item then a batch; two or more GPUs when available; masks open in the viewer; TST-21 |

## Open questions

- Kirck conda environment name and the command used to enter it.
- `nnUNet_results` location and the first model profile: dataset, configuration(s), folds, checkpoint, ensemble and postprocessing instructions.
- GPU IDs/count available to one run and the CPU/RAM budget that constrains preprocessing/export workers.
