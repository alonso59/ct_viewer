# HPC acceptance: site facts and checklist

Scope: what is known about each cluster the HPC deployment is tried on, and what must be run there before it is accepted (OPS-20, OPS-23).
Read when: working on ADR-0055 or ADR-0056, or recording a result from a cluster.
Depends: DEPLOYMENT.md (OPS-20, OPS-23, OPS-24), HPC_INSTALL.md, STORAGE_SETUP.md, ../adr/0055-app-as-slurm-job-validated-compute-profiles.md, ../adr/0056-storage-locations-local-and-managed-workspaces.md.

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
| Connection | VS Code "Forward a Port" to `node:port` reaches the app in the job; the app listens on the node's interface. Works, but whether the login-to-compute segment is encrypted is not established (M7) | USER-TESTED |

### Acceptance plan

Ordered by priority. `dev_viewer.sh` stays the USER-TESTED reference; `rw-app.sbatch` replaces it only after groups A to F pass here.
Procedures: HPC_INSTALL.md. Record each result in the Level column with its date; a failed or forbidden item becomes BLOCKED — MARVIN.

| # | Check on Marvin | Pass when | Level |
|---|---|---|---|
| **A** | **Application job startup and shutdown** | | |
| M1 | `rw-native.py prepare` inside an interactive allocation | A release is built; compute nodes reach conda-forge, PyPI and npm | UNVERIFIED — MARVIN |
| M2 | `rw-app.sbatch start`, `status`, `log`, `stop` with the owner's account and a CPU partition | The job runs, the app answers, `status` shows node and port, `stop` ends it and removes both files in HOME | UNVERIFIED — MARVIN |
| M3 | The site formally permits an HTTP application server inside a compute allocation | A written answer from the site; the tested run alone is not approval | UNVERIFIED — MARVIN |
| **B** | **VS Code forwarding with `BIND=loopback`** | | |
| M4 | Open the job's node in VS Code Remote-SSH and forward the port | The sign-in page loads through the forward; record whether the site allows a VS Code server on a compute node | UNVERIFIED — MARVIN |
| **C** | **Existing forwarding with `BIND=node`** | | |
| M5 | From VS Code on the login node, "Forward a Port" to `<node>:<port>` | The sign-in page loads, as with `dev_viewer.sh` | UNVERIFIED — MARVIN |
| **D** | **Network exposure and transport security** | | |
| M6 | From a second account or node, connect to the job's port in both bind modes | Recorded: who can reach the interface and who can reach loopback | UNVERIFIED — MARVIN |
| M7 | Establish which segments of each forward are encrypted (site documentation or support) | Recorded per bind mode; until then no deployment here is called secure | UNVERIFIED — MARVIN |
| M8 | Open OnDemand, JupyterHub or another site-approved forward is offered | Recorded; optional launcher only | UNVERIFIED — MARVIN |
| **E** | **Session authentication and credential protection** | | |
| M9 | Unauthenticated request, wrong code, right code, second browser | Refused, refused, accepted, asks again | UNVERIFIED — MARVIN |
| M10 | Inspect the job log, `scontrol show job` and `squeue` output; modes of the two HOME files | The code appears nowhere but its 0600 file; the folder is 0700 | UNVERIFIED — MARVIN |
| M11 | After `stop` and after a time-limit end | The old code no longer signs in; a new job has a new one | UNVERIFIED — MARVIN |
| **F** | **HOME file locking and SQLite WAL** | | |
| M12 | `rw-native.py run` start check on HOME; HOME filesystem type | The check passes, or names what fails; recorded | UNVERIFIED — MARVIN |
| M13 | `flock` on a Lustre workspace (project locks, OPS-24) | Two processes on two nodes exclude each other | UNVERIFIED — MARVIN |
| **G** | **Nested `sbatch` from the app job** | | |
| M14 | `sbatch --test-only`, then a trivial `sbatch`, from inside the app job; also `squeue`, `sacct`, `scancel`, `seff` | Accepted; a refusal sets job submission to BLOCKED — MARVIN | UNVERIFIED — MARVIN |
| M15 | Only if M14 fails: a site-supported submission service (scheduler REST API with a user token) | Identified and documented by the site, or submission stays blocked | UNVERIFIED — MARVIN |
| **H** | **Scheduler permissions and account associations** | | |
| M16 | `sshare -U`, `sacctmgr show assoc`, `scontrol show partitions`, `sinfo` for the owner | Accounts, partitions, limits, GPU types and concurrent-job limits recorded | UNVERIFIED — MARVIN |
| M17 | `--gres=gpu:N` and `--gpus=N` with `--test-only` | The site's GPU request form recorded | UNVERIFIED — MARVIN |
| **I** | **Workspace discovery, expiration and renewal** | | |
| M18 | `ws_list` output; `ws_allocate` and `ws_extend` on a login node and inside a job | Format recorded; where the commands work recorded | UNVERIFIED — MARVIN |
| M19 | A dataset in a workspace listed in `ALLOWED_DATA_ROOTS`: create and reopen a project | Works; paths are identical on login and compute nodes | UNVERIFIED — MARVIN |
| **J** | **Independent lifecycle of application and compute jobs** | | |
| M20 | Stop the app job while a compute job it submitted runs (needs M14) | The compute job continues and writes its outputs | UNVERIFIED — MARVIN |
| **K** | **Recovery after restarting the application** | | |
| M21 | `start` again after M20 | The app finds the compute job again and shows its real state; projects and settings are intact | UNVERIFIED — MARVIN |
| **L** | **Graceful termination before the wall-time limit** | | |
| M22 | An app job with a short `TIME` | SIGTERM arrives before the limit, the app shuts down cleanly, both HOME files are removed | UNVERIFIED — MARVIN |
| M23 | One GPU segmentation run end to end (needs M14, M16) | OPS-20 for this site | UNVERIFIED — MARVIN |

### Status

| Area | Status |
|---|---|
| App as a job with the development servers (`dev_viewer.sh`, `intelsr_long`) | USER-TESTED |
| Forward to `<node>:<port>` from the login node | USER-TESTED for reachability; its encryption is UNVERIFIED — MARVIN (M7) |
| `rw-native.py run`, `rw-app.sbatch`, session sign-in | Implemented, tested locally only: UNVERIFIED — MARVIN (A, B, C, E) |
| Secure transport | UNVERIFIED — MARVIN (D); `BIND=node` is not a verified secure deployment |
| Compute-job submission from the app | UNVERIFIED — MARVIN (G); BLOCKED — MARVIN if M14 fails and M15 finds nothing |
| Compute profiles, storage registry, workspace status in the app | Not implemented (ADR-0055 §7–§10, ADR-0056) |
| BLOCKED — MARVIN items | None recorded |
