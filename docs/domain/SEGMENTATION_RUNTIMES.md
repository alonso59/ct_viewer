# Segmentation execution backends

Scope: deployment topology, operator configuration and capability contracts for segmentation.
Read when: deploying local/server inference or the SLURM backend.
Depends: ../adr/0034-capability-based-segmentation-runtimes.md, SEGMENTATION.md, TASKS.md, ../ops/DEPLOYMENT.md.

## Deployment matrix

| Backend | Application | Execution | Resource authority | Acceptance |
|---|---|---|---|---|
| `local` | Web app on the workstation, native (OPS-22) | Existing Python/conda environment on the same Linux host | Verified user-service cgroup; unprivileged sandbox | Linux implementation; other desktop OS adapters and Electron remain future work |
| `server` | Web app on `john`, native (OPS-22) | Existing `torch` conda environment | Same owned cgroup/sandbox backend; cooperative host GPU pool | Real process and inference acceptance required |
| `slurm` | Web app plus lightweight runner on an approved submission host (OPS-23) | Compute allocations; never inference on a login node | Scheduler allocation, site policy and declared worker capabilities | Submission adapter tested against a fake scheduler only; real HPC acceptance open (OPS-20) |

The browser and API use the same task/job protocol for every backend. A backend is a deployment choice, not arbitrary code supplied by the browser. Three deployments do not imply that a local API can spawn processes on another machine; remote dispatch needs its own approved queue/transport contract.

## Local/server trust and limits

- Trusted first-party code, model checkpoints and operator-owned conda environments. No hostile-code or cross-UID isolation claim.
- User-service cgroups own complete attempts including setsid descendants. CPU, memory, swap, task and runtime bounds must pass an effective probe before advertising GPU tasks.
- Landlock ABI ≥ 3 restricts content writes/truncation/removal/linking to job/output roots, with explicit device/shared-memory allowances and write/truncate access to the calling PID's `/proc/PID/task` and `/proc/PID/comm` for native thread names. Other PID directories and procfs controls stay denied. Seccomp denies non-Unix socket creation and io_uring setup; descendants inherit restrictions. These controls do not establish a private network namespace, general metadata confidentiality or exclusive device ownership.
- A private per-attempt Unix socket accepts only same-UID callers in the owned cgroup, matching attempt identity, the two approved nnU-Net executable names from the configured environment, and an allocated GPU subset. The watchdog launches each official CLI in its own sandbox within the same resource cgroup, so CUDA can name its own threads without a writable `/proc` tree or a wider device allowlist. The file-queue wrapper remains sandboxed too.
- CUDA visibility selects approved GPUs by UUID. Resolve each UUID to its Linux device minor using the NVIDIA driver's procfs metadata; inventory indices may differ from device minors.
- Admission follows ADR-0039: fresh total minus used memory must meet the operator's `gpu_min_free_mb` budget (default 16384 MiB per GPU). GPU utilization and unrelated compute processes do not independently block selection. Unknown memory refuses admission. One durable host-pool slot serializes participating attempts across workspaces.
- Reservations are retained after runner death. Only verified boundary emptiness and fresh accounting with no GPU process in the owned attempt permit release; unrelated contexts may remain. Ambiguous launch/ownership/accounting requires reconciliation. No arbitrary PID kills, resets or eviction.
- RAM is bounded explicitly. `john` starts with 32 GiB, CPU quota 12, numerical thread count 1 and at most four GPUs selected from physical indices 0..7. Pool membership grants no right to interrupt outside work.
- File-size limits, bounded logs and free-space monitoring reduce storage risk; no aggregate disk quota is claimed. `/dev/shm` is shared runtime storage. Linger is optional: closing a tab does not stop inference, but logout, eviction or reboot may interrupt it.
- R1/R4/R5 remain in force. No sudo, policy changes, runtime package/model downloads or external network requests.

## Operator configuration

Create a private (0600), operator-owned JSON file. Paths below are placeholders; source/model roots must not overlap workspace/derived/state roots except the explicit PRJ-19 case below. The configured interpreter is used explicitly; shell activation is unnecessary during a job.

```json
{
  "deployment": 1,
  "backend": "server",
  "environment": "/operator/conda/envs/torch",
  "workspace": "/operator/workbench/workspace",
  "source_roots": ["/operator/data"],
  "model_roots": ["/operator/nnUNet_results"],
  "derived_roots": ["/operator/workbench/derived"],
  "gpu_pool": ["0", "1", "2", "3", "4", "5", "6", "7"],
  "limits": {"cpus": 12, "memory_mb": 32768, "tasks": 128, "seconds": 43200, "gpus": 4}
}
```

All participating runners on one host/Unix identity must use the same pool state. Default: `~/.local/state/radiology-workbench/gpu-pool`; `state_dir` is intended for an explicitly coordinated installation or disposable test namespace, never an independent production pool per workspace.

PRJ-19 datasets may be listed in optional `managed_datasets`, with each exact dataset present in `source_roots` and its exact `derived/` folder in `derived_roots`. Runtime paths must be canonical and the dataset must contain `.workbench/projects/`. Only the current output subfolder becomes writable; generated/state files cannot be submitted as source inputs. Model/workspace/pool overlap stays forbidden. This exception never grants write access to the whole source dataset.

Run the backend's GPU-free acceptance before inference:

```bash
cd backend
.venv/bin/python -m tools.runner_host_probe --run --unprivileged
```

Then start `scripts/rw-runner.py` with `--deployment /absolute/deployment.json`, the matching `--workspace`, trusted `--plugins`, `--tasks segment.nnunet` and `--concurrency 1`. Admission without a verified configured backend stays closed.

A run uses at most two GPUs (`MAX_GPUS`, fixed for every user and not a task setting), so other runs keep devices of the pool; optional `gpu_ids` (at most two) selects physical indices, resolved against fresh inventory to UUIDs. Configure additional devices by UUID. Empty selection uses ready approved devices automatically. Effective count is capped by pending cases; requested devices are never replaced with outside devices. nnU-Net uses its official partitioned inference CLI. Preprocessing and export workers are 1 or 2 per GPU and kind (`MAX_WORKERS`): with two GPUs and the 12-CPU budget that is at most 2 predictors, 4 preprocessors and 4 exporters.

The task's **Check GPUs** button waits up to 20 seconds for a new runner inventory reading and refreshes the device choices, free memory and per-GPU budget. Every host GPU is listed with a state: ready (green: in the pool, enough free memory, idle), warning (yellow: usable but shared with other work) or unavailable (red: not in the approved pool or not enough free memory; it cannot be picked). It does not reserve devices or start inference. The state uses the allocator's admission rule; launch checks memory again. Shared memory can change during inference.

## SLURM backend

Off unless the deployment file says `"backend": "slurm"`; `local` and `server` are unchanged. The runner stays on the submission host and only submits and watches; the task runs inside the allocation.

```json
{
  "backend": "slurm",
  "slurm": {"partition": "gpu", "account": "research", "qos": "normal", "constraint": "a100", "scratch": "/local/scratch"},
  "limits": {"cpus": 12, "memory_mb": 32768, "tasks": 128, "seconds": 43200, "gpus": 2}
}
```

The other keys are those of §Operator configuration. Every `slurm` key is optional; none accepts flags or shell text.

- **Resources.** One `sbatch` job per attempt: `limits` becomes `--cpus-per-task`, `--mem`, `--time` and `--gres=gpu:N`, with N capped as on a server (pending cases, `MAX_GPUS`, `limits.gpus`). The scheduler picks the devices: a run with `gpu_ids` is refused, and the task form hides the GPU picker and Check GPUs and says the scheduler assigns GPUs, up to the per-run cap the runner reports (`gpus_per_run`). `limits.tasks` and `gpu_pool` are not used.
- **Identity.** The job is named `rw-seg-{attempt}` and its id is kept with the attempt. The attempt is recorded before `sbatch` runs, so a runner that restarts, or that lost the answer of `sbatch`, finds its job again by name and never submits twice. Stopping the runner leaves the job running.
- **Completion.** `exit.json` is written only once `squeue`, or `sacct` where the site has it, shows the job finished or gone; it carries `scheduler_state`. An attempt the scheduler does not list waits 60 s before it counts as gone or never submitted. While the scheduler does not answer, the attempt stays `cleanup_pending` and nothing new starts.
- **Cancel.** `scancel`, also for a job still queued. The submission asks for SIGTERM 60 s before the time limit.
- **Scratch.** HOME, TMPDIR and caches of the task live in a private folder under `slurm.scratch`, else `$SLURM_TMPDIR`, `$TMPDIR` or `/tmp` of the compute node, removed when the task ends. Outputs go straight to the derived root.
- **Boundary.** The scheduler's allocation is the only resource boundary: no Landlock sandbox, user-service cgroup or native-command broker on compute nodes. One attempt at a time; `max_parallel` and job arrays are not implemented.
- **Needs** the workspace, plugins, conda environment, model, source and derived roots at the same paths on the submission host and the compute nodes.

Unverified, because no cluster was available (per-site plan: ../ops/HPC_ACCEPTANCE.md): the site's GRES syntax, `sacct` availability, signal delivery, shared-storage visibility, quotas, and whether the site allows a long-lived runner on the submission host. Reported for the target site: quota-controlled `/lustre/`, separate from HOME and compute-node storage.

## Closure

The accepted work order and current open gates live in SEGMENTATION_JOB_PLAN.md. Environment-specific execution evidence belongs to ../ops/SEGMENTATION_JOB_TEST_PLAN.md; configured paths and fake tests alone never certify a production deployment.
