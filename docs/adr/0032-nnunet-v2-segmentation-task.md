# ADR-0032 nnU-Net v2 inference as a partitioned external segmentation task
Status: Accepted · Date: 2026-10-21
Amends: ADR-0016 §6 and TSK-12 for one multi-GPU external run

**Context.** nnU-Net v2 is installed in the `torch` conda environment on the `john-gpinedo` GPU host and its trained models must stay outside the OCI image. A web run should use the host GPUs in parallel, preserve nnU-Net's inference pipeline, write only derived data and add predictions beside imported masks. This phase excludes mask editing and other segmentation pipelines.

**Decision.** Requirements and profile format: SEGMENTATION.md (SEG-*).
1. Ship `segment.nnunet` as a first-party external task executed by the existing file-queue runner in the installed conda environment.
2. Administrators expose validated, static model profiles. The browser selects a profile and safe settings; it cannot provide commands, model paths or arbitrary flags.
3. Stage pending inputs with nnU-Net names in job scratch. Invoke official nnU-Net v2 prediction, ensemble and postprocessing entry points; do not replace their preprocessing or inference code.
4. Parallelize a prediction stage with upstream `-num_parts/-part_id`, one process per explicitly visible GPU. The operator exposes 2–4 GPUs to the runner; the task defaults to 2 and cannot request more than 4. One runner claims one nnU-Net web run at a time; CPU worker counts are bounded per GPU.
5. Publish geometry-validated NIfTI masks atomically into the run's derived output and register them as one new segmentation set through TSK-09. Source files and existing masks are never modified.
6. Keep partial item results, cancel every child process, and resume only unfinished items. Record the effective pipeline, model/profile fingerprints, dependency versions, GPU assignment and output hashes.

**Consequences.**
- \+ Multi-GPU inference follows the upstream data-partition mechanism and retains fold/configuration ensemble and postprocessing semantics.
- \+ The core image, API process and generic task/indexing contract remain unchanged.
- \+ Predictions remain comparable with imported masks and can feed later pipelines.
- − The GPU host needs an operator-maintained model profile and a running host runner.
- − A single case uses one GPU; acceleration comes from processing different cases concurrently.

Accepted scope: the first production profile is `Dataset220_KiTS2023`. Its compact inference bundle is installed outside the repository; later profiles require a separate phase decision.

**Rejected.** Custom torch inference (diverges from nnU-Net); GPU code in the OCI image (OPS-08/R3); the API starting conda or SLURM processes (TSK-11); one independent web run per GPU (fragments provenance and segmentation sets).
