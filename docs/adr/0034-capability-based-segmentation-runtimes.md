# ADR-0034 Capability-based segmentation runtimes without administrator access
Status: Accepted (§5 admission criterion superseded by ADR-0039) · Date: 2026-10-22
Supersedes: ADR-0033 (preserves catalog, lifecycle, ownership and immutable-output contracts)
Amends: ADR-0016 external lifecycle; ADR-0007 host-runner deployment; BE-06 external recovery

**Context.** The owner has no sudo or administrator support. The standalone host enforces resource cgroups but failed namespace/device isolation; strict storage and logout requirements prevent deployment. The owner authorizes a revised architecture and three setups: local, standalone GPU server and SLURM HPC. HPC access is currently unavailable; a separate quota-controlled Lustre filesystem is reported, not verified.

**Decision.**
1. Keep one web application and external file queue. Introduce interchangeable execution backends behind durable attempt/control records: `local`, `server`, `slurm`. The API never launches host processes or scheduler commands. Electron remains P8.
2. Use operator-selected existing conda environments for trusted first-party inference. Conda isolates dependencies; it supplies no OS confinement, GPU reservation or cleanup guarantee. No environment creation, package/model downloads or system-policy changes during a job.
3. Local/server backends use verified user-service cgroups where available; require bounded CPU/RAM/tasks/runtime and verified attempt ownership/cleanup before GPU admission. A platform without an accepted process/resource backend remains unavailable. Future desktop backends must meet their declared capabilities.
4. Apply additional unprivileged protection when supported, including Landlock write restrictions and seccomp network denial. Probe effects in disposable children; report enforced, cooperative/advisory and unavailable protections separately. No namespace, hostile-code, device exclusivity, aggregate disk quota or logout-survival claim without evidence.
5. Standalone GPU reservations coordinate participating workspaces under one Unix identity/host pool. Resolve approved devices to UUIDs, refuse busy/unknown devices, retain uncertain leases and never evict outside work. Visibility variables are cooperative controls.
6. SLURM owns cluster GPU/CPU/memory/time allocation. A lightweight runner submits configured jobs from an approved submission host; heavy inference runs only in allocations. Never replace scheduler GPU visibility with standalone physical IDs. Arrays distribute independent case shards across nodes; distributed model training/DDP is outside scope.
7. Operator configuration selects backend, environment, roots, resource budgets and scheduler policy. Browser settings contain catalog/resource IDs only. Lustre workspace/output and node-local scratch are distinct; compute-node path/environment/quota visibility must be verified. No patient data staging outside approved roots.
8. Lack of quota or lingering is reported explicitly rather than universally blocking deployment. Use conservative file limits, disk preflight/monitoring and bounded logs; these are not aggregate quotas. Closing a browser does not cancel work. Logout/node eviction may interrupt it; ownership reconciliation precedes retry.
9. Preserve tests-first waves, cleanup-pending fencing, incremental validated publication and no source/model mutation. Rebaseline host acceptance to the declared backend capabilities; retain earlier strict failures as evidence. A configured backend is not certified until its process/resource/recovery tests pass.

**Consequences.**
- + Supports permitted no-sudo deployment and scheduler-managed HPC without changing the task UI contract.
- + Stronger unprivileged controls can be adopted without requiring administrator changes.
- − Trusted code and shared Unix identity remain part of the deployment trust model; cooperative controls do not isolate hostile programs or unrelated users.
- − Runtime acceptance is per deployment. Fake scheduler tests cannot certify the inaccessible HPC.

**Rejected.** Disabling server security policy; privileged installs; describing conda/torchrun/udocker as a sandbox; silent downgrade; arbitrary browser shell/sbatch flags; requiring SLURM on standalone hosts; implementing Electron during P7g.

Runtime configuration and backend contracts: `../domain/SEGMENTATION_RUNTIMES.md`. Work order and acceptance remain owned by `SEGMENTATION_JOB_PLAN.md` and `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.
