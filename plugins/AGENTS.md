# plugins/ map

First-party plugins (PLG-01). Each folder has a `plugin.json`; task plugins add `task*.json` manifests. Builtin plugins are installed into the image; `PLUGINS_ROOT` is the host copy the runner executes for `external` runtimes.

**Owns**
- Task plugins: `dicom/` (converter, DCM), `analyzers/` (phase, readiness, target; ANZ), `nnunet/` (segmentation, SEG), `threshold/` (CI test task).
- `runner/`: host-runner safety (GPU allocation, sandbox, supervised lifecycle, preflight; OPS-16..19). The host runner itself is `scripts/rw-runner.py` (TSK-11).
- Contribution-only (UI, routes or pack data): `radiomics/` (its builtin task lives in `backend/app/radiomics/`), `curation/`, `labeling/`, `dashboard/`; packs `ccrcc/`, `generic-ct/`; `voi/` is pending (PLG-09).
- Shared: `protocol.py` (task side of the run protocol, TSK-07), `text.py` (DICOM value → text).

**Entry points:** a manifest's `runtime`: `builtin` → `entry` (`module:function`, run in a job worker); `external` → `command` run by the host runner in the plugin's own environment (R4).

**Boundaries**
- Plugin code does not import `backend/app`; it talks to the app only through job files (TASKS.md §Protocol).
- Task code writes only into the run's output folder or the task's `dataset/` in a `derived` root (BE-03, R1).
- The backend runs plugins only through `backend/app/tasks/`; their UI lives in `frontend/src/plugins/<name>/`.

**Tests:** in `backend/tests/`, named after the plugin (`test_dicom*`, `test_analyzers.py`, `test_nnunet*`, `test_runner*`, `test_gpu*`, `test_supervised*`, `test_plugins.py`). Runner safety gate: `make test-runner`; host effects: `make test-host`.

**Change together**
- `task*.json` settings ↔ the schema-driven task form (`frontend/src/features/tasks/`) ↔ the owning domain doc.
- `plugin.json` ↔ `docs/domain/PLUGINS.md` §Manifest.
- Runner, GPU or supervised behavior ↔ `docs/domain/SEGMENTATION_RUNTIMES.md` and the active P7g plan (`docs/INDEX.md` §Active plans).
- DICOM discovery or conversion ↔ `docs/domain/DICOM_CONVERTER.md` and the active DICOM plan.

**Read more:** protocol and runtimes `docs/domain/TASKS.md`; manifest and catalog `docs/domain/PLUGINS.md`; nnU-Net `docs/domain/SEGMENTATION.md`; analyzers `docs/domain/ANALYZERS.md`.
