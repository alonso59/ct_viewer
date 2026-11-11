# HPC acceptance: site facts and checklist

Scope: what is known about each cluster the HPC deployment is tried on, and what must be run there before it is accepted (OPS-20, OPS-23).
Read when: working on ADR-0055 or ADR-0056, or recording a result from a cluster.
Depends: DEPLOYMENT.md (OPS-20, OPS-23, OPS-24), ../adr/0055-app-as-slurm-job-validated-compute-profiles.md, ../adr/0056-storage-locations-local-and-managed-workspaces.md.

The application and its ADRs are site-agnostic; this file is where a site is named. One section per site.

| Level | Meaning |
|---|---|
| DOCUMENTED | Supported by the site's official documentation |
| USER-TESTED | The owner ran it on the site |
| UNVERIFIED — MARVIN | Needs a run on the site or a formal policy confirmation |
| BLOCKED — MARVIN | Known not to work or not to be permitted; the feature stays off there until a supported mechanism is identified |

A local or fake-scheduler test never changes a level. Only the owner records a result, with its date.

## Marvin — University of Bonn

Source: official documentation at https://wiki.hpc.uni-bonn.de (JavaScript-rendered).
These are site facts, not application defaults; none is built into the code.

| Topic | Fact | Level |
|---|---|---|
| Login nodes | No computations, long-running services, processes after logout or `screen` | DOCUMENTED |
| Access | University network or VPN; SSH key registered through FreeIPA | DOCUMENTED |
| Hosts | `marvin.hpc.uni-bonn.de`; `gpu.marvin.hpc.uni-bonn.de` (`login03`: software environment of the GPU nodes, no GPU) | DOCUMENTED |
| Compute-node SSH | From a login node, while the user has a job on that node | DOCUMENTED |
| Account | `--account` is required; `sshare -U` and `sacctmgr show assoc` list associations | DOCUMENTED |
| GPUs | Requested with `--gpus`; CPUs and memory may follow the GPU count unless given | DOCUMENTED |
| Environment | `--export=NONE` recommended; then `unset SLURM_EXPORT_ENV` before job steps | DOCUMENTED |
| Tools | `sinfo`, `scontrol`, `squeue`, `sacct`, `seff`, `srun --pty` | DOCUMENTED |
| Partitions | `<node-type>_<queue-type>`; node types `intelsr`, `lm`, `vlm`, `sgpu` (32 nodes, 4× A100 80 GB), `mlgpu` (24 nodes, 8× A40 48 GB) | DOCUMENTED |
| Queue limits | `devel` 1 h, `short` 8 h, `medium` 1 day, `long` 7 days; some queues add job and node limits | DOCUMENTED |
| Mail | Notifications need an `@uni-bonn.de` address | DOCUMENTED |
| HOME | 100 GB, persistent, snapshots; no quota command (`du` estimates) | DOCUMENTED |
| Workspaces | `ws_allocate` on `scratch` or `mlnvme`; give the duration (default one day); 90 days, three extensions, 360 days in total; deleted 21 days after expiry; `ws_extend` needs the same `-F`; reminders in `~/.ws_user.conf` | DOCUMENTED |
| Lustre | Set striping before writing; moving files does not restripe them | DOCUMENTED |
| Job-local `/tmp` | Local SSD, about 2 TB per node, private to the job, removed at job end | DOCUMENTED |
| Software | `Miniforge3` module and conda-forge; Anaconda default channels not allowed; Lmod, EasyBuild, Apptainer | DOCUMENTED |
| App as a job | `dev_viewer.sh` on `intelsr_long` (7 days, 4 CPUs, 16 GB): development backend and Vite inside the job; `start`, `stop`, `status`, `log` from the login node | USER-TESTED |
| Connection | VS Code "Forward a Port" to `node:port` reaches the app in the job; the app listens on the node's interface. Works, but whether the login-to-compute segment is encrypted is not established (M12) | USER-TESTED |

### Checklist

| # | Check on Marvin | Decides | Level |
|---|---|---|---|
| M1 | The site formally permits an HTTP application server inside a compute allocation | ADR-0055 §1 as a supported deployment, beyond the tested run | UNVERIFIED — MARVIN |
| M2 | `sbatch --test-only`, then a real `sbatch`, from inside an allocation | ADR-0055 §9 primary path; a refusal makes job submission BLOCKED — MARVIN | UNVERIFIED — MARVIN |
| M3 | If M2 fails: a site-supported submission service (scheduler REST API, user token) | The only permitted alternative, ADR-0055 §9 | UNVERIFIED — MARVIN |
| M4 | `squeue`, `sacct`, `scancel` and `seff` answer from inside an allocation | Watching, cancel and accounting in the Jobs panel | UNVERIFIED — MARVIN |
| M5 | `--gres=gpu:N` is accepted as well as `--gpus=N` | The site's GPU request form | UNVERIFIED — MARVIN |
| M6 | Accounts, partitions, GPU and concurrent-job limits of the owner's association (`sshare -U`, `sacctmgr`, `scontrol show partitions`) | Which profiles validate | UNVERIFIED — MARVIN |
| M7 | `sinfo` reports GPU types in a form discovery can read | The GPU type of a profile | UNVERIFIED — MARVIN |
| M8 | `flock` works on HOME and on a Lustre workspace | Project locks, allocation pool, OPS-24 | UNVERIFIED — MARVIN |
| M9 | HOME filesystem type; SQLite WAL works there | The start probe of ADR-0055 §11 | UNVERIFIED — MARVIN |
| M10 | Compute nodes reach conda-forge, PyPI and npm | Whether `prepare` can run in a job | UNVERIFIED — MARVIN |
| M11 | Another user can reach a port opened by a job, on the node's interface and on its loopback | The exposure that ADR-0055 §4 closes | UNVERIFIED — MARVIN |
| M12 | The real connection path: which segments of the VS Code forward are encrypted; whether a forward can end on the job node's loopback (VS Code Remote on the node); whether the site approves it | The production transport, ADR-0055 §5; until settled no deployment here is called secure | UNVERIFIED — MARVIN |
| M13 | Open OnDemand or JupyterHub is offered | Optional launcher, ADR-0055 §5 | UNVERIFIED — MARVIN |
| M14 | `ws_list` output format; `ws_allocate` and `ws_extend` inside a job | Workspace discovery and commands, ADR-0056 §11 | UNVERIFIED — MARVIN |
| M15 | Workspace, release, environment and model paths are identical on login and compute nodes | OPS-20 shared visibility | UNVERIFIED — MARVIN |
| M16 | SIGTERM reaches the job before the time limit; the app and a task stop cleanly | ADR-0055 §6, OPS-24 | UNVERIFIED — MARVIN |
| M17 | `rw-native.py run` through `rw-app.sbatch`: start, stop, status, log; sign-in with the per-job credential; a second user is refused | ADR-0055 §1–§4; replaces `dev_viewer.sh` | UNVERIFIED — MARVIN |
| M18 | Compute jobs survive the end of the app job and are found again by the next one | ADR-0055 §6 | UNVERIFIED — MARVIN |
| M19 | One GPU segmentation run through a validated profile, end to end | OPS-20 | UNVERIFIED — MARVIN |
