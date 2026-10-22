# ADR-0033 Supervised segmentation jobs and approved GPU allocation
Status: Superseded by ADR-0034 · Date: 2026-10-22
Supersedes: ADR-0032 (preserves its official nnU-Net pipeline and immutable output decisions)
Amends: ADR-0016 external lifecycle; BE-06 for external-run recovery only

**Context.** P7e completed KiTS inference. The owner now requests additional model profiles, explicit GPU selection, pause/resume/archive, background execution and safe orphan cleanup on a shared no-sudo host. Current direct subprocess supervision and workspace job claims do not enforce those guarantees.

**Decision.** Owner authorized P7g on 2026-10-22. Acceptance criteria and audit: `../domain/SEGMENTATION_JOB_PLAN.md`; test order and evidence: `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.
1. Keep the external file queue and host conda environment; the API never launches host processes. Introduce versioned durable attempt/control records and generation fencing; the API remains the sole project-state writer.
2. A persistent unprivileged supervisor owns each attempt in an OS-enforced boundary, preferably a systemd user service/cgroup. Probe actual resource, storage, filesystem, network and device controls; refuse a job whose required protection cannot be enforced.
3. One participating per-host GPU pool allocates approved UUIDs atomically across workspaces. Users request automatic or explicit devices, with 1..operator-max GPUs (initial maximum 4). Availability checks and cooperative reservations do not exclude unrelated programs.
4. Operators register trusted, fingerprinted single-channel model profiles; the UI exposes valid compatible choices. Support class and region labels; refuse unsupported modality/channels/pipelines before allocating resources.
5. Pause persists complete validated cases, terminates workers and releases verified resources; resume retries unfinished cases in a fenced attempt of the same logical run. Cancel is bounded whole-tree termination. Delete means guarded archival; retain registered outputs/audit records.
6. Recover existing owned attempts before retrying. Missing heartbeat is not proof of exit. Cleanup checks UID/boot/unit/process identity, never accepts arbitrary PIDs and never resets GPUs. Uncertain cleanup blocks allocation.
7. Keep ADR-0004: no application accounts; reviewer stamps do not prove ownership. Same-instance writers share controls. Cross-UID allocation requires separately provisioned host policy; no world-writable control boundary.
8. Adopt tests-first implementation waves and explicit real-host acceptance. Optional dependency/capability skips do not satisfy required gates. Preserve old run records and builtin/radiomics behavior.

**Consequences.**
- + Model selection and job controls fit the existing task/indexing architecture.
- + Verified boundaries and durable ownership reduce orphan/resource interference risks.
- − Some hosts need operator-provisioned capabilities/logout persistence; the app must report blockers without sudo or silent fallback.
- − Pause can repeat an interrupted case; no mid-inference checkpoint or GPU-memory-quota guarantee.
- − Unrelated users remain outside the app's cooperative allocator; host policy is required for exclusive server-wide allocation.

**Rejected.** SIGSTOP as resource-releasing pause; broad PID/name kills or GPU reset; trusting udocker/CUDA_VISIBLE_DEVICES as a security boundary; an API-owned conda process; a new SLURM/Redis/database requirement; silent best-effort production isolation.

P7g is authorized; its safety and host acceptance gates remain mandatory before phase completion.
