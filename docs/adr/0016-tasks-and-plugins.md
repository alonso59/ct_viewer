# ADR-0016 Tasks and plugins: one contract, builtin and external runtimes
Status: Accepted · Date: 2026-09-24
Amends: ADR-0006 (radiomics becomes a builtin task), ADR-0007 (heavy plugins run outside the image)

**Context.** DICOM conversion, metadata analyzers, radiomics and nnU-Net segmentation all take items plus settings, run as a job, and produce derived data. nnU-Net needs torch and a GPU, which don't fit the 1.5 GB image (OPS-08). The API runs inside a container (Docker or udocker), so it cannot start containers or host conda envs.

**Decision.** Protocol and fields: TASKS.md (TSK-*).
1. **Manifest.** A task is a `task.json` manifest with:
   - id and version;
   - typed outputs (`images`, `masks`, `features`, `metadata`, `annotations`);
   - `requires`;
   - settings as JSON Schema, rendered by the generic form (RAD-01 generalized);
   - `runtime` (`builtin` | `external`);
   - `resources`.
2. **One run protocol.**
   - The task reads `job.json` and appends per-item lines to `progress.jsonl`, then writes `result.json`.
   - Cancel is a flag file plus SIGTERM. Resume skips the items already `ok`.
3. **Builtin runtime: the job workers (BE-06).**
   - Radiomics becomes `radiomics.pyradiomics`; RAD-* and the engine adapter stay.
   - API-30..37 are aliases for one phase.
   - The converter and the analyzers are builtin (ADR-0017).
4. **External runtime.**
   - Jobs go to `WORKSPACE_ROOT/queue/`, and a stdlib-only host runner (`scripts/rw-runner.py`) executes them in the plugin's env with GPU access.
   - No nested containers, sudo (R4) or ports (R5).
   - Jobs show `waiting_for_runner` until a runner heartbeat appears.
5. **Outputs by type:**
   - masks → a segmentation set (ADR-0015);
   - images + metadata → a `metadata-v1` import (ADR-0013);
   - features → a Parquet run for the dashboard;
   - annotations → proposals (ADR-0017).
6. **nnU-Net plugin.**
   - The model folder's `dataset.json` gives the labels and channels.
   - Inputs are staged as `{case}_0000` symlinks.
   - It runs anything from one item to the whole selection, in batches.
7. **Trust.** Builtin tasks ship in the image; external ones are admin-installed manifests under `PLUGINS_ROOT`. There is no download.
8. **CI.** A fake threshold-segmentation plugin tests the external path without a GPU.

**Consequences.**
- \+ One UX for every tool.
- \+ Heavy models stay out of the image.
- − A runner to start on the host.
- − Radiomics migrates onto a generic run model.
- Owners: TASKS, RADIOMICS, API, BE ARCHITECTURE, DEPLOYMENT, UI_SHELL, TESTING.

**Rejected.**
- Heavy deps in the image.
- The backend spawning containers: impossible under udocker.
- HTTP plugin services.
- Entry points in the API process: dependency conflicts, crashes.

**Amended by ADR-0018.** Tasks are one contribution type of first-party plugins; third-party plugins are out of scope in v3, and `PLUGINS_ROOT` only points the host runner at first-party external plugins.
