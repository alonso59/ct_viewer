# Standalone DICOM converter: implementation plan

Scope: turning the existing converter into an installable package (`rw_dicom`) shared by ct_viewer and a local CLI and Python API, with per-unit pinning, version provenance, bounded memory, parallel units and incomplete-dataset import.
Read when: implementing or reviewing ADR-0042 or DCM-26..34.
Depends: ADR-0042, ADR-0035, ADR-0040, DICOM_CONVERTER.md, DICOM_JOB_PLAN.md, ../ops/DICOM_STANDALONE_TEST_PLAN.md.

## Status and boundaries

- S0 (this plan, ADR-0042 Accepted, DCM-26..34) was approved by the owner on 2026-11-03. P7i does not depend on P7h (CTFlow).
- S1 (characterization and baselines, tests and tools only) runs independently. Production refactoring waits until its evidence has been reviewed.
- S2–S3 change only `plugins/dicom` internals and behave identically. S4–S8 change backend imports, the image, the inventory, execution or the API; they start only after P7g's mandatory gates and the P7 remote checks pass (ROADMAP).
- DCM-26..34 stay `S`: the standalone converter is not a v3.0 release dependency. Its release gates are the mandatory cases in DICOM_STANDALONE_TEST_PLAN.md §Release gates.
- Every phase is independently verifiable, stops for owner confirmation at its exit and keeps all ct_viewer workflows working: GUI, source operations, batches, project imports, storage rules and recovery.
- No unrelated refactoring, and no new services, databases, queues or schedulers. At each phase exit, facts move into their owner docs (§Specification ownership). After S8 this plan moves to `archive/`.

## Owner decisions (2026-11-03)

| # | Decision | Where |
|---|---|---|
| D1 | A dedicated namespace; existing ct_viewer imports and plugin registration keep working | ADR-0042 §1, DCM-26 |
| D2 | Per-unit pinning with strong SHA-256; the change from the whole-run snapshot is documented | ADR-0042 §4, DCM-29, §Integrity model |
| D3 | Strict cryptographic verification is the default; stat-based shortcuts only after benchmarks and file-system tests, including network storage | ADR-0042 §5, DCM-30 |
| D4 | Verified reuse across versions keeps the original provenance; an explicit policy for mixed-version datasets | ADR-0042 §6, DCM-31, §Version policy |
| D5 | A generated schema with a CI drift check; manifest hashes preserved; no loader change | ADR-0042 §2, DCM-27 |
| D6 | No shareable export yet; private metadata protected; PHI risk documented | ADR-0042 §3, DCM-28, §Privacy |
| D7 | P7i comes before P7h C7 and after P7g's mandatory gates; S1 runs independently | §Status, ROADMAP |
| D8 | DCM-26..34 stay `S`; correctness, integrity, privacy, recovery and compatibility cases are mandatory release gates | §Status, test plan §Release gates |
| D9 | Incomplete datasets keep their explicit status, distinguish failed, pending and converted units, need acknowledgment, and keep the original reasons and diagnostics | DCM-34, §Artifacts |
| D10 | SHA-256 stays the default for committed units; the limits of metadata-based detection are documented; any weakening needs an ADR and regression evidence | DCM-30, §Integrity model |
| D11 | Bounded-memory discovery and planning are verified at scale with one worker, independently of S7 | DCM-32, A17 |

## Verified starting point

| Area | Current behavior |
|---|---|
| Core | `plugins/dicom` (with `plugins/analyzers` and `plugins/text.py`) never imports `app`; the backend, Open mode (`tasks/dicom_stage.py`) and the CLI call it. There is one pixel path, `convert.write_nifti`. |
| App orchestration | One owned process per attempt (`tasks/dicom_process.py`, `dicom_worker.py`) under one admission lease (`dicom_execution.py`), plus the SQLite inventory (`tasks/source_inventory.py`), operations, batch plans and registration. |
| CLI | `plugins/dicom/cli.py`: legacy YAML, lock, journal and outcomes; resumes when re-run; repeats in-memory discovery on every invocation. Writes only `metadata.jsonl`, `nifti/` and `sidecars/`, and cannot set `anonymize`, `sidecars`, `patient_folders` or `phase_analyzer`. |
| Execution | `pipeline.run` converts series one at a time with ITK threads = 1; `SourceInventory._scan` reads files one at a time. |
| Pinning | Before the first pixel, every selected input is SHA-256 hashed (`input_pins`, `commits.pin_run`), and this repeats on every resume. On reuse, committed units hash their inputs again and decompress their outputs (`commits._commit`). |
| Memory | Per-file Python objects for the whole run: the `walked` paths, `Series.files` of every series in `found`, and `input_pins`. `SourceInventory.discover(subtree)` builds one Dataset per file of a subtree, and a flat source is a single subtree. |
| Commit identity | Full `asdict(Settings)` + salt + `reader_versions` (converter, SimpleITK, pydicom; not isal). [Inferred] Any change to settings or readers makes later incremental runs report committed series as conflicts. |
| Emission | `task.py` writes `summary.json` and `dataset.json` with plain `write_text`: no atomic replace, no fsync. |
| Incomplete results | Workspace: neither `dataset.json` nor the dataset's `annotations.jsonl` is written. A manual import turns failed and pending rows into `missing` items with `missing_path` errors and brings no layers. Project: `completed_with_errors` DICOM runs are not registered (`tasks/driver.py`). |
| Manifest hash | SHA-256 of the raw `task.json` bytes (`tasks/registry.py`), pinned by task-run resume. `task.json` is hand-formatted. |
| Code-hash caches | `scanner_identity`, the Open `series_fingerprint`, `dicom_eta`, the phase checkpoint and `source_open` all hash module file bytes. |
| Image | Code runs from source on `PYTHONPATH`, with dependencies from `backend/pyproject.toml`. The DICOM worker sets its own `PYTHONPATH`. |
| Platform | Linux-specific: `/proc/self/fd` (`convert.read_image`), `/proc/self/status` (`resources`), `RLIMIT_AS`, `sched_getaffinity`, and `PR_SET_PDEATHSIG` (backend). |

## Package boundary (S4)

| Moves unchanged into `plugins/dicom/src/rw_dicom/` | Stays |
|---|---|
| `files`, `scan`, `rows`, `sidecar`, `convert`, `commits`, `identity`, `resources`, `pipeline`, `cli` | `plugins/dicom/{plugin.json,task.json,task.py}`: job glue; `task.json` stays byte-identical |
| `plugins/analyzers/{__init__,target,readiness,phase,checkpoint}.py` → `rw_dicom.analyzers`; `plugins/text.py` → `rw_dicom.text` | `plugins/analyzers/{task.py,*.json}`, now importing `rw_dicom.analyzers` |
| One durable-write helper, replacing `commits._write`, `cli._write` and `pipeline.write_jsonl` | `plugins/protocol.py`, unchanged for the other plugins |
| The settings normalizer (S2) and the generated `settings.schema.json` | A shim at `plugins/dicom/cli.py` for `python -m plugins.dicom.cli` |

- **Distribution:** `rw-dicom`, `requires-python = ">=3.12,<3.13"`, dependencies `pydicom>=3.0`, `SimpleITK>=2.3`, `isal>=1.8,<2`, optional extra `yaml`. Console script `rw-dicom` with `convert`, `status` and `--version`. The name follows the repository's `rw` prefix (`rw`, `rw-runner`, `.rw-runs`).
- **Imports:** backend, tests and tools switch to `rw_dicom` in the same change. No `sys.modules` aliases (mypy can't follow them) and no star-import shims (`dicom_resources` assigns module attributes).
- **Image:** add `/app/plugins/dicom/src` to `PYTHONPATH` in the Dockerfile and in the `dicom_process.py` worker env. Dependencies stay in `backend/pyproject.toml`; a test checks the package's version ranges against `backend/requirements-ci.lock`. **Dev:** add the path to pytest `pythonpath` and mypy `mypy_path`.
- **Conda:** `conda activate <env>`, `pip install -e 'plugins/dicom[yaml]'`, then `rw-dicom convert SOURCE OUTPUT`.
- **One-time effects of the move:** inventories rescan, Open caches regenerate and the timing history resets; unfinished phase analyses must finish before upgrading. Committed outputs are unaffected (no code hash in the commit identity). Later phases leave `scan.py` and `files.py` unedited unless a rescan is intended.
- **macOS (later, not now):** GDCM behavior with `/dev/fd`; memory admission without `/proc` and `RLIMIT_AS`; `os.cpu_count`; a lifeline pipe instead of PDEATHSIG. New code adds no `/proc` dependency.

## Integrity model (S5b)

| Concern | Mechanism |
|---|---|
| Unit identity | `item_id` and output filename, allocated from the identity registry before execution |
| Input identity | Per-file `(relpath, size, sha256)` in the unit's commit record |
| Change detection | Unconverted unit: member `(size, mtime_ns, ctime_ns)` against the run pin's per-unit digest, checked before hashing. Committed unit: a SHA-256 rehash on every reuse (strict default). |
| Output integrity | SHA-256 of the image and sidecar, taken after gzip CRC and geometry validation at commit, verified on every reuse |
| Reproducibility | Deterministic identity; gzip `mtime=0` and an empty filename header; versions and the dataset-fixed settings hash recorded per unit, never inferred from reuse |

Per-unit protocol:
1. Open the members through the guarded descriptor chain and check their stats against the run pin.
2. SHA-256 the members, then read the sidecar header from the first one.
3. Decode, then hash again.
4. Commit as today: staged → prepared → published → committed.

The run pin keeps settings, versions, identity, the inventory generation and one stat digest per unit.

Guarantee change (explicit; replaces the whole-run snapshot described in the DCM-17 implementation notes):
- **Before.** Every selected input was content-pinned at preflight. Any content change to any selected input before its decode, or before a resume, was refused.
- **After.** Each unit's bytes are identical across its own hash → decode → rehash window and are recorded in its commit. Units are not pinned at one common moment; a preflight lasting hours never gave one moment either.
  - Between attempts, an unconverted unit is refused when its size, mtime or ctime changed. An edit that preserves all three (a reset clock, or a file system with emulated ctime) is no longer detected for unconverted units.
  - Committed units keep strong detection.
- **Gained.** No serial whole-source pass; the first output appears after one unit; no per-file manifest held for the run. The sidecar header and the image come from the same pinned bytes; today the sidecar header is read during planning, before the pin.
- **Remounts.** `dev` and `ino` stay out of the unit digests, as the inventory already handles them. How ctime behaves on bind and network mounts is measured in the S1 file-system lane.

Limits of metadata-based change detection. It is used only for inventory reuse (DCM-15, existing) and for unconverted units between attempts (DCM-29); never for committed units.
- **NFS** caches attributes on the client (`actimeo`), so a server-side edit can stay invisible for seconds or longer. Client and server clocks can also differ.
- **SMB/CIFS, FUSE and Docker Desktop mounts** may emulate or omit ctime, or report coarse timestamps.
- **Any file system:** timestamps have tick granularity, so an edit in the same tick as the recorded stat can keep its values. A reset clock defeats all three fields.
- Copies that preserve mtime (`rsync -a`, `cp -p`) still change ctime and refuse the unit, which errs on the safe side.
- These limits are measured per file-system lane in S1. A refusal is always safe; a miss means an unconverted unit is converted from its current bytes, and those bytes are still hashed into its commit.

Unchanged: the per-unit `flock`, owned staging, prepared and committed records, no-overwrite publication, adoption only on matching hashes, descriptor-pinned reads, and the D21 refusal cases.

## Version policy (S5b)

- **Versions compared:** the converter `VERSION`, SimpleITK, pydicom and isal. v1 records don't record isal; a key missing on either side is reported as `unrecorded` and does not count as a mix by itself.
- **Unfinished run, versions changed:** refused, as today. Remedy: finish on the pinned image, or start a new dataset.
- **New run:** verified committed units are reused with their recorded versions (`already_converted`).
  - Before any pixel is read, the plan compares the current versions with those of the committed units.
  - If new units would be converted with other versions, the run is refused (`mixed-versions`) unless the request acknowledges it: `allow_mixed_versions`; CLI `--allow-mixed-versions`; a confirmation in the converter window.
  - The acknowledgment is an execution parameter and is recorded in run provenance.
- **Visibility:** `summary.json` and `dataset.json` carry `units_by_versions: {hash: {versions, count}}`. The CLI summary and the converter window's result say when a dataset is mixed.
- **Commit record v2** adds versions, the dataset-fixed settings hash, member stats and per-step timings. v1 records are read forever, compared on their dataset-fixed subset.
- **Settings:** the dataset-fixed settings (`anonymize`, `sidecars`, `include_modality_prefix`, salt) can't change for a dataset; a change is refused. Selection settings may change between runs.

## Execution and memory (S5a, S7)

- **Coordinator** (the CLI parent, or the owned app worker): discovery, plan, identity, run pin, admission, outcomes, progress, and assembly in plan order.
- **Workers:** receive one unit at a time over a `multiprocessing` spawn `Pipe`. No `Queue`, so no resource-tracker helper process. Crashes are attributed by each worker's `sentinel`.
- **Worker setup:** ITK threads = 1; on Linux, `PR_SET_PDEATHSIG(SIGKILL)`; SIGINT and SIGHUP ignored; recycled after K units (K from benchmarks).
- **Memory:** a unit is admitted while, across in-flight units, Σ(worker baseline + the `resources` working-set estimate) ≤ the total budget.
  - The worker lowers its soft `RLIMIT_AS` to its share; the hard limit is the total.
  - A unit larger than the total budget is `waiting_for_resources` for that unit only. The run goes on and ends incomplete.
- **Worker count:** `auto` = min(affinity CPUs, units admitted, a benchmark cap). In the app, ≤ `DICOM_CPU_THREADS`, via a new `DICOM_WORKERS` (default 1, S7). `workers == 1` keeps today's in-process path.
- **Crash:** the unit becomes `crashed`, the worker is replaced and the unit is retried once; a second crash is `failed: worker_crashed`. Staging is reconciled by the unit protocol.
- **Termination:** app workers share the owned process group, so the existing `_stop_group` / `group_running` cleanup proof covers them unchanged. The CLI sends SIGTERM, then SIGKILL after the grace period, and waits on every sentinel.
- **ct_viewer unchanged:** admission lease, fencing, cancel evidence, restart reconciliation. The ETA signature gains the worker count; `bytes_per_s` uses wall-clock attempt time.
- **Bounded memory (S5a, verified with one worker before S7, A17):**
  - Planning reads the inventory one series at a time and keeps only rows and series keys. Members are loaded per dispatched unit.
  - Per-unit pins replace `input_pins`.
  - The CLI uses the inventory, so the `walked` list goes away; flat sources stream series the same way.
  - Coordinator memory = O(series rows) + O(in-flight units).

## Configuration (S2, S4)

- **Source of truth:** `task.json` `settings_schema`, edited by hand. `make gen-dicom-schema` writes `rw_dicom/settings.schema.json`, and `make check` fails if the two differ. Generation runs in this direction because the manifest hash covers the raw, hand-formatted `task.json` bytes, so generating `task.json` would change every pin.
- **One normalizer**, moved from `app/tasks/schema.py`, which re-exports it. `Settings` reads its defaults from the schema and refuses unknown keys; a test compares its field set with the schema.
- **Execution parameters:** `workers`, `memory_mb`, `max_failures`, `allow_mixed_versions`. Never in the settings hash, the commit identity or the CLI journal's `request`.
- **Optional config file** (YAML or JSON): `{source, output, settings, execution}`. Legacy keys are mapped into it (DCM-09).

## Artifacts and incomplete datasets (S2, S6)

- **Standalone output = the workspace dataset layout** (DCM-14), written by the same emission code with the workspace context: open phase vocabulary, salt `""`, the `DATA` alias, relative paths. Its 32-hex run ID can never match a workspace phase-run record, so an import takes the existing portable-dataset path (phase rows from `annotations.jsonl`).
- Every manifest is written atomically with fsync. `dataset.json` keeps its meaning: complete, sealed, listed, batch-complete.
- **Every finished attempt** writes `annotations.jsonl`, `diagnostics.jsonl` and `summary.json` (`complete: false|true`).
  - An incomplete attempt also writes `dataset.incomplete.json` (the `dataset.json` fields plus `complete: false` and counts), removed when `dataset.json` is published.
  - Older readers ignore that file, so a rollback can't seal an incomplete dataset.
- **Importing an incomplete dataset** requires `allow_incomplete`; the preview shows converted, failed and pending counts separately.
  - Converted units import with their layers.
  - `failed` rows become `excluded_upstream` with QC `conversion_failed`; `pending` and `waiting_for_resources` rows get `conversion_pending`. Both carry the row's original diagnostic code and message, never `missing_path`.
  - `diagnostics.jsonl` stays unchanged in the dataset, and the import records its SHA-256.
  - The import and its annotation run are marked incomplete and are never shown as complete. A later complete dataset imports as a new snapshot (IMP-06).
- **Project scope:** an explicit "Register converted series" control on a `completed_with_errors` DICOM run, with the same mapping. The run keeps its status; Retry failed registers the full snapshot later; registration stays idempotent per attempt.

## Privacy (all phases)

- **Private state:** a 0700 subtree with 0600 files, holding the inventory (full headers), run pin, journal, outcomes, timings and a traceback log.
- **The dataset itself may contain PHI** even with `anonymize: basic`: rows, sidecars, paths inside `commit.json`, `diagnostics.jsonl`, and `dataset.json.source`. The CLI documentation and summary state that a converted folder is not shareable as-is (DCM-05).
- **CLI output:** progress, summary and errors show counts and item IDs only, never folder names, PatientIDs or source paths. An unexpected exception prints its type and the item ID.
- **Anonymization:** semantics and salt are identical to a workspace dataset. In-project datasets salt with the project ID, by design.

## Phases

| Phase | Objective and changes | Depends on | Exit (test plan cases) |
|---|---|---|---|
| S0 | ADR-0042, this plan, the test plan, DCM-26..34. No code. Done 2026-11-03. | — | Owner approval; ADR-0042 Accepted; ADR-0035's status updated |
| S1 | Characterization and baselines: synthetic generator, benchmark tool, golden digests, characterization tests. Tests and tools only. | S0 | C01–C12 green; baselines B01–B06 recorded |
| S2 | Settings contract (normalizer moved into `plugins/dicom`; the CLI validates against the schema), shared atomic emission, private state, CLI artifact parity | S1 | A01–A08 |
| S3 | Behavior-preserving split into plan / execute / assemble, with a serial executor | S2 | A09 |
| S4 | The `rw_dicom` package: imports, image and dev paths, CLI flags and config file, Python API, generated schema, conda documentation | S3 | A10–A14 |
| S5a | Inventory core moved into `rw_dicom` with a backend wrapper; CLI on the inventory; bounded threaded header reads; streamed planning | S4 | A15–A17 |
| S5b | Per-unit pinning, run pin v2, commit record v2, version policy and its acknowledgment (additive API field), settings split | S5a | A18–A24 |
| S6 | Incomplete datasets: emission, import mapping and QC code, acknowledgment (API and UI), project registration control | S2 (scheduled after S5b) | A25–A29 |
| S7 | Parallel units: worker set, total memory admission, crash handling, CLI signals, `DICOM_WORKERS`, ETA and bytes rate | S5b | A30–A36; benchmark sweep B07; owner sets the defaults |
| S8 | Optimizations justified by S1/S7 data (e.g. reuse without decompression, a single staged hash, scratch and compression path, fsync batching). Stat-based checks only with a new ADR and the file-system lane. | S7 | Per change: before/after benchmark, guarantees unchanged or an accepted ADR, regression green |

## Specification ownership

At each phase exit, change facts only in their owner doc and cite IDs from tests:

| Phase | Owner docs |
|---|---|
| S2 | DICOM_CONVERTER §Settings (execution vs. conversion), §Output layout, CLI notes |
| S4 | DICOM_CONVERTER (DCM-09 note), `plugins/AGENTS.md` (owns `rw_dicom`), ops/DEV_ENV, ops/DEPLOYMENT §Implementation notes (`PYTHONPATH`), ops/TESTING |
| S5 | DICOM_CONVERTER §Implementation notes (pinning, commit v2, versions); backend/API (`mixed-versions` slug and field, skill `rw-api-change`) |
| S6 | INPUT_METADATA (QC codes, with `app/ingest/codes.py`), backend/API, frontend/UI_SHELL (UI-25, import preview) |
| S7 | ops/DEPLOYMENT §Config (`DICOM_WORKERS`; `DICOM_MEMORY_MB` as a total), backend/ARCHITECTURE (DICOM process exception), DICOM_CONVERTER ETA notes |

## Risks

| Risk | Mitigation |
|---|---|
| The package move invalidates code-hash caches | One planned move (S4), a release note, phase analyses finished before upgrading |
| Manifest hash drift breaks resume pins | `task.json` byte-identical; the schema is generated from it; C11 |
| The settings split misreads v1 records | C03/C04 first; v1 compared on the dataset-fixed subset |
| ctime is unreliable on some mounts (false conflicts or misses) | S1 file-system lane; committed units keep SHA-256; a conflict is never a silent reuse |
| A wrong memory estimate leads to OOM | Per-worker soft `RLIMIT_AS` = admitted share; the failure stays inside that unit |
| Orphaned workers, or parallel load slowing network storage | PDEATHSIG, process-group cleanup proof, waiting on every sentinel; benchmark caps, explicit `--workers` |
| A standalone output leaks PHI when shared, or incomplete data passes as complete | Private-state subtree and documentation; no export; acknowledgment, separate QC codes, incomplete marking |
