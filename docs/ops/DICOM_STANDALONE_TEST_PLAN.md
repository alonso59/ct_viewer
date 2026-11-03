# Standalone DICOM converter: tests, benchmarks and acceptance

Scope: characterization, acceptance cases and benchmark protocol for DICOM_STANDALONE_PLAN.md.
Read when: writing tests or benchmarks for ADR-0042 phases, or deciding whether a phase is complete.
Depends: ../domain/DICOM_STANDALONE_PLAN.md, DICOM_JOB_TEST_PLAN.md, TESTING.md, ADR-0042; requirement ownership stays in INDEX.md.

## Method

- Labels C, A and B are case labels, not requirement IDs. Each test cites the requirement it covers (DCM-*, IMP-*, …) and its case label (R8).
- **S1 characterization tests assert today's behavior**, known gaps included. A phase that changes a behavior changes its test in the same commit, citing the new requirement. No skips and no xfail.
- DICOM_JOB_TEST_PLAN.md cases D17–D24, D28, D29, D34 and D35 stay required at every phase exit.
- **Data:** synthetic data for CI, recordings and screenshots, with no patient paths or tags in artifacts. Real data is opt-in local acceptance only, never a CI fixture or an upload.
- **Assertions:** test public behavior and file-system and process effects, not private structure. Validate geometry with independent readers (nibabel, known landmarks), never only with the writer's own return values.
- **Evidence:** record revision, environment, lock hash, command and evidence location in DICOM_STANDALONE_PLAN.md at each phase exit.

## Fixtures

| Fixture | Construction and oracle |
|---|---|
| Golden source | Seeded multi-patient CT tree (DICOM_JOB_TEST_PLAN geometry oracle and header variants), with skip, fail and multi-series cases. Digests of images, sidecars, normalized rows and annotations are recorded per lock hash; they are regenerated only when the lock changes. |
| Scaling series | Generator for N patients × M series × K slices with small matrices (≥ 64×64; the native reader rejects 4×4) and unique UIDs, in two sweeps: fixed series count with K ×1/×10/×100, and fixed K with growing M. Covers 10³ to 10⁶ files, plus a flat variant with every file directly in the root. |
| Mutable source | DICOM_JOB_TEST_PLAN's mutable source, including an equal-length edit with a restored mtime. Applied before decode, during decode (barrier), and between attempts, to converted and to unconverted units. |
| Version fixture | Committed units with recorded versions patched to another value; v1 records without isal |
| Incomplete dataset | A workspace dataset and a CLI dataset with converted, failed (decode error, `CommitConflict`) and pending units |
| Process harness | DICOM_JOB_TEST_PLAN's crash harness, plus barriers inside a worker (after hash, after decode, after staging) and a native fault injected with `os._exit` |
| File-system lanes | Local ext4 or xfs (required); a Docker Desktop bind mount and an NFS or SMB mount where available. Each lane records ctime support, timestamp granularity, attribute-cache staleness and remount behavior (DICOM_STANDALONE_PLAN §Integrity model limits). |

## S1 characterization (C)

| Case | Today's behavior to record | Covers |
|---|---|---|
| C01 | Golden digests and normalized rows of a workspace conversion, including `anonymize: basic` | DCM-02/04/05/13/14 |
| C02 | Artifact difference between CLI and workspace (missing files, the settings the CLI can't set) | DCM-09/14 |
| C03 | A second incremental run with a different selection setting reports committed series as conflicts | DCM-07/17 |
| C04 | A changed `reader_versions` makes committed series conflict in a later incremental run | DCM-07/17 |
| C05 | `summary.json` and `dataset.json` torn by a crash injected during the write | DCM-14 |
| C06 | Importing a partial workspace dataset gives `missing` items with `missing_path` and no layers; a project `completed_with_errors` run is not registered | DCM-07, IMP-07 |
| C07 | Source and output bytes read during a fresh run and during a resume, counted at the file-open level | DCM-17 |
| C08 | Peak RSS of the inventory scan, the dry-run plan and the conversion coordinator across the scaling sweeps up to 10⁶ files, with one worker (recorded by the benchmark tool, not asserted) | DCM-32 |
| C09 | Time to first committed output against the selected source bytes (benchmark tool) | DCM-29 |
| C10 | Mutable-source detection per window, as today; the restored-mtime edit is detected | DCM-17 |
| C11 | `task.json` manifest hash; it must stay constant through S2–S7 | DCM-27 |
| C12 | CLI response to SIGINT, SIGTERM, SIGHUP and SIGKILL (journal state, orphans, resume) | DCM-09/33 |

## Acceptance (A)

| Case | Acceptance | Phase |
|---|---|---|
| A01 | The schema, `Settings`, CLI flags, legacy YAML, JSON and the API produce the same normalized settings and the same hash; unknown keys are refused | S2 |
| A02 | CLI output equals the workspace dataset: identical images, sidecars, rows and annotations; diagnostics equal apart from run IDs, timestamps and absolute paths | S2 |
| A03 | A CLI dataset imports through the existing `commit_with_annotations` path with its analyzer layers and sidecar refs | S2 |
| A04 | A crash injected during emission never leaves a torn manifest; the import sees either the previous state or the new one | S2 |
| A05 | Private state is 0700/0600; CLI stdout, stderr, progress and tracebacks contain no folder names, PatientIDs or source paths | S2 |
| A06 | `anonymize: basic` gives the same output from the CLI and from a workspace run | S2 |
| A07 | C11 is unchanged; all existing DICOM, source-operation, batch and import suites are green | S2–S8 |
| A08 | Legacy YAML configs and `python -m plugins.dicom.cli` work unchanged | S2, S4 |
| A09 | The split leaves C01 digests, row order and annotations byte-identical; `VERSION` unchanged | S3 |
| A10 | A clean Python 3.12 venv or conda env installs `rw-dicom` without backend dependencies; `rw-dicom convert`, `api.convert` and `--version` work | S4 |
| A11 | Isolation: the CLI runs in a subprocess where `app`, `plugins` and `fastapi` cannot be imported | S4 |
| A12 | The schema drift check fails on any difference between the generated copy and `task.json` | S4 |
| A13 | Image smoke test (`scripts/dicom-namespace-smoke.py`) and owned-worker conversion pass with the new `PYTHONPATH`; the dependency ranges match the lock | S4 |
| A14 | After the move, inventories rescan cleanly and Open caches regenerate; committed outputs are reused | S4 |
| A15 | CLI discovery resumes without re-reading unchanged headers (instrumented counts) | S5a |
| A16 | Threaded inventory reads give the same rows, series and diagnostics as sequential reads | S5a |
| A17 | With one worker and up to 10⁶ files, peak RSS of discovery, inventory scan, planning and the coordinator stays flat within the measured tolerance when K grows ×10 and ×100 at a fixed series count; the slope over M is reported; the flat-source variant is bounded the same way. Verified before S7 starts. | S5a |
| A18 | No whole-source hash pass: the first unit decodes before any other unit's inputs are read (spy on read order) | S5b |
| A19 | Mutable source: changes before decode, during decode and between attempts are refused for converted and unconverted units; the restored-mtime edit is detected through ctime; D21 still passes | S5b |
| A20 | The sidecar header and the image come from the same pinned bytes | S5b |
| A21 | Commit v2 is written; v1 records verify and are reused; a corrupt record of either version is a conflict | S5b |
| A22 | Version policy: a changed version blocks resume of an unfinished run; a later run reuses older units with their provenance; new units refuse without acknowledgment and record it with acknowledgment; `units_by_versions` is correct; unrecorded keys don't count as a mix | S5b |
| A23 | Changing a selection setting reuses committed units; changing a dataset-fixed setting is refused | S5b |
| A24 | Strict verification: a flipped byte or a truncation in an input or output is a conflict and never reused; resume read volume is compared with C07 | S5b |
| A25 | An incomplete attempt writes `dataset.incomplete.json` and no `dataset.json`; workspace resume and batch plans behave as before (D24) | S6 |
| A26 | Importing needs the acknowledgment; the preview counts converted, failed and pending separately; converted units arrive with layers; failed rows get `conversion_failed` and pending rows `conversion_pending`, each with the original diagnostic code and message; `diagnostics.jsonl` is unchanged and its SHA-256 recorded; the import and its layers are marked incomplete and never shown as complete | S6 |
| A27 | Once the dataset completes, its import adds the remaining units as a new snapshot, without duplicate items, layers or registrations | S6 |
| A28 | A project `completed_with_errors` run registers its converted series only through the explicit control; registration is idempotent; Retry failed registers the rest later | S6 |
| A29 | Rollback: the previous release ignores `dataset.incomplete.json` and does not treat the dataset as sealed | S6 |
| A30 | 1, 2, 4 and 8 workers produce identical bytes, row order and annotations, and the same set of item outcomes | S7 |
| A31 | A worker SIGKILL or native fault marks the unit `crashed`, retries it, then fails it as `worker_crashed`; other units complete; no duplicate output | S7 |
| A32 | A parent SIGKILL leaves no orphan (process-group scan); a resume completes cleanly | S7 |
| A33 | The total memory budget holds (sum of admitted shares); an oversized unit waits with its remedy while the others proceed; the per-worker soft `RLIMIT_AS` is enforced | S7 |
| A34 | App: the owned cleanup proof includes the workers (D17); cancel meets P05; admission and fencing are unchanged | S7 |
| A35 | CLI signals follow §Interruption semantics | S7 |
| A36 | The ETA signature includes the worker count; `bytes_per_s` uses wall-clock attempt time | S7 |

## Release gates

DCM-26..34 are `S`, so this feature is not a v3.0 release dependency. Releasing the standalone converter requires all of these to pass on the release revision, in addition to DICOM_JOB_TEST_PLAN D17–D24, D28, D29, D34 and D35:

| Gate | Cases |
|---|---|
| Correctness | A01, A02, A09, A16, A30 |
| Integrity | A18–A21, A24, A31 |
| Privacy | A05, A06 |
| Recovery | A04, A15, A22, A32–A35 |
| Backward compatibility | A03, A07, A08, A13, A14 |
| Incomplete datasets | A25–A29 |
| Scale | A17, A33 |

## Interruption semantics (DCM-33; app behavior unchanged, ADR-0035)

| Event | Standalone | ct_viewer |
|---|---|---|
| Terminal or SSH closed | SIGHUP is handled as a graceful stop and nothing more is written to the terminal; for sessions that must outlive the terminal: tmux, screen, nohup, `systemd-run --user` | The server keeps running; the browser reconnects by operation ID |
| Graceful cancel | Dispatch stops; in-flight units finish within the grace period; a second signal stops them | Durable Cancel (DCM-18) |
| Process terminated (SIGTERM) | As graceful cancel, then SIGTERM and finally SIGKILL to workers | Container stop: see server restart |
| One worker killed | Unit `crashed`, retried once; the other units continue | Same, inside the attempt |
| Parent killed (SIGKILL) | Workers die via PDEATHSIG; the next run resumes and adopts prepared commits | Owned group dies; fenced resume |
| Server restart | n/a | Reconcile; never re-run automatically |
| Machine restart or power loss | Only fsynced records count; anything else is reconverted | Same unit protocol; a changed `boot_id` counts as cleaned up |

## Benchmarks (B)

| Case | Measurement |
|---|---|
| B01 | Discovery: files/s for new and reused reads; walk, header read, parse and SQLite time; small, medium and large datasets and the scaling sweeps |
| B02 | Conversion: series/s and MB/s; per-series latency p50, p90 and max by class (slices, codec); time to first committed output |
| B03 | Per-unit cost split: hash, decode, raw write, compression, validation, sidecar, publish, fsync |
| B04 | Resume: time from start to the first pending conversion; source and output bytes read; against dataset size |
| B05 | Resources: peak RSS per process (`getrusage` of children), CPU utilization, peak temporary disk, source and output I/O (`/proc/<pid>/io` in the harness) |
| B06 | The same B01–B05 per file-system lane |
| B07 | S7 sweep: workers 1/2/4/8 × file-system lane; failure and recovery timing; output-equivalence digests |

- **Datasets:** small (one study), medium (about 10⁴ files and 10² series), large (at least 2×10⁵ files and 10³ series, synthetic plus the reference trees in DICOM_JOB_PLAN), and the scaling series.
- **Cache conditions:**
  - Warm: repeated runs.
  - Cold for source pages: `posix_fadvise(POSIX_FADV_DONTNEED)` on every source file, which needs no root. Directory metadata caches stay warm; report that.
  - Full `drop_caches`: only on local hosts with root (R4).
- **Method:** alternate configurations in pairs, at least 3 repetitions, report median and spread.
  - Pin to each result: code revision, lock hash, settings, CPU affinity, memory limit, file system and worker count.
  - Set no targets before the S1 baseline. P03 in DICOM_JOB_TEST_PLAN (no conversion-throughput regression above 10%) stays in force.
