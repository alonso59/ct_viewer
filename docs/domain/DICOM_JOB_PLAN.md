# DICOM source operations: implementation plan

Scope: accepted design and implementation work for fast, complete DICOM discovery, dry run, conversion and verified continuation after interruption, with/without a project.
Read when: implementing or reviewing the DICOM explorer/converter improvements requested on 2026-10-23.
Depends: DICOM_CONVERTER.md, SOURCES.md, TASKS.md, ANALYZERS.md, ../ops/DICOM_JOB_TEST_PLAN.md, ADR-0035.

## Status and boundaries

Owner workflow update (2026-10-25): finish the missing implementation first, then add focused local verification. Run the complete regression in GitHub CI; do not repeat it locally. This changes the implementation/test order below, without relaxing ADR-0035 safety or recovery requirements.

Implementation authorized on 2026-10-23: the owner requested implementation of this plan/tests and compliance with ADR-0035, now Accepted. Implementation/test evidence is tracked below; acceptance alone does not certify behavior, production readiness or phase completion. Interruption/resume is required. P7g's existing closure gates remain separate; this plan does not open Electron or SLURM work.

Reuse `dicom.convert`, SimpleITK/GDCM, `ConverterOverlay`, the job manager and project/workspace run registries. Keep CLI compatibility, source immutability, contract-v1 metadata, identity rules and existing output layouts. Other formats keep their import behavior; their long-running discovery/indexing gets the shared minimize/reconnect control where applicable. Do not couple DICOM work to the GPU runner.

## Inspection evidence (2026-10-23; not acceptance)

| Area | Current behavior / consequence |
|---|---|
| TCGA source | Read-only enumeration of `../data/tcga_kirc`: 141,164 `.dcm`, 2,523 directories including root, 1,919 directories containing files; all files at folder depth 3, no symlink directories/errors. Folder count is not a verified series count. |
| General detector | `sources/formats.py` found all 141,164 files, no truncation, in 20.08 s in one observation. `sorted(rglob)` materializes the tree before the 200,000-candidate limit, which also counts directories. This is not a controlled performance baseline. |
| Open mode | `sources/open.accepted` cuts to 500 files before `dicom_stage.probe_series`; the first 500 span 8 leaf folders and incompletely include one. The remaining 140,664 files never reach grouping. |
| Recognition | Picker regex excludes extensionless/`.ima`; detector accepts those only with `DICM`, ignores `.dicom`/`.001`, and trusts `.dcm`. Converter accepts additional header starts. In-memory probes confirmed the mismatch, not full format compatibility. |
| Background | Converter store survives minimize/navigation but not browser reload. Dry-run scratch/result is deleted when its HTTP request finishes. Open/import discovery lacks the same operation lifecycle. |
| Cancellation/resume | Shared builtin pool + coarse cancellation checks cannot establish bounded native-reader cleanup. Project/workspace paths have different lifecycle code; output existence is insufficient for safe resume. |
| Phase | `pipeline.run` calls phase rules even when `task.py` later drops their annotations. ADR-0020 already places phase in a separate layer. |

## Expected user behavior

One reusable floating work window: source → discovery → settings/dry run → conversion → result. `Import data` hands DICOM to this window with its original project/path; `Convert DICOM to NIfTI` enters it directly. Open-mode folder discovery uses its recoverable progress surface; importing NIfTI/metadata still uses its existing adapter wizard, without forcing conversion.

The window shows folders visited, files examined, DICOM confirmed, rejected/unreadable candidates, complete series found, selected/skipped series and reasons, estimated bytes, elapsed time and ETA basis/range. Counts remain provisional until discovery completes; files, frames and series have separate units. Unknown totals use an indeterminate bar, not a fabricated percentage. Conversion progress counts committed series, with current-stage progress separate from overall progress.

Header controls: Minimize / Restore / Cancel. During work, ×/Escape minimize; outside clicks do not discard it. A floating compact panel shows stage, counts, progress and Restore/Cancel. Reload/another tab retrieves active/recent operations from the server; local storage is not the job authority. Multiple operations are listed; opening another source cannot silently replace running work. Keyboard focus, screen-reader progress and Dark/Light layouts are covered by tests.

Interrupted/cancelled/partially failed results show Resume pending, Retry failed, completed/pending/failed counts, last interruption reason and output destination. Cancel does not erase committed outputs; closing results is distinct from cancelling. A completed conversion may still report an analyzer failure, with Retry analyzer only.

## Contracts (ADR-0035; implementation in ordered waves)

### Durable records and authority

Store source operations below `WORKSPACE_ROOT/plugins/dicom/operations/{operation_id}/`, inventories under a managed workspace cache, and durable attempt/checkpoint records beside the operation/run. No records go into input roots. No hidden project. Persist version, opaque ID, source ref, project-or-workspace context, normalized settings hash, inventory/plan generations, linked run ID, attempt generation, control request/ack, progress revision, timestamps, last error and cleanup evidence. Native worker events are fenced by attempt generation; only the API writer mutates authoritative records under existing locks.

The operation owns discovery/estimate state and links the existing conversion run, whose record remains authoritative for conversion/output registration. Do not maintain competing run statuses in two registries. Start requests use a persisted idempotency key; duplicate clicks/retries return the original operation/run. Keep one active conversion per existing task exclusivity key; cross-context jobs also share global resource admission.

Operation stages: discovering → planning → ready → converting → registering → optional analyzing → result. Execution states: queued/running/cancelling/completed/completed_with_errors/cancelled/interrupted/failed/cleanup_pending. `ready` means plan prepared, not conversion authorized. Wave 0 adds operation-specific enums; shared segmentation/radiomics states change only if required and regression-tested.

### API evolution

Additive routes: `POST /source-operations` (body contains path/context/purpose; 202 after durable write), `GET /source-operations[/{id}]`, `GET /source-operations/{id}/series`, `GET .../plan`, `POST .../estimate`, `POST .../convert`, `POST .../cancel`, `POST .../resume`, `POST .../retry-failed`. Series/plan reads use stable generation-bound cursors and bounded pages. Commands include expected revision/attempt; stale incompatible controls return problem+json/409.

`POST /sources/detect`, `POST /open`, API-44 and API-62 synchronous estimate responses remain compatible adapters over the shared services; they do not change response type silently. New UI uses asynchronous routes. Public HTTP paths/cursors never embed patient filesystem paths. SSE carries opaque IDs/revisions and small counters; reconnect refetches durable state, with polling fallback for workspace operations. View-only links cannot create/control operations and must not expose workspace inventories.

### Discovery and inventory

Use a streamed `scandir`/`os.walk` traversal, prune excluded directories before descent, and check cancellation between bounded batches. Centralize recognition as a plugin scan primitive reached by backend services through `app/tasks/`; plugins never import `app`. For mixed-format discovery retain existing NIfTI/NumPy classification. Extension is a hint: unknown/absent suffix candidates receive bounded DICOM header validation; reject random bytes and malformed/non-image objects with reasons. Include preamble-less input variants supported by the actual reader; validate compatibility with GDCM, not just a magic-byte predicate.

Apply containment guards to every descendant read, reject symlink escapes, prevent cycles, and diagnose unreadable paths. Keep resource/hidden-folder exclusions explicit and consistent across entry points. Large headers/private sequences have configurable read/allocation bounds and actionable diagnostics; do not read a whole huge object merely to search blindly for PixelData bytes.

Persist bounded inventory batches with source-relative file paths, stat signature and parsed grouping/geometry facts. Group consistently by directory + SeriesInstanceUID, preserving current behavior; flag identical UIDs spread across folders instead of silently merging stacks. Stable case/scan identity is assigned through the existing registry, independently of discovery scheduling. Duplicate SOP instances and missing identity require diagnostics, not silent deduplication or accidental case merging.

Browse paged complete series; fetching a page never truncates a series' member list. Keep a configurable series/page budget and inventory byte budget instead of a slice-count cutoff. Open mode loads/converts a complete chosen series lazily and preserves its existing cache/attach/Save-as contracts. Any inventory limit yields an explicit partial state and a way to continue, never a complete-looking result.

Reuse inventory for dry run and conversion. Restat directory/file manifests and rescan changed branches; additions, deletions, rename, changed settings or scanner version invalidate the appropriate plan generation. Restat is a fast invalidation mechanism, not proof of identical content. A resumed conversion verifies the pinned strong input manifest (see below). Old inventories are retained while referenced by active/recoverable work; bounded cache eviction cannot delete active plans/checkpoints.

### Dry run, ETA and resources

Dry run reads headers and returns every planned/skipped series through paging; no pixel decoding, NIfTI writes or source changes. Unknown/bad series are reported, not counted as successfully inspected. Planned role/geometry decisions must match conversion for the same generation/settings. `already complete`, `pending`, `failed` and `skip` are distinct; ETA/bytes cover remaining work on resume, with cumulative totals also visible.

Persist measured discovery/conversion/registration/analyzer durations locally, keyed by execution environment, storage root signature, reader/plugin versions, compression/geometry class and effective concurrency. Before conversion show a range from sufficient compatible history, with sample count, basis and confidence; otherwise show Unknown. Never call header-scan duration a conversion-time estimate. No hidden pixel calibration in Estimate. Update remaining-time estimates after committed series, excluding paused/disconnected time and already complete output. Analyzer time is separate; do not fabricate precision for rare codecs or zero-progress jobs.

John CPU budget is at most 12 across admitted work, including ITK/numerical threads and scan workers, not 12 per operation. Start conservatively (one conversion unit; bounded header workers), benchmark before raising concurrency. The segmentation runner's configured memory limit is not automatically a DICOM entitlement: use an explicit conservative DICOM/global memory budget, estimate per-series peak memory and queue oversized work with an actionable reason. Keep API volumes out of memory (BE-12), preserve responsiveness of unrelated jobs; GPU allocation is untouched.

Wave 0 freezes validated deployment settings for CPU/memory admission, header-byte/inventory-byte limits, queue/batch sizes, cleanup deadline and retention. Count the application's external runner reservations in admission; when their usage cannot be reconciled, serialize DICOM conversion behind those reservations rather than oversubscribing. These are application budgets, not claims to control other server users. Keep at most one conversion process by default; absent a usable memory budget, allow read-only discovery/planning and refuse pixel conversion with a configuration remedy. Never infer permission to consume all host RAM from reported free memory.

### Cancellation, interruption and verified resume

Use DICOM-specific owned worker processes inside the existing OCI image (ADR-0035); the shared API/job driver tracks them. Do not terminate the shared pool, host runner or unrelated PIDs. A cancelled future is not cleanup evidence. Acknowledged controls are durable; no new unit dispatches after cancel. Proposed healthy-host bounds: control response ≤1 s, cooperative stop at the next bounded checkpoint, escalation/owned-process cleanup ≤30 s. An uninterruptible I/O process remains cleanup_pending; block replacement attempts and report it honestly.

On restart, reconcile records/owned execution before setting interrupted and enabling resume; do not launch automatically or overlap a surviving writer. Resume uses the same logical operation/run/output allocation, a fresh fenced attempt and the original case/scan registry. It resumes verified inventory batches when valid, otherwise rescans affected branches; there is no assumption that a half-read header is resumable.

Each series commit records pinned input identity/content digests, settings/reader versions, output digest/size/geometry, sidecar state and registration state. Stream hashes in workers and cache completed manifests; no up-front full-dataset hash for discovery/Estimate. On resume verify strong selected-input digests and committed output hashes/geometry; matching timestamps alone never authorize reuse. Missing/changed inputs, output corruption, profile/anonymization changes or incompatible versions return a precise conflict and offer a new operation. Added files/series require explicit plan refresh/new generation; they are not silently appended to a pinned conversion.

Order publication: prepare under attempt-owned staging → validate pixels/geometry/metadata → publish a complete series artifact set without overwrite → durably record commit → idempotent registration. Use no-clobber publication, not check-exists then replace. Crash between any two steps must be reconcilable: adopt a validated matching orphan exactly once or quarantine an incomplete artifact in the owned derived area before explicit retry; never treat `.nii.gz` existence alone as completion. Old successful outputs and input roots are immutable. No `_datasets/name-1` allocation on resume; completed datasets remain sealed.

Partial metadata is recoverable state, not a complete dataset advertisement. Expose committed rows and actual counts on cancel/failure; only complete artifact manifests become discoverable as a ready dataset. Project import/index registration has durable idempotency markers so restart cannot duplicate imports, rows or annotations. Resume skips complete validated series, restarts partial series from their beginning, and Retry failed targets only recorded failures. Another resume/cancel request cannot create a second active attempt.

Phase stays optional and separate (ADR-0020): remove phase inference from core conversion and run the same analyzer rules as an independently checkpointed post-conversion step. Keep target/readiness selection in dry run/conversion as specified by ANZ-02; keep metadata clean. Preserve default phase-on behavior and effective-phase precedence; failed analyzer retry never reconverts images.

## Modification map

The implemented modules follow the planned service layering and one authoritative lifecycle.

| Area / files | Planned change | Expected behavior / primary cases in test plan |
|---|---|---|
| `plugins/dicom/{files,scan}.py` | Stream candidates, shared recognition/grouping, bounded header facts, cancellation hooks | D01–D07, D10–D12 |
| `backend/app/sources/{formats,detect,open,open_service}.py`; `tasks/dicom_stage.py` | Guarded shared inventory adapter, asynchronous open/discovery, complete-series paging | D01–D09, D30–D31 |
| `backend/app/tasks/{source_operations,source_inventory,source_import}.py`; `core/fsio.py` as needed | Durable records, cache generations, atomic controls/idempotency, retention | D10–D17, D22–D24, D32–D33 |
| `backend/app/tasks/{estimate,dry_run,workspace_runs,models}.py`; `dicom_eta.py`, `dicom_timings.py` | Durable header-only dry runs, full plan paging, measured ETA, workspace parity | D12–D15, D25–D26, D32 |
| `backend/app/tasks/{driver,service,registration,records}.py`; `jobs/{manager,runs,types}.py`; `dicom_worker.py` | Reuse run records; dedicated owned DICOM execution/admission; explicit cancellation, recovery and resume | D16–D24, D27–D29; all shared-runtime regressions |
| `backend/app/config.py`; deployment configuration and startup validation | Validated DICOM budgets, existing runner reservation accounting, queue/retention/deadline settings; safe defaults without global runtime changes | D07, D27, D32; configuration/startup regressions |
| `plugins/dicom/{pipeline,convert,task,cli}.py`; analyzers task adapter | Consume pinned plan, commit/checkpoint per series, no-clobber output, separate phase step | D18–D29, D34–D35 |
| `backend/app/api/v1/{sources,tasks}.py`; operation router, context/main wiring | Add asynchronous operation API, controls and paging; retain compatibility | D08–D09, D13–D17, D24, D30–D33 |
| `frontend/src/plugins/dicom/{ConverterOverlay,store,index}.ts(x)`, `converter.css`; extracted progress/plan components | Existing window hosts operation selection, metrics, minimize/reconnect/resume/retry | U01–U12; B01–B08 |
| `frontend/src/features/import/{ImportWizard,FolderBrowser,store}.ts(x)`; `open/{OpenDialog,OpenRoute,store}.ts(x)` | DICOM handoff, content-based selection, persistent long-load surface; preserve other adapters | U02–U04, U08–U10; B01–B04, B08 |
| `frontend/src/api/{http,surface,types,hooks,keys}.ts`, generated `schema.d.ts`; i18n/theme/lib only where needed | Typed operation APIs, SSE/refetch/polling, status/ETA/cancel vocabulary | U05–U12; API/schema/recording regressions |
| Test generators/fixtures, Makefile, `.github/workflows/verify.yml`, image smoke | Synthetic fixtures, process/restart lanes, benchmarks and image verification | All gates in test plan; never upload real data |

## Ordered tests-first waves

| Wave | Red tests first | Implementation / exit |
|---|---|---|
| 0 — contract/baseline | Capture current failures D01/D02/D03/D16/D20; run existing relevant suites; record dependency/CI state | Accept ADR-0035 before changing runtime/contract; update owner specs with additive IDs and API schema, freeze semantics/baselines. Do not accept a failing baseline as a new regression's cause without evidence. |
| 1 — complete discovery | D01–D09, D34 | Shared recognition + streamed traversal + complete-series reads; old source/geometry/CLI suites green. |
| 2 — durable inventory/dry run | D10–D15, D30–D33 | Async operation records/paging, cached plan validation, compatible legacy endpoints; interruption leaves recoverable records. |
| 3 — execution/recovery | D16–D24, D27–D29, D35 | Owned process cancellation, no-clobber commits, same-run resume for both contexts, idempotent registration; unrelated jobs survive. |
| 4 — existing window | U01–U12 then B01–B08 | Shared entry points, minimized progress, reload recovery, resume/retry, real backend both-browser acceptance. |
| 5 — ETA/throughput | D25–D26, performance matrix | Compatible historical ETA + measured updates; resource admission + benchmark-selected concurrency. |
| 6 — release verification | Full regression/environment gates | All required evidence reviewed; build one image, Docker/udocker acceptance, deploy same verified tree with rollback. Not authorized by this planning task. |

## Specification ownership and release boundary

On Wave 0 acceptance, change behavior only in its owner and cite it from tests: SOURCES (SRC-01/02/09/13 and complete-series paging); DICOM_CONVERTER (DCM-01..07/09/13/14 plus inventory/resume commits); TASKS (TSK-05..10/13 and source-operation lifecycle); ANALYZERS (ANZ-01..08 phase chaining); backend ARCHITECTURE (BE-02/03/05/06/10/12/13 and DICOM process exception); API (API-07/19/44/62 plus additive operation IDs); UI_SHELL (UI-25 and long-import/Open progress); TESTING (TST-03/05/07/10/13..16/20, new lifecycle coverage). Do not redefine those requirements in this plan or mark them implemented during planning.

Closure requires every acceptance case in the companion test plan to have a real test/evidence link, no mandatory skips, explicit performance measurements, complete source immutability/geometry evidence, and passing product-image checks. Synthetic API/UI tests cannot certify restart cleanup; a UI countdown cannot certify ETA accuracy; listing leaf folders cannot certify series completeness. Open evidence stays open. Code review, publication and production rollout are separate from this plan.

## Implementation evidence

Current state (2026-10-27). The accepted contract and companion D/U/B/P matrix remain the scope.
Evidence under `build/verification/` is local and ignored; real patient paths/pixels are never published.
A narrow pass certifies only its stated coverage. Superseded checkpoints remain in Git.

### Functional implementation

| Area / matrix portions | Implemented behavior | Decisive evidence |
|---|---|---|
| Discovery / D01–D07, D10–D12 | Streamed guarded traversal; suffix-independent bounded headers; complete directory+UID groups; durable SQLite batches and generation invalidation; typed bad/missing/duplicate identity diagnostics and cross-folder UID warning. | `test_dicom_discovery.py`, `test_dicom_scan.py`, `test_source_inventory.py`, `test_dicom_identity.py`; actual 750-slice geometry, 12 independent GDCM mixed-UID/encoding cases (implicit/explicit little-endian, big-endian, deflated, RLE and JPEG 2000 lossless) and two native enhanced CT/MR geometry cases. |
| Operations / D08–D16, D32–D33 | Durable start/control receipts, fenced attempts/revisions, generation-paged reads, retained results, restart reconciliation, shared Open/import/conversion window. | `test_source_operations_api.py`, `test_dicom_operation_recovery.py`, `test_dicom_progress.py`, `test_source_detection.py`; real SIGKILL inventory/header tests and recorded frontend exchanges. |
| Open / D02, D09, D31, U08 | Complete chosen series, later pages, lazy hydration, attached masks and Save; retained geometry/stat pins refuse changed or lost dependencies. | `test_open_paging.py`, `test_source_open.py`, `test_source_operations_api.py`, `test_open_convert_once.py`; Open/background/paging Chromium and Firefox journeys. Same-stat rewrites are outside the stat-based hydration check. |
| Import continuation / U02, U06, B04/B08 portions | Server-retained form edits, Preview, commit identity and Index; minimize/reload/cancel/resume; explicit project selection; reused snapshots; lightweight polling, damaged-preview repreparation and cancellation through the Index handoff. | `test_source_import_context.py`, `ImportWizard.test.tsx`, `Host.test.tsx`, `import-background.spec.ts`, `p2-flow.spec.ts`; 37 affected backend/API cases pass, including parser responsiveness, one NIfTI scan and deterministic finalization barriers. |
| Native lifecycle / D17–D24 | Owned process/descendant cleanup, durable control handoff, same logical run/destination, verified pending/failed-only retry, source/settings/output conflict refusal and no-clobber publication. | `test_dicom_process_lifecycle.py`, `test_dicom_resume.py`, `test_dicom_retry_failed.py`, `test_source_operation_conversion.py`, `test_dicom_operation_recovery.py`; four API-SIGKILL cases inside actual ITK writer callbacks, at progress 0/1 in project/workspace scopes, verify parent-death cleanup, resume, unchanged completed bytes/mtime, landmarks and one registration. The full crash/platform matrix is not inferred from these cases. |
| Metadata registration / D18–D24, D35 | Durable metadata journals; directory sync before success; idempotent import/annotation publication; completed registration waits for a successful index; recovery does not block polling. | `test_dicom_metadata_durability.py`, `test_dicom_registration.py`, `test_dicom_registration_cancel.py`, `test_dicom_publication.py`; ENOSPC and interrupted registration cases. |
| Resources and retention / D07, D27, D32 | Explicit DICOM budgets, native affinity/address-space bounds, shared participating allocation, aggregate SQLite quota and conservative completed-history retention; recoverable drafts/Open sessions and corrupt evidence remain protected. | `test_dicom_resources.py`, `test_dicom_admission.py`, `test_dicom_inventory_policy.py`; production pool device/inode matches its fresh runner. Cross-container/multi-workspace host acceptance remains separate. |
| Phase / D29 | Separate recorded analyzer after successful native commits; off executes no phase rules; phase-only retry preserves converted images and manual annotations. | `test_dicom_phase_runs.py`, `test_dicom_phase_step.py`, `test_metadata_ownership.py`, existing phase/analyzer suites; bounded private input checkpoints and retry conflict cases. |
| ETA and measurements / D25–D26 | Compatible bounded conversion history, minimum observations, unknown/low confidence, remaining verified work and no pixel calibration. Active discovery/planning/registration/analysis durations have idempotent bounded history; queue/downtime is excluded. | `test_dicom_eta.py`, `test_dicom_timings.py`: 39 timing/ETA cases and 13 final stage/identity cases pass, including real project/workspace pipelines. Reference calibration remains open. |
| Compatibility / D30–D31, D34 | Legacy HTTP/CLI response contracts, existing YAML/defaults, clean metadata and layer ownership, view-only redaction, source immutability and service/plugin boundaries. | `test_contract.py`, `test_dicom_cli_resume.py`, `test_metadata_ownership.py`, `test_view_redact.py`, `test_layering.py`; full published-tree CI and both-browser suite. |

Native API recovery: `dicom-active-writer-api-recovery-v2.log`, four real ITK Execute barriers at
progress 0/1, project/workspace scopes; owned group gone, completed bytes/mtime unchanged, one registration.
`converter-recovery.spec.ts` adds eight Chromium/Firefox cases: project/workspace × cancel/API death,
actual native callback, second tab, minimized reload, both themes, fresh browser-context restore and resume.
`dicom-native-browser-final-matrix.log` passes 8/8; the final port-reservation cleanup passes its focused
crash case (`dicom-native-browser-after-cleanup.log`); four original host recovery cases still pass.
These deterministic barriers do not certify every blocked-I/O or crash point.

### Publication and packaged runtime

- Production john:5180 runs `29bac01`, tree `b760c138663c2b9f3d26d19fdf826707339fb8b7`, image
  `85745aa64356ea0f:verification`. CI `40371515442` passed 1,200 backend, 431 frontend,
  108 serial runner and 76 browser tests. Non-root uid-1008 same-image udocker conversion,
  queued API SIGKILL/restart, cancel/resume and restored Open preserve source/output hashes
  (`dicom-product-29bac01/acceptance.json`). No GPU workload was launched.
- Published `63b8869` adds test/docs only; CI `40376987867` passed 1,209 backend, 431 frontend,
  108 serial runner and 76 browser tests, plus image/static/contract gates. Twelve native codec cases
  cover implicit/explicit LE, BE, deflated, RLE and JPEG 2000 lossless, with independent GDCM geometry.
  Four damaged/unsupported-record cases preserve original bytes, refuse recovery actionably and permit fresh work.
- Drained same-image rollback/forward `29bac01` → `50d83ca` → `29bac01` preserves two restored Open
  images, one run and all source/derived bytes (`dicom-product-29bac01/rollback-acceptance.json`).
  This proves drained format compatibility, not active-record migration or cross-PID cleanup.
- Two uid-1008 udocker workspaces sharing one pool pass inventory admission, API-death cleanup,
  restart/resume, conservative lease recovery and unrelated-process survival on the preceding `8a77665`
  image (`dicom-product-8a77665/multi-workspace-acceptance/result.json`); same host PID namespace only.
- Full TCGA read-only headers: 141,164 files / 1,919 series / 2,523 folders exactly match independent
  GDCM membership and physical ordering (`dicom-tcga-membership-oracle/result.json`). Source stat signatures
  unchanged. The 1-GiB inventory limit stopped explicitly at 95,552 files; 2 GiB resumed retained batches.
  Final DB 392 MB; four 500-series pages 0.25–0.40 s. Production inventory/aggregate ceilings are 2 GiB;
  DICOM memory admission remains 8 GiB. Drain, backup and release records live with the deployment.
- Claude cleanup was fast-forwarded at `4eb56a9`; 44 focused merge cases passed and its worktree/branch
  were removed. Earlier main-tree edits remain in stash `c3427bad`; unrelated untracked scripts stay untouched.

### Performance and independent pixel evidence

| Measurement | Result and scope |
|---|---|
| P01/P05, three read-only TCGA samples, four assigned CPUs | Start 5–38 ms; first progress 0.73–0.86 s; cancel acknowledgment 2.0–2.5 ms; verified cleanup 0.16–0.19 s, owned group gone and sentinel alive (`dicom-reference-controls-v3/result.json`). Header/listing control only. |
| P02, same 141,164-file enumeration membership hash, three alternating warm pairs | Old median 18.70 s; streamed 6.66 s (2.81×), four assigned CPUs, no cache resets (`dicom-enumeration-benchmark.json`). Not pixel throughput. |
| P04, disposable API, 201,128 entries / 1,005 series | Complete inventory 37.2 s; three 500-series pages 82–121 ms, no duplicates/missing series. API RSS 201.1→202.3 MiB; worker 187.4 MiB; source image hashes unchanged (`dicom-large-api-inventory/result.json`). No pixel conversion. |
| P04 NFR-04/08 reference index/cache | Four 10,000-item projects remain cached after normal indexing jobs: API idle 480,047,104 bytes, then 492,720,128 bytes after Explorer use (limit 500,000,000); 1,000-item index 1.136 s (limit 60 s). Reference payload 512×512×600 int16, 241,781,469 compressed bytes; warm local SSD, hardlinked shared payload with distinct item metadata, 4 CPU affinity, 2 workers/native threads 1, `ARROW_DEFAULT_MEMORY_POOL=system`. Full source membership/stat/unique-inode hashes unchanged. `dicom-nfr-reference-system.log`, private `/tmp/rw-dicom-nfr-system-qds6v57g/result.json` and `dicom-nfr-system-post-explorer.json` pin the measured settings/code. No forced GC, reduced cache or cache reset. Earlier allocator measurements exceeded the idle limit; this does not certify cold distinct-volume throughput. |
| P04 NFR-03 Explorer | Compiled SPA, Chromium 153/software GL, 10,000 items/2,500 cases: five filter interactions ≤26.2 ms and seven scroll interactions ≤74.3 ms, at most 28 mounted rows; no external requests/page errors (`dicom-nfr-explorer-system.json`). Local case/patient text matching preserves shared conditions, counts and navigation; 23 affected frontend cases pass. The prior server-round-trip measurements failed the 100-ms target and were superseded by this implementation. |
| P04 exact packaged reference, two 512×512×600 int16 CT volumes | Same production image, uid 1008, 8-GiB admission confirmed from actual worker kernel limits; sampled API 216.9 MiB, pixel worker 1,091.4 MiB. Full shape, marker world coordinates, queued API death/cancel/resume, Open restore and source/output hashes pass (`dicom-reference-600-image/state/reference-600-result.json`). Not active native/cross-PID death. |
| P03, five distinct-patient real TCGA CT series, 64 slices each | Three alternating warm pairs: current median 3.764 s versus principal 8.569 s (56.1% faster); outputs +14.20%. All voxels/affines match independent GDCM and source header geometry; full source SHA/directory metadata unchanged (`dicom-tcga-pixel-reference/result.json`). Four CPUs, native threads 1, private 8-GiB address-space cap; outputs removed afterward. |
| P03, five distinct-patient real TCGA CTs, 64/128/256/399/559 slices | Three alternating warm pairs: 15.300 s versus principal 23.445 s (34.74% faster); outputs +5.68%. All voxels/affines/source header geometry match; full source SHA/directory metadata unchanged (`dicom-tcga-pixel-reference-large/result.json`). Four CPUs, native threads 1; benchmark-only 16-GiB cap includes independent oracles, measured process peak 2,193.6 MiB. Production remains 8 GiB. |
| P03, synthetic native/RLE/JPEG 2000 lossless CT, three 512×512×96 volumes | Three alternating pairs: current 7.11 s versus principal 12.33 s (42.3% faster), output +1.79%, equal voxels/affines and unchanged source hashes (`dicom-mixed-codec-principal-benchmark.json`). Four CPUs, variation below 1%, no cache reset. |
| P06, synthetic 512×512 CT, 64–120 slices, native/RLE/JPEG 2000 lossless | Five training observations per codec followed by nine frozen hold-outs: 9/9 covered, mean relative error 1.25%, range width 54.3%; voxel/affine/source hashes match, process peak 705 MiB (`dicom-eta-codec-holdout/result.json`). Training flushed before forecasts; hold-outs never train. Unseen classes remain unknown/low confidence. |

The guarded ISA-L level-2 writer retains source SHA, CRC, geometry and no-clobber checks; one raw-volume
scratch file and the measured larger gzip outputs are explicit tradeoffs. Fresh units reuse complete
preflight manifests and rehash after decoding; recovered units undergo full stream validation.
Earlier 25% and 17.7% overhead experiments were superseded, without weakening verification.
The native RLE oracle uses 64×64; 4×3/4×4 fixtures are rejected by the installed native reader even
though pydicom can decode them. Real TCGA pixel measurements cover regular Explicit-VR LE CT;
they do not certify every codec/storage/pathology class. Private clinical outputs were removed.

### Remaining closure gates

The plan remains open until the full companion matrix is audited with evidence, especially:

- Complete the per-case evidence audit. Existing real SIGKILL coverage includes staging/image/sidecar/commit/progress and eleven registration/Index barriers (`test_dicom_operation_recovery.py`); registration cancellation has separate durable-acknowledgment cases. Remaining analyzer/CLI paths must be mapped individually rather than inferred from filenames.
- Remaining B04–B08 branches in both browsers: active scan/estimate recovery,
  stage-specific cancellation and partial pixel/phase failures. B01 deep project import passes in both browsers, including extensionless/IMA files, minimize/navigation/restore and indexed results (`dicom-import-deep-browser-fixed-root.log`). B02 result Open and Add-to-existing pass in both browsers (`dicom-result-open-browser-final.log`, `dicom-result-branches-browser-fixed-key.log`); Create was already covered. B03 passes in both browsers: 503 DICOM series/2,274 files, later-page selection of all 750 slices, exact independent GDCM membership, full voxel/affine/marker oracle, paged identities without gaps, converter handoff and truthful minimum-size skips (`dicom-large-series-browser-summary.log`). Active scanning minimization remains a separate branch. The eight native recovery cases above cover portions.
- Pixel ownership/accounting/cleanup across distinct Docker PID namespaces and multi-workspace workloads;
  existing same-namespace inventory proof is narrower. Never relax an unverified cleanup fence.
- P04 NFR-03/04/08 now pass at the recorded reference workload and allocator setting; final image must retain that setting. P06 has frozen native/RLE/JPEG-2000 hold-out evidence; unsupported classes retain unknown estimates. Windows Docker and actual Safari remain unavailable platform lanes.
- Full CI and same-image Docker/udocker acceptance for the segmentation editor, inspector and memory fixes before rollout. Published `3cec8b2` includes the deterministic cancellation barrier and B01/B02 journeys; CI `40541772503` passed full static/unit/contract checks and serial runner safety and is still running the browser gate. The local Explorer, allocator and B03 follow-up requires publication and final image acceptance.
  Rollback requires compatible readers or a drained metadata snapshot, never an assumed migration.
