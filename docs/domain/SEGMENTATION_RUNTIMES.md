# Segmentation execution backends

Scope: deployment topology, operator configuration and capability contracts for segmentation.
Read when: deploying local/server inference or preparing SLURM support.
Depends: ../adr/0034-capability-based-segmentation-runtimes.md, SEGMENTATION.md, TASKS.md, ../ops/DEPLOYMENT.md.

## Deployment matrix

| Backend | Application | Execution | Resource authority | Acceptance |
|---|---|---|---|---|
| `local` | Web app in Docker/udocker on the workstation | Existing Python/conda environment on the same Linux host | Verified user-service cgroup; unprivileged sandbox | Linux implementation; other desktop OS adapters and Electron remain future work |
| `server` | Web app in Docker/udocker on `john` | Existing `torch` conda environment | Same owned cgroup/sandbox backend; cooperative host GPU pool | Real process and inference acceptance required |
| `slurm` | Web app plus lightweight runner on an approved submission host | Compute allocations; never inference on a login node | Scheduler allocation, site policy and declared worker capabilities | Configuration contract only; submission adapter and real HPC acceptance deferred |

The browser and API use the same task/job protocol for every backend. A backend is a deployment choice, not arbitrary code supplied by the browser. Three deployments do not imply that a local API can spawn processes on another machine; remote dispatch needs its own approved queue/transport contract.

## Local/server trust and limits

- Trusted first-party code, model checkpoints and operator-owned conda environments. No hostile-code or cross-UID isolation claim.
- User-service cgroups own complete attempts including setsid descendants. CPU, memory, swap, task and runtime bounds must pass an effective probe before advertising GPU tasks.
- Landlock ABI ≥ 3 restricts content writes/truncation/removal/linking to job/output roots, with explicit device/shared-memory allowances and write/truncate access to the calling PID's `/proc/PID/task` and `/proc/PID/comm` for native thread names. Other PID directories and procfs controls stay denied. Seccomp denies non-Unix socket creation and io_uring setup; descendants inherit restrictions. These controls do not establish a private network namespace, general metadata confidentiality or exclusive device ownership.
- A private per-attempt Unix socket accepts only same-UID callers in the owned cgroup, matching attempt identity, the two approved nnU-Net executable names from the configured environment, and an allocated GPU subset. The watchdog launches each official CLI in its own sandbox within the same resource cgroup, so CUDA can name its own threads without a writable `/proc` tree or a wider device allowlist. The file-queue wrapper remains sandboxed too.
- CUDA visibility selects approved GPUs by UUID. Inventory is sampled immediately before reservation; unknown/busy devices refuse admission. One durable host-pool slot currently serializes participating attempts across workspaces, conservatively bounding aggregate resource use.
- Reservations are retained after runner death. Only verified boundary emptiness and fresh GPU accounting permit release; ambiguous launch/ownership/accounting requires reconciliation. No arbitrary PID kills, resets or eviction.
- RAM is bounded explicitly. `john` starts with 32 GiB, CPU quota 12, numerical thread count 1 and at most four GPUs selected from physical indices 0..6. Pool membership grants no right to interrupt outside work.
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
  "gpu_pool": ["0", "1", "2", "3", "4", "5", "6"],
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

`gpu_cap` supports 1..4; optional `gpu_ids` selects physical indices 0..6, resolved against fresh inventory to UUIDs. Empty selection uses available approved devices automatically. Effective count is capped by pending cases; requested devices are never replaced with outside devices. nnU-Net uses its official partitioned inference CLI. `torchrun` is not required for independent cases and supplies no isolation/reservation boundary.

## SLURM preparation (deferred)

Reported: quota-controlled `/lustre/`, separate from HOME and compute-node storage. Unverified: shared visibility on submission/compute nodes, quota/headroom, environment availability, partition/account/QOS/GRES policy and permitted background submission.
Use an operator-configured Lustre workspace/derived root and separately configured node-local scratch; copy only complete validated outputs into derived storage. The future adapter will persist scheduler identity, use approved sbatch/srun resources and scheduler-provided GPU visibility, and reconcile before retry. Job arrays distribute independent case shards across nodes. No cluster access or actual scheduler execution is claimed.

## Closure

The accepted work order and current open gates live in SEGMENTATION_JOB_PLAN.md. Environment-specific execution evidence belongs to ../ops/SEGMENTATION_JOB_TEST_PLAN.md; configured paths and fake tests alone never certify a production deployment.
