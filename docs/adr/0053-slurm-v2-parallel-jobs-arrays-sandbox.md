# ADR-0053 SLURM v2: several jobs at once, job arrays and a sandbox on compute nodes
Status: Proposed (owner delegated the drafting in the session brief; revisit after the first run on a real cluster, OPS-20) · Date: 2026-11-10
Extends: ADR-0034 §6 (SLURM owns allocation; arrays distribute independent case shards). Does not change ADR-0039 (local/server admission) or the task UI contract.

**Context.** The v1 adapter (`../domain/SEGMENTATION_RUNTIMES.md` §SLURM backend) submits one `sbatch` job per attempt and runs one attempt at a time; `max_parallel` and arrays are not implemented, and compute nodes get no Landlock/seccomp sandbox. It was tested only against a fake scheduler. A cohort of hundreds of cases on one allocation leaves cluster capacity idle, and the compute-node boundary is weaker than on `local`/`server`. None of the site facts v2 depends on (GRES syntax, `sacct`, array limits `MaxArraySize`/`MaxSubmitJobs`, signal delivery, Landlock ABI on compute kernels, shared-path visibility) is verified.

**Decision (proposed).**
1. **Several attempts at once.** The runner may hold up to `slurm.max_parallel` submitted attempts (operator key, default 1 = v1 behavior). Each keeps its own durable attempt record, `rw-seg-{attempt}` name, recovery-by-name and `cleanup_pending` fence; one unresponsive scheduler call fences new submissions for all of them.
2. **Job arrays for case shards.** An attempt whose pending cases exceed one shard is submitted as one array (`--array=0-{n-1}%{slurm.array_throttle}`), one shard of cases per index, shard size from the operator file. Shard assignment is written into the attempt record before `sbatch`, so a restart never resubmits or reshards. Each index writes outputs for its own cases only, through the existing incremental validated publication; the attempt finishes when every index is finished or gone, and `exit.json` lists per-index scheduler states. Failed indices are retried only by a new attempt over the unpublished cases. Distributed training/DDP stays out of scope (ADR-0034 §6).
3. **Sandbox on compute nodes when the node supports it.** Inside the allocation the wrapper probes, in a disposable child, the same Landlock (ABI ≥ 3) write roots and seccomp network denial as `local`/`server`, applies what the probe proves and reports enforced / advisory / unavailable per attempt, as ADR-0034 §4 requires. No cgroup or native-command broker is added on compute nodes: the allocation stays the resource boundary. A node without the controls runs unsandboxed only if the operator file says `"sandbox": "optional"`; the default `"required"` fails the index before inference.
4. **UI.** The task form and the jobs view show the attempt's array progress (indices done / running / pending) from the attempt record; the scheduler still assigns GPUs, so no device picker under SLURM.

**Consequences.**
- + Cohort runs use cluster capacity; a restart or a lost `sbatch` answer still never submits twice.
- + Compute nodes get the same unprivileged controls as the server where the kernel allows them, reported honestly where not.
- − More scheduler load (`squeue`/`sacct` per array) and a larger attempt record; per-index logs need bounded retention.
- − Every item above stays unverified until OPS-20 runs on a real cluster; the fake scheduler must grow array and partial-failure cases first (tests first, ADR-0034 §9).

**Rejected.** One `sbatch` per case (scheduler pressure, per-site submit limits); `srun` steps inside one long allocation (holds idle GPUs, couples cases' failures); container runtimes on compute nodes (ADR-0051); retrying failed indices inside the same attempt (breaks the one-attempt, one-record recovery model).

**Revisit when** the v1 adapter has run once on the target site and the facts above are recorded in `../ops/SEGMENTATION_JOB_TEST_PLAN.md`.
