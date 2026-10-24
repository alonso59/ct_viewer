# DICOM source operations: tests and acceptance

Scope: tests-first verification, regression protection and release gates for DICOM_JOB_PLAN.md.
Read when: writing tests, measuring performance or deciding whether DICOM background/resume work is complete.
Depends: ../domain/DICOM_JOB_PLAN.md, TESTING.md, ADR-0035; requirement ownership remains in INDEX.md.

## Status and method

Cases below define the required acceptance; passing evidence is recorded in DICOM_JOB_PLAN.md. ADR-0035 was accepted with implementation authorization on 2026-10-23; it does not certify these cases. Case labels D/U/B/P are acceptance-case labels, not new SRS requirement IDs. At Wave 0 add new requirements only in their owning docs; each test cites applicable existing/new accepted requirement IDs and its case label. Record red output before its fix, green output afterward, revision, environment, command and evidence location. Test public behavior and filesystem/process effects, not private implementation structure.

Use synthetic data for CI/recordings/screenshots; no patient paths/tags in artifacts. Real TCGA is an opt-in local acceptance source, never a CI fixture or upload. Run tests under the existing locked environments, non-root image and container-only Node on john. Do not use production output directories, production services, GPUs or host package installs for these tests.

## Fixture families and independent oracles

| Fixture | Construction and oracle |
|---|---|
| Deep/mixed tree | Seeded CT DICOM at root and depths 1/3/8, mixed with NIfTI/NumPy/text; expected relative files, complete series membership and rejection reasons in a generated manifest. Include legitimate folders with names that resemble exclusion names; test documented exclusion policy explicitly. |
| Large-series tree | At least one 750-slice tiny CT series crossing the old 500-file boundary, >500 series and >1,000 planned rows; a separate listing-only >200,000-entry fixture tests budgets without large pixel payloads. |
| Header variants | `.dcm`, `.DCM`, `.ima`, extensionless, `.001`, `.dicom`; with/without preamble, supported explicit/implicit and endian encodings; enhanced multi-frame CT/MR; non-image DICOM, SEG, missing UID, corrupt/random bytes, very long/private headers. Real reader support determines expected acceptance. |
| Geometry oracle | TST-13 asymmetric marker, oblique direction, reversed filename/InstanceNumber order and known RAS-mm landmarks; expected geometry independent of the converter's grouping/sorting helpers. Include each DCM-03 defect and duplicate SOP instances. |
| Mutable source | Controlled add/delete/rename/replace during discovery/planning/conversion, including equal-length content with restored mtime; immutable completed outputs hashed before/after. |
| Process/crash harness | Spawn a disposable real API and DICOM worker; controllable barriers at read/write/publish/commit/register; slow native unit, abrupt worker/API death and an unrelated job/sentinel. Use real process ownership and temp roots, never arbitrary PID kills. |
| ETA corpus | Deterministic recorded synthetic durations with environment/codec/concurrency signatures, outliers and insufficient samples; hold-out observations for accuracy tests, never the same measurements used to fit the model. |

Pixel decoding is required only in geometry/conversion/process cases. Header-only/budget tests use compact fixtures and spies on pixel reader/writer entry points; simulate pathological short reads/timeouts explicitly. Validate outputs with nibabel/known landmarks and reader oracles, not the writer's own returned metadata alone.

## Backend acceptance matrix

Tests extend existing files where the feature already lives; new filenames are proposed. Parameterize project/workspace variants instead of cloning expected results.

| Case | Behavior and decisive assertions | Specification / intended tests |
|---|---|---|
| D01 | Discover every nested supported file at all fixture depths; deterministic series/identity across traversal/concurrency order. No depth cutoff or silent missing branch. | SRC-01/02/07, DCM-06; `test_sources.py`, `test_dicom_scan.py` |
| D02 | Open the 750-slice series through a root containing >500 files; members and z extent match the independent manifest; inspect actual resulting voxel count and landmarks. Every later series is reachable through paging. | SRC-09/13, DCM-02, TST-13; `test_open_service.py`, `test_dicom.py` |
| D03 | Picker/detect/Open/dry run/conversion agree on supported header variants regardless of suffix. Random `.dcm` is not a valid image. Preserve `.nii.gz`/`.npy` recognition. | SRC-01/02, DCM-10; `test_sources.py`, `test_dicom_scan.py`, `test_dicom.py` |
| D04 | Mixed/non-image/missing UID/corrupt/SEG cases produce typed rejection/diagnostic counts; no fabricated successful series or empty dataset. One damaged series does not hide valid neighbors. | DCM-03/06/10/11, BE-08; `test_dicom_scan.py`, `test_dicom.py` |
| D05 | Symlink escape/cycle/replaced descendant rejected at read time; unreadable subtree reports partial discovery. Output-root traversal, root overlap and source-as-output are refused. | BE-02/03/15, NFR-11; `test_sources.py`, new `test_source_inventory.py`, existing path tests |
| D06 | Group/ordering matches supported GDCM oracle for shuffled slices and multiple UIDs per folder; UID repeated across folders is diagnosed without unintended merge. Duplicate SOPs cannot silently alter volume. | DCM-02/03, SRC-07; `test_dicom_scan.py`, new `test_source_inventory.py` |
| D07 | Bounded queues/header buffers; reject over-budget pathological headers actionably. >200k candidates yields explicit partial/continuation; exclusions are pruned before descent. Every supported series remains complete. | BE-12, SRC-02/09, DCM-06; new `test_source_inventory.py` |
| D08 | Legacy API-07/19 shapes/statuses/errors stay compatible for files/folders; new operation 202 only after durable record. Delayed job completes after HTTP connection closes. | API-07/19, BE-08/10; new `test_source_operations_api.py`, OpenAPI snapshot |
| D09 | Series paging has stable order/no gaps/duplicates; changed generation rejects stale cursor. Item IDs remain stable across pages; attaching/viewing/saving a selected later series still works. | SRC-07/09/10/14, API-08/09; `test_open_service.py`, new API tests |
| D10 | Inventory reuse: discovery→dry run→convert shares parsed header facts; instrument read counts, distinguish necessary full sidecar header and pixel reads. Same input never triggers an unexplained full header rescan. | DCM-04/06/07, BE-12; new `test_source_inventory.py` |
| D11 | Added/deleted/renamed/replaced files invalidate affected branches/plan; restored-mtime mutation cannot bypass strong resume verification. Old plan is not silently used for new data. | DCM-07, SRC-07, TSK-07; new inventory/resume tests |
| D12 | Dry run invokes no pixel reader/NIfTI writer, changes no source or final dataset, pages all >1,000 rows; selected/skipped/reasons/storage match actual conversion decisions. | DCM-06, TSK-05; `test_dicom.py`, `test_metadata_ownership.py`, new operation tests |
| D13 | Restart during discovery/dry run preserves records and completed valid batches; API reconciles interruption and returns results/progress independently of the old request. Invalid half-batch is discarded/recomputed. | BE-05/06/13, API-62; new `test_dicom_operation_recovery.py` |
| D14 | Durable start/control acknowledgment, duplicate idempotency key returns same operation/run; changed payload with same key returns conflict. No lost acknowledged operation after abrupt restart. | BE-05, TSK-06, new operation contract; new API/recovery tests |
| D15 | Project and workspace use the same estimate semantics; no derived root blocks conversion with existing remedy while read-only discovery is usable. Reject invalid/settings-changed stale plans before creating output directories. | DCM-01/06/14, TSK-13, API-44/62; new operation API + `test_metadata_ownership.py` |
| D16 | Cancel during listing/header/plan: durable cancelling, no new dispatch, no synthetic completed result. Repeat cancel is safe; ready-but-unlaunched conversion never starts. | DCM-06, TSK-06/07; new `test_dicom_operation_controls.py` |
| D17 | Real cancel during native decode/write: owned worker/descendants stop, pending units never launch, temporary outputs cleaned, unrelated task and API remain healthy. No process-pool-wide terminate. Deliberately unconfirmed cleanup blocks replacement attempts. | BE-06/13, TSK-07, ADR-0035; new `test_dicom_process_lifecycle.py` |
| D18 | SIGKILL worker/API at each commit barrier (staging, after publish, before commit, during registration) yields recoverable state. Validate adoption/quarantine policy, no successful partial artifact. | DCM-02/04/07, TSK-09, BE-05; new `test_dicom_operation_recovery.py` |
| D19 | Uninterrupted run versus interrupted/resumed run: same case/scan IDs, same voxel data/world geometry, metadata facts and sidecar semantics. Hash previously committed outputs before/after resume; exclude run timestamps from semantic comparisons. | SRC-07, DCM-02/04/07, NFR-18; new `test_dicom_resume.py` |
| D20 | Resume in both contexts reuses original logical run and allocated output directory; new attempt ID only, no `_datasets/name-1`, no hidden project, no duplicate import/index rows/layers. | DCM-07/14, TSK-09/13; new `test_dicom_resume.py`, `test_metadata_ownership.py` |
| D21 | Resume rejects changed/deleted source, incompatible settings/reader, changed output bytes/geometry, missing required sidecar. No existence-only skip. Explain conflict; preserve valid outputs and offer explicit new operation/recovery. | DCM-02/04/07, TSK-07; new `test_dicom_resume.py` |
| D22 | Double resume, resume-vs-cancel, two-tab convert, and late old-worker progress/result cannot duplicate writers or registration. Stale attempt/revision fenced; cleanup_pending never resumable. | BE-05, TSK-06/07/09; new controls/recovery tests |
| D23 | Resume skips only verified commits; restarts incomplete series from beginning; Retry failed selects failures only. No missing/duplicated checkpoint after torn write. Cancel preserves completed artifacts. | DCM-07, TSK-07/09; new `test_dicom_resume.py` |
| D24 | Workspace dataset is not advertised as ready during partial commit; completed dataset sealed. Repeated finalization/registration after crash creates exactly one valid result/import. | DCM-07/14, TSK-09/13, SRC-16; new recovery + `test_metadata_ownership.py` |
| D25 | ETA unknown without compatible history; correct units/basis/range/sample count, no negative/NaN ETA, no pixel calibration. Codec/host/storage/concurrency/version mismatches excluded; pauses/restart downtime excluded. | TSK-05, DCM-06; new `test_dicom_eta.py` |
| D26 | ETA after resume excludes verified completions; updates from committed series, not failed/unfinished units. Deterministic hold-out observations validate range coverage; zero throughput remains unknown. | TSK-05, DCM-06/07; new `test_dicom_eta.py` |
| D27 | CPU/thread/process admission respects aggregate cap across operations and segmentation reservations; unknown reservation state serializes admission. Missing/invalid memory budget permits discovery but refuses pixels actionably; peak estimates queue/refuse oversized work. Validate defaults, bounds and startup diagnostics. API never retains all image pixels. | BE-01/06/12, NFR-08; new `test_dicom_resource_admission.py`, config tests |
| D28 | Geometry/affine fidelity incl. oblique and enhanced cases, geometry skip policy, anonymization and sidecar omissions/provenance unchanged; artifact publish cannot replace a concurrent existing file. | DCM-02..05/10, NFR-18; `test_dicom.py`, `test_dicom_scan.py`, new commit tests |
| D29 | phase-off never invokes phase rules; phase-on launches separate recorded analyzer with same proposal semantics/precedence. Analyzer failure leaves conversion usable; retry does not reconvert or overwrite a manual phase. Metadata/CLI remain clean. | DCM-09/13/14, ANZ-01..08, PHS-03/04, TST-20; `test_metadata_ownership.py`, `test_analyzers.py`, `test_phase.py` |
| D30 | View-only cannot start/control/read unrestricted workspace inventory; no patient source paths in URLs, SSE, logs, mock recordings, neutral dataset names or errors exposed by shared links. | API-60, NFR-12/17, PRJ-17; `test_view_redact.py`, new operation API tests |
| D31 | Single-file DICOM/multiframe, standalone NIfTI/NumPy, metadata import, attached mask geometry/refusal, Save as and Open-cache sharing retain behavior. | SRC-01..16, DCM-10; `test_sources.py`, `test_open_service.py`, `test_open_convert_once.py`, `test_dicom.py` |
| D32 | Operation history/plan survive reload; retention/eviction never removes active or interrupted recoverable inventory, commit or controls. Missing/corrupt/older record versions yield actionable recovery and preserve evidence. | BE-05/06, API-62, OPS-03; new operation retention/migration tests |
| D33 | SSE reconnect/refetch and workspace polling converge on the same revision; stale/out-of-order events cannot regress counters/state. Backend clock changes do not corrupt durable durations. | API-40, BE-06, UI-25; new API/recovery tests |
| D34 | Standalone CLI uses shared discovery and produces contract-v1 output, same identity/geometry and resume behavior; existing YAML/options/defaults accepted. No app imports in plugins, service/API dependency cycles or legacy dependency. | DCM-09/13, TST-20, BE layering/R9; metadata ownership + `test_layering.py` |
| D35 | ENOSPC, permission failure, short writes and abrupt failure during metadata/sidecar/checkpoint produce failed/interrupted with correct committed counts; no success acknowledgment before durable commit. Hash verification and retry recover safely. | DCM-01/04/07, BE-05, TSK-09; new commit/recovery tests |

## Frontend unit/integration matrix

Use real QueryClient state and API-recorded synthetic exchanges; assert requests/visible results. Mock only timing/race boundaries, not complete success paths. Extend `plugins/dicom/ConverterOverlay.test.tsx`, add store/operation/progress/plan tests, and cover modified import/Open components and API bindings.

| Case | Observable assertions |
|---|---|
| U01 | Existing source/settings/dry-run/run/result journey remains valid for project and dataset; default phase-on/anonymize behavior and name clash warning unchanged. |
| U02 | Import DICOM hands off source/project exactly once to existing overlay; metadata/NIfTI/NumPy retain adapters/options and unsaved import context; generic discovery/indexing can minimize/restore without loss. |
| U03 | Picker can select supported extensionless/`.ima` candidates, reports validation failure for non-DICOM, and does not silently accept every unknown file as an image. |
| U04 | Discovery shows provisional folders/files/DICOM/series counters; unknown total is indeterminate. Once totals known, use matching units and sensible empty/error states. |
| U05 | Minimize/×/Escape while working preserves server operation; restore/focus works. Closing idle/result differs from cancel. Multiple operations do not overwrite each other. |
| U06 | Fresh store/QueryClient after reload discovers operation IDs from server and restores stage/counts/context; no dependence on saved browser snapshot or URL containing a patient path. |
| U07 | Cancel shows Cancelling until cleanup acknowledgment; network error keeps reconciling, never fakes Cancelled. Repeated click cannot dispatch multiple attempts. |
| U08 | Open paged complete series, select a later page, view full volume, preserve attach/Save as; no "first 500 files" assumption in list/selection. |
| U09 | Resume/Retry failed shown only in allowed states, display verified completed vs pending counts and exact output destination. Changed inputs/settings show actionable conflict. |
| U10 | ETA shows basis/range/unknown/elapsed; resumed ETA excludes completed work; conversion complete + analyzer failed yields Retry analyzer rather than rerun conversion. |
| U11 | >1,000-plan paging/filtering and virtualized/bounded DOM; generation changes invalidate old pages/selection safely. No implicit Convert on scan/estimate/filter/restore. |
| U12 | Accessible progressbar/status, keyboard focus on minimize/restore, label/cancel tooltip, responsive floating panel, Dark/Light, all localized keys; unmount stops polling without cancelling the server job. |

## Both-browser acceptance (real disposable backend)

| Case | Journey / required evidence |
|---|---|
| B01 | Project Import data → deep DICOM → shared overlay → dry run → minimize → navigate → restore → convert → indexed result. |
| B02 | No project → Convert DICOM → minimize during scanning and conversion → restore → dataset → Open/Create project/Add to project. No implicit project allocation. |
| B03 | Open root with >500 slices and >500 series → later-page series → full volume/geometry → conversion handoff. Verify backend member manifest, not only UI row text. |
| B04 | Reload and close/reopen a browser context during scan, estimate and conversion; operation identity/results retained. A second tab reflects control state without duplicate work. |
| B05 | Cancel each stage incl. native writer, observe confirmed terminal state, resume same run, validate completed hashes and one registration. Verify owned PIDs are gone. |
| B06 | Restart the real API mid-conversion, then restore operation, show Interrupted, Resume, complete unchanged pending series with new attempt and original output destination. |
| B07 | Force partial series/analyzer failure; retry only failures/analyzer; preserve conversion and manual phase. Error/summary counts agree with filesystem manifests. |
| B08 | Non-DICOM import/Open and G1..G4 journeys unchanged; view-only/network allowlist and viewer WebGL2 remain real. Dark/Light plus keyboard minimize/restore checked. |

Lifecycle tests must spawn actual processes; thread-inline/mock tests do not certify termination/restart. Reuse existing browser harness patterns, without invoking GPU inference or modifying the segmentation lifecycle. Windows Docker acceptance covers container process control; Linux udocker covers john. Required platform prerequisites missing are a blocked lane, not a skipped pass. Safari coverage remains NFR-13 and must be reported separately if unavailable.

## Performance acceptance (proposed targets, Wave 0 baseline)

Record machine/storage/container, git tree, settings/versions, file/byte/series counts, effective workers, CPU/RSS, first progress latency, header reads, throughput and p50/p95 page latency. Separate cold/warm runs and file enumeration/header discovery/pixel conversion/registration. Use identical data/settings with old web converter and principal `src/preprocessing/convert/`; semantic output checks precede speed claims. Do not drop caches or reset other server users' resources.

| Case | Acceptance method / target |
|---|---|
| P01 | First progress/status acknowledgment ≤1 s on prepared reference host; subsequent activity visible while long traversal runs. Controlled-clock unit test plus real reference measurement. |
| P02 | Pure inventory enumeration target ≥2× old web detector median on the same TCGA tree/cache conditions (at least 3 runs each); 20.08 s is only prior observation. Header discovery must separately retain exact supported membership and diagnostics. No cross-stage speed comparison. |
| P03 | Unchanged discovery→dry-run→convert reuses header facts by instrumented counts; revalidation/strong hashes and sidecar reads measured separately. Full conversion throughput must not regress >10% median against comparable baseline; justify statistical noise and storage contention explicitly. |
| P04 | Discovery/plan pages remain bounded for >200k files and >1k series; existing NFR-03/04/08 targets remain required at their stated reference workload. Measure API RSS and worker peak memory separately. |
| P05 | Healthy-host cancel control acknowledgment ≤1 s and verified owned cleanup ≤30 s; blocked/uninterruptible test reports cleanup_pending and forbids replacement. UI acknowledgment alone is insufficient. |
| P06 | ETA hold-out target ≥80% of compatible series/run durations within reported ranges after ≥5 representative completed-series observations; include range width/error so an arbitrarily wide range cannot claim usefulness. Before evidence exists show unknown/low confidence. Review calibration per codec/storage/concurrency. |

Wall-clock/throughput goals run in a dedicated controlled lane; avoid flaky subsecond assertions in shared CI. CI verifies event ordering, work/read counts, bounds, formulas and simulated clocks. If performance targets fail, report them as open; do not weaken geometry, source guards, hashing or series completeness to meet them.

## Regression and environment gates

| Gate | Required verification / evidence |
|---|---|
| Focused red/green | Run relevant existing and new pytest files and affected Vitest tests after each wave. Source operations, process controls, crash/restart and CLI tests mandatory. Preserve failing traces on first failure; do not rerun until green without diagnosis. |
| Full static/unit/contract | `make check FULL_TESTS=1` with configured locked Python/container Node runtime; includes lint/types, all backend/frontend tests, deadcode, OpenAPI/TS and requirement/bundle checks. Generate schema/mock exchanges from synthetic backend; review diff. No mandatory skipped tests. |
| Shared lifecycle safety | `make test-runner FULL_TESTS=1 PYTEST_WORKERS=0`; if shared job/process/host code changes, `make test-host FULL_TESTS=1` and real supervisor browser gate. No GPU launch required for this DICOM plan. Existing runner/radiomics/index/thumbnail jobs must survive DICOM cancel/crash. |
| Browser | Full `make fixtures e2e` in prepared browser container with real WebGL2 in Chromium/Firefox; include B01–B08. Focused browser passes do not replace full journeys. |
| Real data | Read-only TCGA discovery/dry run; remeasure baseline counts at test time. Validate series count/membership against independent GDCM oracle; folder count is not series count. Real pixel conversion requires selected representative CT series into a fresh approved derived directory, full source before/after hash evidence and geometry check; not authorized merely by this planning task. |
| Product image | Build one image after unit/browser gates; run Docker container-smoke plus DICOM lifecycle/restart smoke non-root, then load the same image under udocker and repeat with disposable roots. Hash synthetic sources and completed outputs. Report image size/runtime limits and platform gaps. |
| Publication/deploy | Review actual CI result for the published tree and same-image checks before rollout. Back up operation/run metadata; record migrations/compatible reader versions, image digest, rollout/rollback procedure. Never roll an old image back onto incompatible active records; drain jobs or restore a compatible metadata snapshot after cleanup. |

Commands above refer to existing Make targets; new DICOM process/browser/benchmark targets are added in their implementation waves and documented in TESTING.md. Do not imply a nonexistent target already runs these cases. All writes during tests stay under temporary workspace/derived roots; source hashes must match (TST-07), including failure/cancel paths.

## Closure evidence checklist

- [ ] ADR-0035 accepted, owner specs/API updated without duplicate requirements; each accepted behavior maps to tests.
- [ ] D01–D35 and U01–U12 implemented with linked red/green evidence, both scope variants where relevant.
- [ ] B01–B08 pass in Chromium/Firefox against real services; unsupported platform evidence explicitly open.
- [ ] Resume after cancellation/worker crash/backend restart preserves identities, valid output bytes and original destination; no duplicate attempts or registrations.
- [ ] Strong input/output verification, geometry, anonymization, clean metadata, CLI compatibility, no-clobber publication and source immutability proven.
- [ ] P01–P06 measured/calibrated on the reference lane; unknown ETA remains truthful; resource bounds/unrelated-work survival verified.
- [ ] Full checks, browser journeys, shared-runtime regressions, CI and same-image Docker/udocker lanes pass; no mandatory skip hidden as success.
- [ ] Reviewer can reproduce evidence from recorded tree/image/settings; production migration/rollback readiness documented separately. Planning alone closes none of these boxes.

## Current implementation checkpoint (not closure)

Focused cases cover portions of D01–D35; each complete acceptance row remains the gate.
Native resume, strong input/output pins, owned cleanup, publication/ENOSPC and registration have synthetic evidence.
Discovery/Estimate include actual backend SIGKILL/restart and durable inventory batches.
Operation controls now test handoff-vs-cancel, stale native attempts and lost resume acknowledgments in both contexts.
Lifecycle restart tests preserve the linked run/destination and replay its acknowledged command without another attempt.
Those lifecycle tests do not replace abrupt SIGKILL at each conversion/registration/index barrier.
`test_dicom_progress.py` additionally covers selected/committed counters, typed resource waits and late old/current completed-worker callbacks.
Cached re-estimates cover preserved generation/name, destination changes and stale-fence refresh; D22/D26/D27 remain partial.

Window tests cover server restoration, pending-control replay, privacy of persisted browser state,
complete plan pagination/filtering, stopping/resource states and extensionless source selection.
They provide partial U coverage; B01–B08 and performance P01–P06 are not certified.
Six real Chromium/Firefox converter cases now cover conversion/import, non-DICOM remedies and minimized reload recovery.
Source hashes remain unchanged. These cases do not certify all B rows or real WebGL viewer acceptance.

Verification counts, artifact names and remaining closure work live in DICOM_JOB_PLAN.md §Implementation evidence.
Independent phase run/API/window retry and all release gates remain open.
No closure checkbox is certified by these narrower checks.
