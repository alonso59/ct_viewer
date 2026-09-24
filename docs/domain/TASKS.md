# Tasks & plugins

Scope: task manifest, selection and preflight, run protocol, builtin and external runtimes, output registration.
Read when: adding or running any task (converter, analyzers, radiomics, segmentation), or touching the runner.
Depends: ADR-0014, ADR-0015, ADR-0016, ADR-0017, RADIOMICS.md, SOURCES.md.

A **task** takes a selection plus settings, runs as a job, and produces typed outputs. Radiomics, the DICOM converter, the metadata analyzers and nnU-Net are all tasks.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| TSK-01 | Every task has a manifest (§Manifest). Builtin manifests ship in the image; external ones are `PLUGINS_ROOT/*/task.json` (read-only). Invalid manifests are listed with their error, not loaded. | M |
| TSK-02 | Settings come from the manifest's JSON Schema, rendered by the generic schema form. Validation runs live in the UI and authoritatively on the server. Radiomics keeps its richer schema (RAD-01) behind the same endpoints. | M |
| TSK-03 | Selection is shared by every item task: all active / current Explorer filter / explicit item list; scope; `seg_id` + labels when the task reads masks (RAD-05 generalized). | M |
| TSK-04 | Preflight checks `requires` against the selection → `{n_ready, missing: {reason: count}, suggestions: [{task_id, reason}]}`. Example: 12 items without a `kidney` mask → suggest `segment.nnunet`. Items that aren't ready are skipped, never failed. | M |
| TSK-05 | Estimate before a run: units, skipped, time (builtin: measured on a 3-item sample; external: the manifest's `seconds_per_item`, else unknown), output size when known. | S |
| TSK-06 | A run is a job (BE-06) with statuses `queued`, `waiting_for_runner`, `running`, `completed`, `completed_with_errors`, `failed`, `cancelled`, `interrupted`. Per-item progress and ETA arrive over SSE. The UI never blocks. | M |
| TSK-07 | Protocol (§Protocol) is identical for builtin and external runtimes. Per-item failures don't stop a run (as RAD-07). Resume skips items already `ok` (as RAD-08). | M |
| TSK-08 | Tasks that need tool-specific names or layouts (nnU-Net `{case}_0000.nii.gz`) stage symlinks in the job's scratch dir. Source and derived files are never renamed. | M |
| TSK-09 | Outputs are registered by type (§Outputs). Volumes go only into the project's `derived` root (ADR-0014); tabular outputs go into the project folder. | M |
| TSK-10 | Run record `tasks/runs/{run_id}/run.json`: task id + version, manifest hash, settings + hash, selection, inputs with fingerprints, dependency versions, counts, outputs (NFR-15). Radiomics keeps `radiomics/runs/{run_id}/` (RAD-09). | M |
| TSK-11 | External runtime through the file queue (§External runtime); the backend never starts containers or host processes. | M |
| TSK-12 | One run per `(project, task)` at a time; the runner caps concurrency (default 1 per GPU). | S |

## Manifest (`task.json`)

```jsonc
{ "manifest": 1,
  "id": "segment.nnunet", "version": "0.1.0", "title": "nnU-Net segmentation", "description": "…",
  "kind": "segmentation",                // conversion | analyzer | features | segmentation
  "input": "items",                      // items (indexed volumes) | rows (metadata only) | source (a source root)
  "outputs": ["masks"],                  // ⊂ images, masks, features, metadata, annotations
  "requires": { "modality": ["CT"], "channels": 1, "seg": null },   // seg: {labels:[names]} when masks are read
  "settings_schema": { /* JSON Schema subset: object, boolean, integer, number, string(enum), array; x-group, x-help, x-advanced */ },
  "defaults": { },
  "runtime": { "type": "external", "command": ["python", "-m", "rw_nnunet", "{job_dir}"], "env_hint": "conda env rw-nnunet" },
                                         // builtin: { "type": "builtin", "entry": "plugins.analyzers.phase:run" }
  "resources": { "gpu": "required", "max_batch": 20, "seconds_per_item": 40 },
  "labels": { "from": "dataset.json" },  // segmentation tasks: label names ({"names": {"1": "kidney"}} inline)
  "test_only": false }                   // CI plugins: hidden from the Tasks view and from suggestions
```

Loading (TSK-01): builtin manifests are `app/radiomics/task.json` and `{BUILTIN_PLUGINS_ROOT}/*/task*.json` with `runtime.type = builtin` (external manifests shipped there, e.g. `plugins/threshold/`, are for `PLUGINS_ROOT` only); external ones are `PLUGINS_ROOT/*/task.json` and must use the external runtime. Unknown keys, a duplicate id or a schema outside the subset make a manifest invalid. Builtin entries are `run(job_dir) -> int` and follow the protocol below; plugins never import `app` (shared helper: `plugins/protocol.py`, stdlib only).

## Protocol

Job dir: builtin = `WORKSPACE_ROOT/.scratch/jobs/{job_id}/`; external = `WORKSPACE_ROOT/queue/{job_id}/`.

| File | Writer | Content |
|---|---|---|
| `job.json` | backend | `{protocol: 1, job_id, run_id, mode: run\|estimate, task: {id, version}, settings, items[] \| rows[], output_dir, identity?, resume: {skip[]}, batch: {size}}`. Each item has `item_id`, `case_id`, `image {path, format}`, `masks {seg_id: {path, format}}` (only the selected set when the task reads masks), `geometry`, `meta` (scan_idx, scope, side, modality, phase, phase_raw, patient_id, labels_present, extra). `mode: estimate` = the TSK-05 sample run into a disposable `output_dir` |
| `claim` | runner | Created with `O_EXCL`; `{runner_id, pid, at}` (external only) |
| `progress.jsonl` | task | `{t: "item", item_id, status: ok\|failed\|skipped, outputs: [{kind, path, seg_id?, labels?, sha256?}], message}` · `{t: "total", n}` (a source task's unit count once known) · `{t: "log", level, message}` · `{t: "heartbeat"}` |
| `result.json` | task | `{status, counts, outputs_manifest[], versions, started_at, finished_at, error?}`; written last, atomically |
| `cancel` | backend | Presence = cancel. Builtin: checked between items. External: the runner sends SIGTERM, then SIGKILL after 30 s |

- Paths: data and derived roots are absolute and mirror-mounted (OPS-05), so they are the same inside the container and on the host. Workspace files are referenced **relative to the job dir**, because the workspace path differs across the container boundary.
- Exit code 0 = see `result.json`; non-zero or no `result.json` = `failed`, with the tail of the log kept.
- `job.json` also carries `context` (phase vocabulary, preset, preset target profile), `project_id`, and for tasks with volume outputs `dataset_dir` + `dataset_ref` (the append-only `dataset/`); `input: source` tasks get `source {path}`; tasks with `metadata` outputs get `identity` and `previous_metadata`. `result.json` may add `identity` (merged into `sources/identity.json`, append-only) and `estimate`.
- Output kinds in item lines: `mask`, `image`, `sidecar` (files inside `output_dir` or `dataset/`, recorded with sha256 in the ledger); `result.outputs_manifest`: `annotations` (a job-dir file, copied to the run) and `metadata` (a file in `output_dir`, imported as the source `task:{task_id}`).
- The API process tails `progress.jsonl` (every 0.2 s) and keeps, in `tasks/runs/{run_id}/`: `run.json` (TSK-10), `items.jsonl` (one outcome line per item and attempt; the last one wins; resume skips `ok` items), `log.jsonl`, and `masks.jsonl` for mask outputs. A mask output must be a file inside `output_dir`, else the item becomes `failed`. Builtin job dirs are deleted when the run ends.

## External runtime

- `scripts/rw-runner.py` (stdlib only) runs on the host inside the plugin's environment (e.g. an activated conda env; R4):
  `python scripts/rw-runner.py --workspace <WORKSPACE_HOST> --plugins <PLUGINS_ROOT> [--tasks segment.nnunet] [--concurrency 1]`.
- Heartbeat: `queue/runners/{runner_id}.json` `{tasks[], gpu, pid, at}` every 10 s. With no fresh heartbeat for the task, a job shows `waiting_for_runner` (not an error) and the UI shows how to start the runner.
- Writers: the backend writes only `job.json` and `cancel`, and the runner/task writes the rest. `queue/` is the only workspace directory with a second writer; project files keep the single writer (BE-05).

## Outputs

| Type | Registered as |
|---|---|
| `masks` | A segmentation set (ADR-0015): `seg_id` = settings `seg_id` (must be new) or `{task-short}-{run_id[:8]}` lower-cased, `label_mapping` from the manifest's labels matched by name (unmatched values get new `label_*` entries in the label map and are listed in `unmatched`), `producer` = this run. It is created at the first `ok` item; at the end the index re-joins every task set from its `masks.jsonl` (the index stays derived, PRJ-10). Every volume output is recorded with its sha256 in `derived/runs.jsonl` |
| `images` + `metadata` | A new import through `metadata-v1` with alias `DERIVED` (IMP-06); the converter writes the full current `metadata.jsonl` per run (DCM-07) |
| `features` | A Parquet run in `tasks/runs/{run_id}/` (radiomics: RAD-10); the dashboard reads any features run |
| `annotations` | `tasks/runs/{run_id}/annotations.jsonl`, active per field through `project.json.annotation_sources` (ANZ-04) |

## Builtin tasks

| ID | Input | Outputs | Owner |
|---|---|---|---|
| `radiomics.pyradiomics` | items | features | RADIOMICS.md |
| `dicom.convert` | source | images, metadata | DICOM_CONVERTER.md |
| `analyzer.phase`, `analyzer.target`, `analyzer.readiness` | rows | annotations | ANALYZERS.md |
| `segment.threshold` (test only, CI; runs under both runtimes, TST-14) | items | masks | TESTING.md |

External (first, deferred until P7b is stable, ROADMAP §P7b): `segment.nnunet` in `plugins/nnunet/`. The manifest above is its target shape.
