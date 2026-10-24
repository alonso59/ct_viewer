# ADR-0035 Durable DICOM source operations and verified resume
Status: Accepted · Date: 2026-10-23 (owner: implement the plan and comply with this ADR)
Partially supersedes: ADR-0016 §3, only the execution of DICOM discovery/dry-run/conversion units in the shared worker pool. Other builtin tasks retain their runtime.
Extends: ADR-0013 (complete-series browsing), ADR-0021 (recoverable converter overlay).

**Context.** DICOM Open mode limits files before grouping series; discovery rules differ between the picker, detector and converter. Dry runs depend on a long HTTP request and disposable records. Shared-pool future cancellation cannot prove a native reader stopped. Users require fast discovery, a recoverable background window and continuation after interruption, with or without a project.

**Decision.**
1. Reuse the existing converter overlay and job/run services. A durable workspace source-operation record links its inventory, dry-run plan and optional project/workspace conversion run; it does not replace run records or create a hidden project.
2. Persist source-operation controls and attempts before acknowledging them. Browsers reconnect by opaque IDs. Backend restart reconciles interrupted work; it does not imply execution survived the restart.
3. Page complete series, never a prefix of their slices. Share extension-independent DICOM recognition through the task boundary; preserve source guards, metadata ownership and identity policy.
4. Run DICOM work in owned, bounded processes inside the same OCI container, managed by the existing job driver. Process ownership/termination is specific to that operation; cancelling it must not kill the shared pool or other jobs. This remains a builtin task, without host runners, sudo or a new runtime service.
5. Resume the same logical operation/run with a fresh fenced attempt only after prior execution is confirmed stopped. Validate pinned inputs/settings, output hashes and geometry; skip verified commits, reconcile incomplete commits, and refuse incompatible changes.
6. Workspace resume fills only the originally allocated unfinished dataset. A completed dataset remains write-once. A separate conversion allocates a new dataset; project output locations remain ADR-0014.
7. Phase is an optional separately recorded analyzer step after committed conversion, preserving ADR-0020; conversion success and analyzer failure are distinguishable and independently retryable.
8. Keep existing synchronous endpoints as compatibility adapters. Add asynchronous source-operation endpoints and paged plan/series reads; existing response shapes are not silently replaced with 202.

**Consequences.**
- Source operations require durable inventory, controls, cleanup evidence and retention; browser storage holds identifiers/preferences only.
- DICOM-specific process/resource admission and crash tests are required before UI adoption. Unknown cleanup blocks resume.
- A dry run reads no pixels or writes image outputs; ETA states its measurement basis and uncertainty.
- Owner changes on acceptance: SOURCES, DICOM_CONVERTER, TASKS, ANALYZERS, API, backend ARCHITECTURE, UI_SHELL and TESTING, as mapped in DICOM_JOB_PLAN.md.
- The owner authorized implementation and tests on 2026-10-23. Acceptance is not evidence of implementation, passing tests or deployment readiness.

**Rejected alternatives.**
- Increase the 500-file limit: a larger prefix can still split a series.
- Browser-only persistence or background fetch: cannot recover server work reliably.
- Kill a shared executor to cancel one conversion: interrupts unrelated work.
- Use file existence alone to resume, or automatically rerun after restart: risks accepting partial data or launching duplicate attempts.
