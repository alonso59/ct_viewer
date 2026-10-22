# Supervised segmentation jobs: audit and implementation plan

Scope: approved model catalog, GPU allocation, persistent job control and isolation; P7f audit and P7g work order.
Read when: implementing the next segmentation phase or assessing its safety guarantees.
Depends: SEGMENTATION.md, TASKS.md, SEGMENTATION_RUNTIMES.md, ../adr/0034-capability-based-segmentation-runtimes.md, ../ops/SEGMENTATION_JOB_TEST_PLAN.md.

## Status and boundaries

P7f accepted and P7g authorized by the owner on 2026-10-22; ADR-0034 supersedes ADR-0033 following the owner's no-administrator deployment decision.
The user requested an audited, tests-first implementation. P7g follows the ordered gates below.
The keys below identify acceptance criteria, not SRS requirement IDs. Assign IDs in their existing owner docs before each wave's tests.
Keep R1..R9, TSK-09/11 and SEG-06. Prioritize Linux local/server production readiness; SLURM execution/acceptance is deferred until cluster access exists. No accounts, database server, privileged daemon, automatic model download or GPU code in the app image.
Support compatible nnU-Net v2 **single-channel NIfTI** models first. Multi-channel MRI, cascade/multi-configuration pipelines and training require a later phase; incompatible models must be explained and refused.

## P7g execution status (2026-10-22)

- Wave 0 verification foundations are implemented. Full backend/frontend units pass; full browser and image/CI gates remain distinct acceptance lanes.
- Waves 1/2 have an owned user-service supervisor, effective Landlock/seccomp probe, generation-fenced cleanup acknowledgement, API restart reattachment, idempotent mask registration and a durable participating host allocation. Real process tests cover cancel/crash recovery and setsid descendants; synchronized allocator processes share one slot.
- The original namespace-based host probe failed and remains recorded. The ADR-0034 capability backend now passes its effective GPU-free protections. Configured inference completed real one-GPU and two-GPU cases with official postprocessing; evidence is owned by `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.
- GPU cap/physical selection is exposed through generic task settings. The runner catalog and pinned resume identity are wired (`test_nnunet_catalog_api`, `test_nnunet_run_identity`).
- Wave 4 lifecycle (2026-10-22): batch pause keeps committed cases and dispatches no remaining ones; publication never overwrites. API-46 pause/archive and supervised cancel record durable `control.json` requests; runs stay `pausing`/`cancelling` until the same attempt's verified cleanup, a stop without it is `cleanup_pending` (archive/resume/new runs 409), archived runs are hidden from API-45 unless `archived=true`. The runner never claims a paused job and answers with `control-ack.json` (`test_segmentation_controls`, `test_task_archive`, `test_runner_safety`).
- Wave 5 UI (unit level): every lifecycle state is labelled and translated, Pause/Cancel/Resume/Retry failed/Archive follow the state, cleanup-pending text stays until confirmation, view-only shows no action (`features/tasks/model.test.ts`, `RunRow.test.tsx`). `reconciling` is typed but not emitted: an API restart reattaches straight to the observed state.
- Still open before the P7g exit: Playwright journeys on the real API/supervisor (U1/J2), the full Chromium/Firefox lane, a fresh verification/product image build in CI, and host acceptance of pause → resume and cancel on a GPU (wave 6). No full P7g exit is claimed.
- Unconfigured GPU launches remain blocked. Existing deployed/running production services have not been replaced by this work.

## Audit of the current implementation

| Finding | Evidence | Required change / priority |
|---|---|---|
| Catalog is fixed to KiTS | `plugins/nnunet/task.json`, `check.py`; configurator validates an existing profile | Discover operator-registered profiles; validate individually; remove kidney-specific UI/manifest assumptions / high |
| Class-based models are rejected | `plugins/nnunet/profile.py::_derived_labels` unconditionally requires `regions_class_order` | Support integer class maps and region maps independently; validate labels/channels / high |
| GPU controls are a cap only | `task.json` accepts 2..4; `run.py::_gpu_ids`, `_execute` choose the pool prefix | Allow one GPU; select approved physical devices using UUIDs / high |
| Atomic job claim is not a GPU reservation | `scripts/rw-runner.py::claim` uses O_EXCL per queue job | Coordinate allocations across workspaces/runners participating in the same host pool / critical |
| Hard crashes can leave descendants | Runner tracks Popen objects only in memory; plugin creates new sessions; runner kills only its direct child | Own every attempt in an enforceable process boundary; reconcile before retry/release / critical |
| Partial startup has no enclosing cleanup | `_execute` launches all predictors before entering `_wait` | Failure on a later spawn must terminate already-started workers / critical |
| Shutdown does not verify process exit | Runner `finally` sends terminate without waiting/escalation | Stop, wait, escalate, reap, then confirm resource release / critical |
| API restart can permit overlapping attempts | `jobs/runs.py::reconcile` marks unknown jobs interrupted; task resume checks in-memory jobs | Recover external state and fence attempts before scheduling a replacement / critical |
| Results are published after the prediction batch | `run.py::_execute`: wait all parts, postprocess, publish | Commit complete validated cases incrementally for useful pause/resume / high |
| Resume does not pin external model/input state | `tasks/service.py::resume` checks task version and skips recorded ok items | Pin manifests, profiles, model artifacts, inputs and outputs; reject drift / high |
| Pause/archive/cleanup have no contracts | `TaskRunStatus`, API-46, `TaskEditor.tsx` expose cancel/resume only | Define lifecycle and guarded actions before UI work / high |
| Isolation is application-level | Host conda subprocesses; data symlinks; no per-job CPU/RAM/device/filesystem boundary | Probe and enforce declared host capabilities; never infer isolation from udocker / critical |
| Runtime policy is not a host guarantee | SEG-13 forbids network; wrapper does not isolate its subprocess network | Enforce denied network in strict mode and test it / high |
| Access is shared by design | ADR-0004: anyone reaching the port can write; reviewer is advisory | Scope ownership to Unix identity/app instance; no claim of browser-user authorization / high |

Test-pipeline findings, measured baseline and host capability evidence live in `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.

## Accepted phase criteria

| Key | Observable contract | Requirement owner |
|---|---|---|
| M1 | Operator registers trusted profiles under allowlisted results roots. Catalog returns stable profile IDs, availability/reasons and a generation/fingerprint; one invalid profile does not disable valid siblings. Browser settings contain IDs, never commands or arbitrary host paths. | SEG-* |
| M2 | Validate model files/hashes, class or region labels, modality, channel count, trainer availability and supported pipeline before allocation. Revalidate a pinned profile at launch; reject drift while queued. | SEG-* |
| G1 | Show host physical index, UUID, name, memory and freshness for approved GPUs. Accept automatic selection or explicit unique UUIDs and a 1..operator-max count (initial max 4). Reject outside-pool, duplicate/aliased, stale or inconsistent requests. | SEG-*, API-* |
| G2 | Atomically reserve the full effective GPU set or queue without holding a partial set. A single-host allocator covers all participating workspaces with an allocation generation. The initial backend conservatively serializes attempts, including disjoint GPU sets. Requested devices are never silently substituted. | TSK-*, OPS-* |
| G3 | A busy/unobservable device is unavailable by default. No eviction of outside work. Publish requested vs effective GPUs; effective count is bounded by pending cases. Reservations are cooperative, not exclusive against unrelated programs. | SEG-*, OPS-* |
| J1 | Persist a versioned external-attempt record and acknowledged control requests. API is the only writer of project records; supervisor writes queue state. Recovery and command replay are idempotent; stale attempts cannot publish into a new attempt. | TSK-*, BE-* |
| J2 | Closing/reopening a tab or API restart never cancels or duplicates external work. Reconnect tails durable progress from its cursor and imports each validated result once. Builtin job recovery retains its current BE-06 policy. | TSK-*, BE-* |
| J3 | Pause stops dispatch, completes bounded in-flight cases then exits workers, or interrupts them at a deadline. Publish only complete postprocessed/validated masks. A paused job owns no workers or GPU reservations. | TSK-*, SEG-* |
| J4 | Resume creates a fresh fenced attempt with the same logical run/output set; reacquires GPUs, verifies pinned inputs/profile and existing output hashes, skips committed cases, restarts incomplete cases. Permit explicit retry of failed items in a partially successful run. | TSK-*, SEG-* |
| J5 | Cancel before claim prevents launch; during execution it terminates the entire owned tree with bounded escalation. All controls are idempotent; invalid transitions return a stable conflict. | TSK-*, API-* |
| J6 | Delete means cancel a queued job or archive an inactive logical run. Active/uncertain/cleanup-pending jobs cannot be archived. Audit records, registered masks and source data are retained; permanent output purge is out of this phase. | TSK-*, API-* |
| S1 | Own each production attempt in a user service/cgroup with the OPS-16..19 resource and cleanup bounds, including native numerical workers. Verify source/model content protection and denied nonlocal sockets. Apply bounded logs/file sizes and free-space monitoring; report the absence of aggregate storage quota explicitly under ADR-0034. | OPS-*, BE-* |
| S2 | Probe actual controller and sandbox effects; report namespace/device/quota/logout capabilities separately. Production refuses a missing required backend protection. The failed original strict profile is retained as evidence, not silently advertised as supported. | OPS-* |
| S3 | Recover/clean only verified owned attempts, using Unix UID, host boot ID, unit/cgroup invocation identity and process start identity. Never accept an arbitrary PID or kill by process name/GPU occupancy. Ambiguous state requires intervention. | TSK-*, OPS-* |
| S4 | Heartbeat loss is suspect, not proof of exit. Release a reservation only after the owned boundary is empty and GPU context accounting is reconciled. Failure remains cleanup-pending and blocks conflicting allocations. No GPU reset or driver/global policy change. | OPS-*, SEG-* |
| U1 | Generic Tasks UI exposes catalog, GPU choice, durable progress, lifecycle actions, cleanup state and enforcement reasons. View-only links offer no mutation. Same-instance write access remains shared under ADR-0004. | UI-*, API-* |
| V1 | Each criterion has test-first evidence, a defined environment and observable oracle. Fake tests and host acceptance are separate gates; a skipped prerequisite is never a passed acceptance check. | TST-* |

## Architecture and lifecycle

Use the existing external file queue, extended with versioned attempt/control/state records; retain compatibility for builtin tasks and old run records.
A persistent host supervisor runs in the existing conda environment. One per-host participating GPU pool has a single allocation authority; do not use workspace-local locks to claim host-wide coordination.
Default deployment is one Unix identity/app instance with its private state and trusted web writers. Cross-UID pooling needs an operator-provisioned common broker/access policy and separate acceptance; a shared world-writable lock folder is not a security boundary.
Use systemd **user services per attempt**, not only a runner-level process group. A subprocess `setsid()` must not escape job cleanup. Keep the API out of host process creation (TSK-11).
User service capabilities vary: prove host support before selecting filesystem/network/device restrictions. CPU cgroups alone do not provide filesystem isolation or GPU VRAM quotas.
If required backend boundaries cannot be enforced without privileges, stop with a precise prerequisite report. Optional quota/logout guarantees remain explicit limitations under ADR-0034. Do not install packages or enable lingering as a side effect.

| Current state | Action/event | Next observable state |
|---|---|---|
| queued / waiting_for_runner / waiting_for_resources | resources acquired, attempt launched | running |
| queued / waiting_* | pause / cancel | paused / cancelled; nothing launched |
| running | pause | pausing; stop dispatch; preserve complete cases |
| pausing | boundary empty and reservation released | paused |
| running / pausing | cancel | cancelling; await verified cleanup |
| cancelling | boundary empty and reservation released | cancelled |
| running | all cases committed / some item failures | completed / completed_with_errors, after cleanup |
| active | lost supervisor / API restart | reconciling; no replacement launch |
| reconciling | owned attempt live / verified dead | running (or prior control state) / interrupted |
| any stopping/reconciling state | uncertain ownership or surviving resources | cleanup_pending; allocation remains blocked |
| paused / cancelled / failed / interrupted / completed_with_errors | resume/retry, no prior live attempt | queued; new attempt generation |
| inactive, cleanup verified | archive | hidden from default list; retained audit/output references |

Transition names above are not implemented yet; update all shared types, API snapshots, recorded mocks, i18n and UI together in P7g.
GPU selection applies to the next attempt, not a live worker. Resume on different approved GPUs is allowed without changing the pinned model/input identity.
Normal pause finishes the bounded in-flight work; immediate stop may repeat that work on resume. No mid-case checkpoint or SIGSTOP-based memory-release claim.

## Ordered P7g work packages: tests before implementation

| Wave | Tests written and observed failing first | Implementation after the red checkpoint | Exit |
|---|---|---|---|
| 0: contracts and baseline | Acceptance matrix and named tests for each new behavior; prerequisite/fixture isolation tests | Accept ADR-0033; update owner requirements; bound test resources; add enforced verification workflow before image publication | Baseline gaps explained; deterministic fake environment; required lanes cannot silently skip |
| 1: supervision and recovery | S1..S4, J1/J2/J5: descendant, partial-spawn, escalation, stale identity, restart/duplicate-publication tests | Supervisor backend, attempt identities, durable controls, recovery/fencing, complete cleanup and capability checks | No orphan from tested crash paths; unrelated process unchanged; absent boundaries refuse launch |
| 2: GPU allocator | G1..G3/S4: concurrent allocators, alias/UUID remapping, all-or-nothing reservation, unknown/busy devices, crash recovery | GPU inventory adapter and per-host allocator; count 1..4 and explicit UUID selection | No overlapping participating leases; no lease released while owned work remains |
| 3: model catalog | M1/M2/J4: class/region fixtures, independent invalid profile, path escape, drift and queued-profile replacement | Operator registration and validated catalog; profile-aware preflight; pinned launch identity | Existing KiTS pipeline retained; compatible additional CT model selectable; unsupported inputs explained |
| 4: lifecycle and publication | J3/J4/J6: barriers around case commit, pause/stop races, changed outputs, partial retry and archive guards | Incremental postprocessed publication, control transitions and archive; same output set across attempts | Pause releases resources; resume never rewrites committed outputs; no duplicate ledger/index entries |
| 5: UI and compatibility | U1, real API contracts, view-only denial; browser reconnect/control journeys | Model/GPU selectors and action UI; generated types, recorded mocks, translations and old-run compatibility | Chromium/Firefox real-backend journeys pass; unrelated task/radiomics workflows unchanged |
| 6: host acceptance | Real cgroup/sandbox tests before a tiny authorized GPU run; synthetic input and sentinel process | Fix only reproduced defects; record host evidence and operating instructions | All required safety gates pass on the deployment host; explicit limitations remain visible |

Test procedures, failure handling and lane commands have one owner: `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.
No wave may claim its exit from mocks alone where an OS/GPU guarantee is required. Preserve the failing test and its red/green evidence; do not merge a knowingly red intermediate commit.

Platform references: [systemd process cleanup](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html), [resource controls/delegation](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html), [user-service sandbox restrictions](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html), [logout persistence](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html), [NVIDIA device identity](https://docs.nvidia.com/deploy/nvidia-smi/index.html), [udocker isolation limitations](https://indigo-dc.github.io/udocker/user_manual.html#13-security). Check actual host-version support, not only current manual availability.

## Completion gate

- Every criterion above maps to accepted owner requirement IDs, concrete tests and evidence.
- Required local/CI regressions pass; optional coverage gaps are closed in their designated full environment.
- Host gate proves stop/crash/restart cleanup, effective limits, write/network isolation and zero effect on the unrelated sentinel. Missing host support is a blocked gate, not success.
- Real one-case/one-GPU and two-case/two-GPU KiTS runs retain TST-21 geometry, provenance, indexing and full source/model hash checks.
- Additional installed models need their own compatibility evidence; no claim of lung/brain/pancreas accuracy from a fake CLI.
- Update SEG-*, TSK-*, API-*, BE-*, OPS-*, UI-* and TST-* in their owner docs and stop at the P7g phase boundary.
