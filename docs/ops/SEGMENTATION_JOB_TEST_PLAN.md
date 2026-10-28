# Supervised segmentation jobs: tests and environment gates

Scope: tests-first acceptance matrix, failure policy and environment audit for P7g; baseline measured in P7f.
Read when: adding supervised-runner tests, debugging a failed lane or signing off P7g.
Depends: ../domain/SEGMENTATION_JOB_PLAN.md, TESTING.md, DEV_ENV.md, ../adr/0034-capability-based-segmentation-runtimes.md.

## Baseline audit: 2026-10-22

The baseline below predates P7g changes. The execution record distinguishes implemented regressions from future acceptance cases; the complete supervised-job implementation is not yet present.
Baseline passes do not prove the later guarantees.

| Check | Observed result | Implication |
|---|---|---|
| Focused backend: nnU-Net, runner, tasks, lifecycle, jobs/spawn, plugins, contract | 46 passed, 2 skipped, 17.49 s | Existing success/cancel/resume paths pass; skips require PyRadiomics |
| Full backend: Python 3.12.3, pytest 9.1.1, four xdist workers, loadscope, numerical threads = 1 | 562 passed, 5 skipped, 56.96 s | Three PyRadiomics modules and two task cases are unverified in this environment |
| Warnings from full backend | 65 NumPy/skimage deprecation warnings in mesh tests | Record separately; do not globally suppress warnings or confuse them with failures |
| Ruff lint / format | Passed; 260 files formatted | Existing Python gate passes |
| Strict mypy | Passed: 197 app/tool/plugin files and 4 scripts | Existing typing baseline passes |
| Requirement checks | 402 IDs; zero errors/warnings | Proposal must preserve owner tables and ID routing |
| Frontend typecheck / eslint | Passed in existing `rw-node` udocker container | No native Node on the remote host (R4) |
| Frontend unit tests | 81 files / 326 tests passed, 164.04 s, in `rw-node` with two workers | Existing UI baseline passes; no real GPU or real-browser rendering exercised |

Repeatable backend baseline (from `backend/`):

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -m pytest -n 4 --dist loadscope -ra
```

Frontend uses the existing Node container through Makefile's `RUNTIME=udocker`; cap Vitest with `npm test -- --maxWorkers=2`.
On this host the wrapper's default Python failed even for `udocker ps` (no curl/pycurl); setting `UDOCKER_PYTHON` to the existing backend venv, which already contains pycurl, restored execution. Use an operator-selected absolute path; do not install system tools or hardcode a personal path into the workflow.

## Pipeline and host findings

| Finding | Evidence | Required preparation in P7g wave 0 |
|---|---|---|
| Image publication is not gated by tests | `.github/workflows/build.yml` builds/pushes directly; no test job or dependency | Add PR/push verification; publication must depend on successful required checks |
| Documented nightly/full gates have no workflow here | Only build workflow is checked in | Add explicit browser, full-radiomics and manual host acceptance lanes; label unavailable gates honestly |
| Backend parallelism is unbounded by default | `make test`: `-n auto`; this host reports 64 CPUs | Configurable bounded worker default, loadscope, one numerical thread per worker; test serial and bounded parallel |
| Frontend workers are not bounded in config | `vitest.config.ts` has no worker cap | Add a configurable cap and record runtime/container version |
| Backend dependencies are range-based | `pyproject.toml`; no checked-in backend lock | Produce a reviewed reproducible CI dependency resolution; keep the pinned PyRadiomics revision; record installed versions |
| Optional dependency skips can mask lost coverage | PyRadiomics importorskip in three modules and two task cases | Separate lean and full lanes; required full lane preflights imports and fails on missing packages |
| Most backend tests use inline workers | `tests/conftest.py`; `test_jobs_spawn.py` supplies some actual spawn coverage | Add real subprocess/daemon/restart tests; inline tests cannot prove isolation or orphan cleanup |
| Process-test cleanup is incomplete | nnU-Net cancellation test has no finally; browser runner afterEach signals without awaiting exit | Register finalizers immediately, wait/reap with deadlines, escalate only verified test-owned processes |
| Fake CLI environment inherits host settings | `test_nnunet.py::plugin_env` copies os.environ | Strip host model/GPU/failure-injection settings; fake executable discovery must fail closed |
| Canvas warnings occur in jsdom | Existing Vitest emits getContext-not-implemented | Keep DOM assertions separate from real browser/WebGL verification; do not count a jsdom pass as rendered-image evidence |
| Host has systemd/cgroup v2 but logout persistence is disabled | Read-only: systemd 255.4, user manager present, `Linger=no`, unprivileged user namespaces enabled | Probe delegated controllers, enforced namespaces/device access and service lifecycle; report logout prerequisite; no automatic host-policy changes |

No GPUs, services, host resource limits, lingering settings or user processes were changed during this audit. Availability of a kernel feature is not proof that the user service can enforce it.

## P7g execution evidence (2026-10-22)

| Gate / implementation | Result |
|---|---|
| Tests first | Initial runner/probe failures retained. Further red checkpoints cover configuration/selection, effective sandbox writes/network, cleanup generations, API restart, duplicate mask registration, worker budgets, long-path Manager IPC, ITK/native thread naming, native launch policy, cancellation at claim and managed outputs |
| Full backend compatibility | 759 passed, zero skipped, 386.19 s; Python 3.12.15 in existing `rw-build` udocker, actual non-root UID, four workers/numerical threads 1 and full PyRadiomics. Final project-reader/GPU-display follow-ups also pass their targeted tests; the final CI full lane remains a separate gate |
| Frontend units | 89 files / 345 tests passed, 194.81 s in `rw-node`; eslint, strict tsc and knip passed. Existing canvas warnings remain separate from rendering acceptance |
| GPU-free host lane | 21 passed, 60.75 s: actual Landlock source mutations/proc-fd escape, nonlocal sockets, inherited restrictions, Manager IPC, native thread policy, per-CLI sandbox, cancel/crash/setsid cleanup and unrelated sentinel survival. Normal container CI excludes this opt-in lane |
| Original strict host profile | Resource bounds/setsid containment passed; namespace read-only/device/network protections failed and the disposable source sentinel changed. Kept as failed evidence; strict readiness is not advertised |
| ADR-0034 host profile | User-cgroup limits, source visibility/unchanged content, denied writes/nonlocal sockets and setsid containment passed with Landlock ABI 4/seccomp. `/dev/ptmx` denial proves only the tested write restriction, not exclusive GPU ioctl/device isolation |
| Native GPU acceptance | One-case/server GPU 0 and two-case/local GPUs 0/6 completed official prediction/postprocessing. Indexed/served masks have valid geometry/labels; all 191 source and 13 model file hashes unchanged. Retained workspaces: `/tmp/rw-nnunet-acceptance-tn34venf`, `/tmp/rw-nnunet-acceptance-wflvblz2` |
| Browser environment | Initial 11/14 passed; missing radiomics and Firefox WebGL2 were explicit failures. Reused full test packages; proved software Firefox WebGL2 with existing Xvfb. Full 62-test Chromium/Firefox lane is being checked; no full-browser pass claimed |
| CI/deployment | `Dockerfile.verify` built in CI; its first check failed on the omitted Ruff config, fixed below. Product image/Docker acceptance remains open. Production was updated to frozen release `3.0.0-local-20261022-picker` (`b62c770`); HTTP health, SPA/task asset hashes, item API and available runner passed |

### Containment follow-up

Executor shell and parent Codex app-server both reported `CODEX_HOME=/home/alonso/.codex-gpinedo`; branch `version_3-dev-seg`, existing uncommitted changes preserved.
Original systemd 255.4 probe: `read_only`, `device_policy`, `network_isolation`, `source_unchanged` failed; random unit `rw-containment-probe-3ee72e25d49546cb97b2f3282768fc27.service` was inactive/collected. This was GPU-free and changed only its disposable fixture.
The probe was hardened tests-first against false readiness after failed cleanup, absent effective blockers and a unit collected before explicit stop.

User lingering remains disabled; no independently bounded scratch/output filesystem is configured. Standalone unshare is denied. No host policy or driver changes were made.
The owner accepted ADR-0034: quota, exclusive devices and logout survival are declared limitations rather than administrator prerequisites. The configured backend passed its required user-service/Landlock/seccomp effects; no full P7g wave exit is claimed.

`python scripts/rw-runner.py --preflight` retains original strict prerequisites. Configured capability checks use `--preflight --deployment /absolute/config.json --verify-host`.
The opt-in capability probe is `cd backend && .venv/bin/python -m tools.runner_host_probe --run --unprivileged`; it creates one random, bounded, GPU-free service and its own sentinel/listener, then stops/collects it. Omitting `--unprivileged` retains the original strict probe.
Checks require exact booleans, unchanged sentinel bytes and verified cleanup. A successful service launch alone never certifies containment.
Lifecycle host acceptance (TSK-15, 2026-10-22, GPU 0, real KiTS 2023 profile, 3 synthetic cases, `cd backend && .venv/bin/python -m tools.nnunet_acceptance --lifecycle --items 3 --gpus 0 --gpu-cap 1`): pause after the first committed case → `paused` with acknowledged control, lease released, no live attempt unit, 1 mask kept; resume → `completed` 3/3 with the committed mask hash unchanged; cancel during inference → `cancelled` with verified cleanup, lease released, no unit; archive hides the run; source and model hashes unchanged. The first attempt exposed the stdlib-shadowing defect (runner refused the profile); fixed by running plugin scripts with `-I` (`test_plugin_scripts_run_isolated_from_their_own_folder`).

Unconfigured GPU admission remains closed. Verified configured execution permitted only the authorized synthetic runs above; complete P7g acceptance remains open.

Closure follow-up (2026-10-22): `make test-host-browser` passed both Chromium and Firefox (59.9 s) against a real HTTP API and user-service supervisor: reconnect/API restart retained one attempt; pause/resume/cancel/archive waited for verified cleanup and released the lease. Retained workspace `/tmp/rw-browser-host-dd7byg9u`; its source hashes stayed unchanged. This lane uses a gated threshold CPU fixture and synthetic GPU telemetry, never CUDA, models or the production workspace.
The effective host lane passed 21 tests (61.05 s). Three native-broker fixtures first failed admission because they used a one-CPU limit and no test verifier; they now meet the actual admission contract without weakening production validation. Frontend compatibility: 341 tests / 87 files passed (188.54 s), strict TypeScript, eslint and knip passed. Full backend recheck and full browser/CI lanes are still running.
CI run `39836296307` built `Dockerfile.verify` successfully but failed `make lint`: the source allowlist omitted `ruff.toml`. The corrected context includes both that configuration and its own ignore file, with a regression test. CI now also builds the product image, runs Docker TST-10/IBSI/arbitrary-UID/source-hash acceptance, and retains the tested image for udocker verification.

2026-10-23 follow-up: select-all across filters/pages, 50/100/200/500-row sizing and fixed-height scrolling passed in both browsers. The focused browser lane passed 9/10; the remaining Firefox runner journey then passed (1.5 min) after waiting for its lazy task heading. A concurrent project-list mutation reproduced a real API failure and now has a deterministic regression. Release packaging now copies a private root before trimming/stripping; a suite affected by mutation of its shared verification root is not counted as a full pass. Required full-browser/CI/image closure stays open. Manual GPU refresh waits for a new runner sample without allocation; displayed idle status now shares the allocator rule (memory/utilization/context), covered by regression tests. The production runner configuration was verified at CPU 12, RAM 32 GiB, maximum 4 GPUs from approved indices 0..6; no new GPU inference was launched.

Native-runtime failures were reproduced before fixes: deep AF_UNIX temp paths, ITK/NumExpr thread excess, and CUDA error 304 caused by thread-name writes. Broad `/proc` access was rejected by automatic review and never applied. Only each calling PID's metadata was allowed; per-CLI sandboxes preserve the wrapper's restrictions. No outside process, source or model was changed. Numerical/deprecation warnings remain visible.

## Tests-first execution contract

For each implementation wave:
1. Assign accepted requirement IDs in owner docs; link each test to its criterion and those IDs.
2. Write public-boundary tests with independent expected results, fixture data and bounded failure diagnostics.
3. Run them against the previous implementation. Record the expected behavioral failure, not just an import/syntax error. Introduce minimal interfaces only where needed to reach the assertion.
4. Implement the smallest change that satisfies them; rerun targeted tests and directly affected regression modules.
5. Exercise the designated real-process/host lane; run full gates at the integration boundary. No xfail/skip, snapshot refresh, tolerance inflation or automatic retries to turn a real regression green.

Fast tests may fake clock, GPU inventory and service adapter. They must still exercise allocation/state/persistence code. Real lifecycle tests launch actual harmless subprocesses.
Every process fixture records ownership before returning control, always cleans up in finally/finalizers, and captures stdout/stderr, attempt IDs and last observed state on timeout.
Use readiness files/events/barriers and monotonic deadlines instead of fixed sleeps to arrange races. Inject a clock for lease/freshness/timeout unit tests; actual signals need bounded wall time.
Use property/state-machine testing for control sequences and crash points; keep failing seeds in regression cases. Use synchronization to guarantee collision in concurrency tests.

## Acceptance matrix: concrete cases to write

File names below are proposed, not already implemented. Split existing combined tests into focused assertions where doing so improves diagnosis.

| Criteria | Proposed tests / independent oracle |
|---|---|
| M1 | `tests/test_nnunet_catalog.py`: enumerate two valid profiles plus missing/corrupt sibling; stable IDs/order and explicit reasons; refresh generation changes on artifact/profile change; no host paths/commands in public payload |
| M1/M2 | Reject traversal, absolute/outside-root and symlink escape, unregistered root, duplicate profile ID, incomplete fold set, absent trainer and altered checkpoint; zero worker launches and no lease acquired |
| M2 | `tests/test_nnunet_profiles.py`: integer labels without regions_class_order; region tuples/order; background rules; invalid/duplicate values and label/name conflicts; profile labels derive from fixture dataset.json, not copied expected implementation output |
| M2 | CT single-channel succeeds; incompatible modality/channel count/multi-configuration/cascade is unavailable with a stable reason; one invalid model does not disable KiTS; changed profile while queued is rejected before execution |
| G1 | `tests/test_gpu_inventory.py`: physical indices 0/6 map to fixture UUIDs despite reversed/reordered CUDA visibility; UI IDs never become local ordinals; duplicates by index+UUID alias are rejected |
| G1/G3 | Missing nvidia-smi/NVML, permission error, N/A memory, stale inventory, removed GPU, busy GPU and foreign context each yield unavailable/unknown, never implicitly free; cap/count bounds and outside-pool selection are rejected |
| G2 | `tests/test_gpu_allocation.py`: synchronized real allocator processes share one durable host slot across workspaces; exactly one wins and stale release cannot free it. The initial conservative policy also queues disjoint sets |
| G2 | Barrier at each reservation step; request all-or-nothing; timeout/failure never strands a partial lease; lock order avoids deadlock; cross-workspace state is shared; malformed/symlink pool state refuses unsafe allocation |
| G2/S4 | Owner exits while descendants survive; missing heartbeat, PID reuse, host reboot and delayed stale release must not free a newer/live generation; cleanup failure blocks the affected devices |
| J1 | `tests/test_external_attempts.py`: duplicate/reordered controls, replay after crash, partial JSON/JSONL writes, atomic replace failure and disk full; recover last acknowledged state; stale attempt cannot publish or change successor state |
| J1/J2 | Real backend and supervisor: restart API during prediction/postprocess/publication; no second predictor; recover cursor once; no duplicate item/ledger/index rows; old terminal and builtin records retain documented behavior |
| J3/J4 | `tests/test_segmentation_lifecycle.py`: pause before claim, during inference, postprocess and immediately before/after atomic commit using barriers; incomplete output is never indexed; paused means zero owned live workers and zero leases |
| J3/J4 | Resume on another approved GPU; completed mask bytes/hashes unchanged; only unfinished cases run. Changed image/profile/model/output blocks resume. Completed-with-errors retries failed items without duplicating successes |
| J4 | Crash after mask rename but before progress/registration; reconcile artifact identity and register once. Crash after registration but before acknowledgement must not rerun or duplicate it |
| J5 | Cancel before claim and race with claim; repeated cancel; cancel vs complete/pause; TERM ignored then KILL; second worker spawn raises; log/claim write fails; every started descendant accounted for |
| J6 | `tests/test_task_archive.py`: active/pausing/reconciling/cleanup-pending archive returns conflict; queued deletion cannot race into launch; terminal archive hides only history; masks/viewer/provenance remain reachable; no source/output deletion |
| S1/S2 | `tests/test_runner_capabilities.py`: missing user manager/delegated controller/namespace/device rule/required limit prevents launch with a specific reason; no advertised strict mode after fallback; budgets bounded across concurrent jobs |
| S1 | Real disposable cgroup: child/grandchild and setsid descendant stay within attempt boundary; CPU/memory/pids/runtime limits are effective. Exercise exceed-limit behavior only inside verified test cgroup with conservative operator-approved limits |
| S1 | Real sandbox: writes to copied sources/model/outside sentinel denied; scratch/derived writes succeed; symlink escape denied; attempted network to a disposable local listener is denied. No external traffic or real patient data |
| S1/S2 | Disk full during publication, excessive logs and low space stop only the owned job and preserve committed files. Local/server report no aggregate quota under ADR-0034; an optional quota-backed deployment must prove its tiny disposable hard limit separately |
| S3/S4 | `tests/test_runner_cleanup.py`: unrelated sentinel under same UID and separate unit survives cancel, hard runner crash, plugin crash and orphan cleanup; unknown/foreign UID/unit/start identity is never signalled |
| S3/S4 | Worker leader dies while its grandchild ignores TERM; cleanup waits/escalates for descendants; unit-empty plus GPU-context checks gate release; lingering context yields cleanup_pending, never GPU reset or arbitrary kill |
| U1 | Vitest: catalog/GPU selection sends IDs and normalized cap; stale options and unavailable profile disable Run with reason; pending controls are not displayed as completed; every lifecycle state translated; view-only hides writes |
| U1/J2 | Playwright on real API/supervisor: start -> close all pages -> reopen -> progress; pause -> no leases -> resume -> complete; cancel -> cleanup; archive; API restart; second browser sees the same durable state |
| U1 | Direct API requests from view-only routes cannot pause/cancel/resume/archive/clean. No arbitrary argv, executable, host path, PID or cgroup may be supplied through control payloads |
| V1 | Adversarial parent environment (real-looking nnUNet_results/CUDA_VISIBLE_DEVICES/FAKE_* settings) cannot change fake fixture behavior; force an assertion failure after spawn and verify fixture finalizer reaps owned descendants |

## Environment lanes and gates

| Lane | Environment and trigger | Required evidence |
|---|---|---|
| Fast contract | CPU-only, no CUDA/torch/model install; every PR | Profile/schema/path/state tests, API snapshot/types, frontend units, lint/types/requirements; zero dependency on host GPU IDs |
| Real-process fake inference | Linux, synthetic NIfTI, fake official CLI only; every PR | Process trees/signals, allocation races, daemon/API restart, incremental indexing, source/model hashes; serial and bounded parallel |
| Full compatibility | Reproducible Python 3.12 + pinned radiomics extra and locked Node deps; required integration/publication gate | Full pytest incl. radiomics/IBSI; Vitest; generated API/types/mock consistency; dead code and bundle size |
| Browser | Chromium and Firefox with provisioned browsers, real backend and disposable workspace; integration/publication gate | Lifecycle/reconnect/view-only plus existing converter, task, curation, viewer and radiomics journeys; TST-07 before/after |
| OS isolation | `make test-host`, explicit supported host, private disposable units, no GPU | Required backend cgroup/write/network effects, descendant crash cleanup, sentinel unchanged; absent required capability blocks acceptance. Optional namespace/quota/logout limits stay explicit |
| GPU acceptance | Explicit operator-approved idle UUIDs; manual phase sign-off | TST-21 one/two-case runs plus release/recovery/control checks; no device reset/compute-mode changes; no grabbing busy GPUs |

CI runners must not receive production model roots, workspace paths or GPU reservations. All writes belong under tmp_path or a run-created browser directory; data are synthetic. Never run the shared host out of memory, disk or processes to test a limit; prove the disposable boundary first.
Use separate tmp roots, pool namespaces, sockets/ports and fake model roots per worker. Do not weaken pool coordination tests by accidentally giving competitors different pool namespaces.
GPU-free host/browser fixtures report 64 GiB of synthetic VRAM and map only their synthetic UUID to `/dev/null` through a test-owned launcher. This permits testing real user-service and sandbox effects under the accepted memory policy without exposing a real GPU. Actual UUID/device-minor resolution remains a separate GPU acceptance obligation.
Pin node package installation to package-lock; preflight browser binaries and backend dependencies. E2E runners must prove the backend Python is executable in the chosen container/host topology; a Node-only image is not assumed to contain host conda Python.
Record dependency/runtime versions, command, commit, environment lane, skips, seeds, logs and teardown outcome. Upload diagnostics on failure with synthetic paths redacted; mark incomplete lanes as incomplete.
Run a deterministic collision case in both serial and bounded-parallel contexts; repeat race/fault cases only for documented scheduling coverage, never as automatic pass-on-retry.

## Failure investigation policy

1. Preserve the first failure, exact command, versions, fixture identities, seed, logs, process/lease state and exit code. Clean only verified test-owned resources.
2. Reproduce the smallest case under the recorded environment, then its module serially. Compare with the known baseline and the normal bounded-parallel lane.
3. Classify: product regression, test race/leak, missing/mismatched dependency, sandbox/port/permission issue, stale generated contract or unsupported host capability.
4. Product regression: fix production behavior with the failing regression test retained. Harness defect: fix isolation/readiness/finalizers and add a test of that failure mode. Environment defect: make preflight fail clearly and repair the declared environment; do not alter product assertions to suit it.
5. Review contract/schema/mock changes semantically before regeneration. Never blindly bless snapshots or rerecord real defects; never remove a failing unrelated suite from the gate.
6. Rerun the affected tests plus coupled pipelines. At integration run full required lanes once green; preserve existing skipped lanes as gaps until their designated environment executes them.

P7g sign-off requires every proposal criterion mapped to accepted requirements and passing tests, full compatibility/browser gates, and real host evidence. Fast mocks do not certify containment, GPU release or logout survival.
