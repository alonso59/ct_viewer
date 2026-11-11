# HPC installation and daily use

Scope: installing the native release on a SLURM cluster, running the app as a scheduler job, and connecting to it privately.
Read when: setting up or operating the app on a cluster.
Depends: DEPLOYMENT.md (OPS-22, OPS-23, OPS-24, §Native), STORAGE_SETUP.md, HPC_ACCEPTANCE.md, ../adr/0055-app-as-slurm-job-validated-compute-profiles.md.

Radiology Workbench is a private, single-user research application. It runs inside your own allocation and is reached through a private forward.
It has no public URL, domain, reverse proxy, user registration or external identity provider, and needs none.

Status: implemented and tested locally against a fake scheduler; **not accepted on any cluster** (OPS-20). HPC_ACCEPTANCE.md lists what is unverified per site.
Submitting compute jobs (GPU segmentation) from the running app is not part of this guide yet (§Not available yet).

Every site value below is a placeholder in `<…>`: account, partition, limits, module names and paths differ per site and are never built into the application.

## Prerequisites

| Need | Note |
|---|---|
| Access | The site's network or VPN and an SSH key registered with the site |
| VS Code with Remote-SSH | The connection method (R7) |
| A SLURM account | And a CPU partition whose wall time suits a session |
| Conda | The site's Miniforge module with conda-forge only; never Anaconda default channels where the site forbids them |
| A C compiler | For PyRadiomics, on the node where `prepare` runs |
| A managed workspace | For datasets and outputs (§Workspaces) |

Nothing runs on a login node except the commands that talk to the scheduler. No sudo and no system installs (R4).

## Install

Run steps 2 and 3 inside an interactive allocation, not on a login node.

| # | Step | Command or file |
|---|---|---|
| 1 | Get the source into HOME | `git clone <repository> ~/radiology-workbench` |
| 2 | Load conda and create the Node build environment | `module load <Miniforge module>`; `conda create -n rwnode -c conda-forge nodejs=22` |
| 3 | Build a release and its Python environment | `mkdir -p ~/.local/share/radiology-workbench/{config,releases}`; `python3 scripts/rw-native.py prepare` (it prints the release tag) |
| 4 | Application settings | `config/runtime.env` (below) |
| 5 | Job settings | `config/app-job.env` (below) |

`prepare` downloads packages: it needs the compute node to reach conda-forge, PyPI and npm, which is a site fact (HPC_ACCEPTANCE.md).
Releases and conda environments stay in HOME: they must not expire with a workspace.
Do not use `rw-native.py deploy` on a cluster: it installs a systemd user service, which login nodes forbid.

`~/.local/share/radiology-workbench/config/runtime.env` (all keys: DEPLOYMENT.md §Config):

```
WORKSPACE_ROOT=/home/<user>/.local/share/radiology-workbench/workspace
ALLOWED_DATA_ROOTS=<workspace folder>
PORT=8000
JOB_WORKERS=2
```

`~/.local/share/radiology-workbench/config/app-job.env`:

| Key | Default | Meaning |
|---|---|---|
| `TIME` | *(required)* | Wall time of the app job, in the scheduler's format; at most the partition's limit |
| `CPUS` | `4` | CPUs; keep `JOB_WORKERS` plus `DICOM_CPU_THREADS` within it |
| `MEMORY` | `16G` | Memory, as `<n>M` or `<n>G` |
| `ACCOUNT`, `PARTITION`, `QOS` | *(unset)* | Where the site requires them |
| `TAG` | the last deployed release | The release to run; set it on a cluster, where nothing is "deployed" |
| `BIND` | `loopback` | `loopback` or `node` (§Connect) |
| `DEPLOYMENT`, `RUNNER_PYTHON` | *(unset)* | Start the task runner with this operator file; see §Not available yet |

Values are checked before submission; a value with spaces or scheduler flags is refused.

## Workspaces

Datasets and outputs live in a managed workspace, never in HOME (STORAGE_SETUP.md §On a cluster).
Allocation, renewal and release are yours to run; the app never runs them.

| Task | Typical command (confirm with the site's documentation) |
|---|---|
| List yours, with expiry | `ws_list` |
| Allocate | `ws_allocate -F <filesystem> <name> <days>` — always give the duration |
| Extend | `ws_extend -F <filesystem> <name> <days>` — the same filesystem as the allocation |
| Use in the app | Put the workspace's parent folder (or the folder itself) into `ALLOWED_DATA_ROOTS` and restart the app job; then add it under Setup › Storage, which lists the workspaces `ws_list` reports |

A workspace has a maximum lifetime and a limited number of extensions, and its data is deleted after expiry.
A run whose output workspace expires before the profile's wall time ends is refused when it is submitted.
The site's limits and filesystems are recorded in HPC_ACCEPTANCE.md.

## Daily use

All commands run on a login node and only talk to the scheduler.

| Command | Does |
|---|---|
| `scripts/rw-app.sbatch start` | Submits the app job, waits for a node and for the app, prints how to connect. Refuses if a job is already queued or running |
| `scripts/rw-app.sbatch status` | Job state, node, port, bind mode, end time |
| `scripts/rw-app.sbatch credential` | Prints the session code of the running job |
| `scripts/rw-app.sbatch log [-f]` | The job log (`logs/rw-app-<job>.log` in the state folder) |
| `scripts/rw-app.sbatch stop` | Cancels the job |

Connection metadata is `~/.local/state/radiology-workbench/app-job.json`: internal node name, port, job id and times, readable only by you.
It is not a published endpoint, and holds no secret. The session code is in `app-job.credential` beside it, also readable only by you.
Both files exist only while the job runs; `status` removes them if the scheduler no longer lists the job.

## Connect

A port on a compute node can be reached by other users of that node, so an app job always asks for the session code once per browser.
The code protects access; it does not encrypt anything.

| | Preferred: `BIND=loopback` (default) | Compatibility: `BIND=node` |
|---|---|---|
| The app listens on | `127.0.0.1` of the compute node | The node's cluster-network interface |
| Connect | Open the job's node in VS Code Remote-SSH (an SSH session to the allocated node, through the login node), then forward the port in the Ports panel | VS Code connected to the login node: Ports panel → "Forward a Port" → `<node>:<port>` |
| Path | Inside SSH up to the node | Inside SSH up to the login node; plain HTTP between the login node and the compute node |
| Evidence | Not yet tried on any site | The flow of `dev_viewer.sh`, tested by the owner on the reference site |
| Standing | Supported only after the site's acceptance confirms it works and is permitted | Not a verified secure deployment: the session code and every authenticated request cross that segment unencrypted |

Then open the forwarded `http://localhost:<port>` in your browser and enter the session code.
Choose `BIND=node` explicitly, and only knowing what it exposes; no TLS is provided.

## Stop, expiry and recovery

| Event | What happens | What you do |
|---|---|---|
| `stop` | The app shuts down; the connection file and the session code are removed | — |
| Wall time reached | The scheduler signals the job before the limit and the app shuts down the same way | `start` again |
| Node failure or kill | The files may remain; they match no running job | `status` or `start` removes them |
| After any of these | Projects, registry and settings are in HOME and the workspace; nothing was on the node | `start`, `credential`, connect again; the node, the port and the code are new |
| Work running inside the app | In-app tasks (conversion, analyzers, radiomics) end with the job and resume or restart per their own rules | Reopen the task; for long conversions prefer a separate job (DEPLOYMENT.md §HPC, OPS-24) |

## Not available yet

| Item | State |
|---|---|
| Compute jobs submitted by the app (GPU segmentation) | The v1 SLURM adapter exists (../domain/SEGMENTATION_RUNTIMES.md §SLURM backend) but is untested from inside an app job; whether a site allows `sbatch` from a compute node is unverified, and blocked where it does not (ADR-0055 §9) |
| Compute profiles and Check queue | Implemented (Setup › Compute, the task form, ../domain/SEGMENTATION_RUNTIMES.md §SLURM backend); tested against fake scheduler tools only |
| Storage locations, workspace expiry, project-state backup | Implemented (STORAGE_SETUP.md); `ws_list` output read from its usual format, unverified on a site |
| An encrypted path for `BIND=node` | Open (ADR-0055 §5) |

`dev_viewer.sh` at the repository root remains the tested reference for the app-as-job pattern until `rw-app.sbatch` passes the same checks on a real site.
