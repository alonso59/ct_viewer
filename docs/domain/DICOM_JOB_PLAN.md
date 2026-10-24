# DICOM source operations: implementation plan

Scope: accepted design and implementation work for fast, complete DICOM discovery, dry run, conversion and verified continuation after interruption, with/without a project.
Read when: implementing or reviewing the DICOM explorer/converter improvements requested on 2026-10-23.
Depends: DICOM_CONVERTER.md, SOURCES.md, TASKS.md, ANALYZERS.md, ../ops/DICOM_JOB_TEST_PLAN.md, ADR-0035.

## Status and boundaries

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

New filenames below are proposed modules, not existing code. Keep service layering and one authoritative lifecycle.

| Area / files | Planned change | Expected behavior / primary cases in test plan |
|---|---|---|
| `plugins/dicom/scan.py`; new `plugins/dicom/inventory.py` | Stream candidates, shared recognition/grouping, bounded header facts, cancellation hooks | D01–D07, D10–D12 |
| `backend/app/sources/{formats,detect,open,open_service}.py`; `tasks/dicom_stage.py` | Guarded shared inventory adapter, asynchronous open/discovery, complete-series paging | D01–D09, D30–D31 |
| New `backend/app/tasks/{source_operations,source_inventory}.py`; `core/fsio.py` as needed | Durable records, cache generations, atomic controls/idempotency, retention | D10–D17, D22–D24, D32–D33 |
| `backend/app/tasks/{estimate,dry_run,workspace_runs,models}.py`; new `dicom_eta.py` | Durable header-only dry runs, full plan paging, measured ETA, workspace parity | D12–D15, D25–D26, D32 |
| `backend/app/tasks/{driver,service,registration,records}.py`; `jobs/{manager,runs,types}.py`; new `dicom_worker.py` | Reuse run records; dedicated owned DICOM execution/admission; explicit cancellation, recovery and resume | D16–D24, D27–D29; all shared-runtime regressions |
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

Artifacts below are ignored files under `build/verification/`.
Synthetic tests use temporary workspace/derived roots and CPU workers; no GPU inference was launched.
This implementation is a development checkpoint; production rollout remains pending.
Open cache guards are tested in `test_dicom.py` and `test_open_service.py`; asynchronous loading and later-series hydration remain open.

| Area | Current evidence; limits |
|---|---|
| Baseline/discovery | `dicom-baseline.xml`: 85 existing tests; `dicom-wave1-red.xml`: 13 failures/6 passes before fixes. Complete-series paging, suffix-independent recognition, private-header bounds and source guards have synthetic tests. |
| Inventory | `dicom-inventory-bounds.xml`: 16 tests, including durable batches, scanner invalidation, pinned WAL readers and explicit quota limits. Smaller/increased budgets preserve recoverable history. Aggregate cache quota/retention remains open. |
| Plan/reuse | All 1,027 planned rows page through stable cursors. Conversion reuses cached scan facts, and revalidates source generation before allocation and again after its native queue wait. |
| Owned execution | Parent-death/dispatch handshake, PID/start/boot/namespace proof, bounded native threads/memory and participating runner admission are tested. Unknown cleanup blocks replacement. Full shared-CPU and cross-container acceptance remains open. |
| Native commits | Strong selected-input/settings/identity pins; prepared/committed artifact journals and no-clobber publication. ENOSPC/source/output conflicts and same-run project/workspace resume have focused tests. Full crash-barrier coverage remains open. |
| Generated import | `dicom-registration.xml`: five cases, including injected registration faults and changed image/metadata refusal. Metadata-only recovery preserves one import/run. Torn journals and actual SIGKILL at every registration/index barrier remain open. |
| Phase | `test_dicom_phase_step.py` covers disabled/core separation, batch cancellation, actual abrupt analyzer exit, corruption/rules conflicts and sealed-output preservation. `test_dicom_phase_runs.py` covers independent records, fenced/idempotent metadata-only API retry/cancel, restart cleanup admission and later dataset import. Window tests cover child controls, polling and minimizing. Initial execution shares the owned conversion carrier; retries have their own worker. Private, hash-pinned metadata seeds recover missing analyzer inputs, including basic anonymization. Recovery without either metadata copy, full crash-barrier and migration acceptance remain open; D29 is not closed. |
| Operation facade | Durable discovery-to-plan intent and reserved run ID; conversion delegates existing project/workspace authority. Generation changes refuse launch. Duplicate handoff commands retain one run/allocation. |
| Native controls | Handoff/run-control locking and native-attempt fences; durable pending controls and run-side resume receipts reconcile lost responses. Restart/replay preserves the destination. Native Tasks controls share the DICOM run lock. |
| Window/picker | Server operation restoration, recent-operation selection, explicit new draft, bounded plan pages/filters, provisional counts and resume/cancel. Browser storage holds only operation ID/minimized preference. Source pickers accept extensionless files. |
| Re-estimate/progress | Settings-only Estimate retains its inventory/name/context; a destination change creates another operation. Stale 409 refreshes without replay. Committed selected-series totals, separate stage units, typed memory remedies and late-callback fencing have backend/window regressions. Historical ETA calibration remains open. |

### Reproduced failures and focused checks

- Earlier red logs cover native containment, missing run pins, shared-pool execution,
  parent death, publication conflicts, inventory bounds, phase checkpointing and registration.
- `dicom-handoff-cancel-red.log` reproduces cancellation acknowledgment preceding allocation.
  The subsequent handoff revision can legitimately return 409; rejection is not acknowledgment.
- `dicom-native-control-fence-red-corrected.log` reproduces the missing run-attempt contract.
  The initial red log also contains a corrected test route error; that is not a product defect.
- `dicom-resume-ack-red.log` reproduces lost resume acknowledgment in both contexts.
  Native receipts now distinguish an acknowledged resume from another caller's attempt.
- `dicom-operation-receipts.xml`: 16 focused cases passed before additional fence/restart cases.
  `dicom-resume-restart.xml`: both backend lifecycle restart cases pass.
  These lifecycle cases are not an abrupt SIGKILL at every native publication barrier.
- `dicom-controls-window-api.log`: 40 frontend/API tests passed before the extra pending-control case.
  `dicom-window-control-receipt.log` includes that additional window case.
- `dicom-native-serialization-red.log` reproduces native Tasks cancellation racing a source-operation resume.
  `dicom-native-serialization.xml` verifies serialization without controlling unrelated task runtimes.
- Real browser red checkpoint: `dicom-converter-browser-checkpoint.log` exposes lost non-DICOM actions;
  its project-create failures also include the temporary harness's reserved `derived` path component.
  The path guard was preserved; `dicom-converter-browser-recheck.log` passes all four original journeys.
- `dicom-converter-browser-restore.log`: six Chromium/Firefox cases pass, including minimized reload recovery.
  Synthetic source hashes are unchanged; no GPU compute. This is partial B coverage, not B01–B08 acceptance.
- Async refusal actions now have backend/UI red/green evidence; current focused regression is
  77 backend cases (`dicom-operation-refusal-regression.xml`) and 42 frontend/API cases (`dicom-window-refusal-fixed.log`).
- `dicom-controls-record-mock.log` refreshes synthetic exchanges; API artifacts are generated.
  `dicom-refusal-record-mock.log` refreshes the subsequent additive problem field.
- `dicom-reestimate-browser-final.log`: six Chromium/Firefox cases also verify same-operation re-estimate and restored settings; source hashes match.
- `dicom-group-proof-red.log` reproduces signalling after leader-proof loss; cleanup now refuses that signal and remains unverified.

### Regression and remaining closure

The previous full gate passed 903 backend and 357 frontend cases (90 files), with no skips
and 135 backend warnings (`dicom-operation-resume-final-check.log`).
It also passed lint/types/deadcode/API types/bundle/426 requirement IDs (232.9 KiB initial JS gzip).
It includes refusal actions, control receipts and native/source-operation control serialization.
Runner regressions passed 107 cases (`dicom-resume-final-runner.log`); host effects passed 21 (`dicom-operation-window-host.log`).
The current checkpoint also passes 107 runner cases and 70 frontend/API/import cases (`dicom-adr36-final-runner.log`, `dicom-adr36-window-import.log`).
`dicom-adr36-publication-targeted.xml`: 69 backend cases pass without skips, including missing-leader cleanup, cached re-estimates and mask-set regressions.
Repeat affected gates for the final implementation tree; browser/CI/image closure remains separate.
The phase checkpoint passes 10 API/restart cases (`dicom-phase-api-final.log`),
14 analyzer checkpoint cases (`dicom-phase-committed-progress-green.log`),
57 converter/layering regressions (`dicom-phase-converter-regressions.log`),
58 frontend/API cases (`dicom-phase-frontend-area.log`) and both G2 browsers
(`dicom-phase-g2-browser.log`). Lint/types/API types and 426 requirement IDs pass
(`dicom-phase-final-static.log`). These focused checks do not close the release matrix.
The subsequent input-recovery checkpoint passes 32 analyzer/API cases
(`dicom-phase-seed-targeted.log`), including initial input-publication failure with basic
anonymization and rejection of altered seeds/rules/checkpoints. Nine bundle tests pass
(`dicom-private-bundle-green.log`); exported projects retain annotation layers but exclude
private execution/phase state. CI run 40090535142 passed 938 backend cases and failed two
obsolete single-run assertions; their replacement requires exactly one conversion plus its
linked phase run. Final CI remains required.
Use absolute `VENV`, `RUNTIME=udocker`, `FULL_TESTS=1`, `PYTEST_WORKERS=2`, `VITEST_WORKERS=1`.
Dependencies come only from the locked project venv; Node runs only in the existing container.

Remaining acceptance is the complete matrix in `DICOM_JOB_TEST_PLAN.md`, including:

- Every conversion/registration/index crash barrier, torn-record recovery, migrations and rollback;
  strong conflict preflight, identity reservations across unregistered runs, Retry failed and complete CLI resume parity.
- Aggregate inventory retention/quota, duplicate SOP/UID/missing-identity diagnostics,
  independent GDCM encoding/multiframe oracle, shared-worker/multi-workspace CPU accounting
  and independent same-image cross-container ownership/cleanup evidence.
- Phase recovery when both pinned inputs and their private seed are unavailable, full analyzer
  publication/index crash barriers, and migration/rollback acceptance for independent phase runs.
- Recoverable general Open/import loading and later Open-series hydration;
  complete progress crash-barrier recovery and full U/B acceptance.
- Compatible historical ETA, calibrated hold-out coverage and controlled reference benchmarks.
- Final full/shared-runtime/browser/CI/Docker/udocker gates, reader-version migration and deployment readiness.

No closure checkbox is certified by narrower synthetic checks or by the accepted ADR alone.
