# ADR-0043 Three deployment options: native, container, HPC
Status: Accepted · Date: 2026-11-04 (owner decision, same date)
Supersedes: ADR-0007 only for its rejection of native server installs and for the image being the only way to deploy; the image contract itself stands. Extends: ADR-0034 (the SLURM adapter stays deferred). Does not change ADR-0002, ADR-0004 or ADR-0014.

**Context.** ADR-0007 rejected native installs because of dependency drift. Since then the lock (`backend/requirements-ci.lock`) and frozen releases answer that risk, and udocker's cost was measured on `john` (same code and data, `PROOT_NO_SECCOMP=1` as in production, medians):

| Converter run | Native | udocker |
|---|---|---|
| 1,600 512² slices, 1 worker | 8.5 s | 37.3 s |
| 1,600 512² slices, 4 workers | 5.1 s | 28.0 s |
| 10,000 small files, 1 worker | 22.8 s | 144.7 s |
| 10,000 small files, 8 workers | 12.2 s | 106.2 s |
| Verified reuse, 1,600 / 10,000 files | 2.3 / 7.3 s | 6.0 / 19.5 s |

Compared 1-worker images were byte-identical. Server side of the API and viewer (private instances, alternating rounds, host load 6–10 of 64 CPUs; browser rendering is client-side and was not measured), native vs udocker: health 0.6 vs 2.8 ms; items page 5.2 vs 9.1 ms; item record 2.5 vs 11 ms; small image 1.5 vs 20 ms; folder of 2,000 entries 118 vs 1,973 ms; opening and reading a 512×512×300 image 216 vs 1,824 ms; boot 2.0 vs 6.2 s.

udocker gives no network or OS isolation either (ADR-0007, OPS-19), so native loses no security boundary. Clusters add constraints neither option covered: login-node policy, SIGTERM at the time limit, and network file systems where SQLite's WAL does not work.

**Decision.**
1. **Three options, same source and same lock.** Each deployment picks one (OPS-22..24); the code has no option-specific behavior beyond configuration.

| Option | Use when | App | Heavy work |
|---|---|---|---|
| Native | Single server or workstation with conda, no sudo, performance matters. Default on `john` | Frozen release in a conda environment, user service | Same host, through the existing runner |
| Docker/udocker | The server has Docker, or a portable artifact matters more than speed | The one OCI image | Same host, through the existing runner |
| HPC | SLURM cluster | Apptainer from the image; a native conda environment if the site has none. On an approved service or submission node | Scheduler allocations only |

2. **Native release.** `scripts/rw-native.py` builds from a commit a release folder (backend, plugins, scripts, built web app) and an environment pinned by the lock, smoke-tests it before any restart, refuses to switch while work is active and restores the previous release on failure. Conda environments are per need: one if everything coexists, several if not (`torch` stays separate; OPS-14 holds).
3. **Node is a build tool.** On a server without `npm`, Node comes from a conda environment (or a container). It never runs in production. R4 is reworded for this; still no sudo, apt, brew or system installs.
4. **The image stays.** R3 holds: CI builds and tests one image for Docker and udocker, and that image is the source for Apptainer. No compose-only or native-only features.
5. **HPC placement.** The app and a light runner never compute on a login node. `rw-dicom` runs inside `sbatch`; the output lives on shared storage and the inventory on node-local disk (`--state-dir`), because it is a rebuildable cache and pins and commits stay in the output. GPU segmentation waits for the adapter and acceptance of OPS-20; nothing here certifies a cluster.

**Consequences.**
+ On `john`, conversion is 2.6–8.7× and server responses 1.7–16.7× faster, with the same outputs. − Native needs its own smoke run: CI's image gates do not exercise a host's environment.
− A native environment is pinned, not byte-identical across hosts (PyRadiomics compiles locally, needing a C compiler). HPC remains unaccepted until tried on a real cluster (OPS-20, OPS-23).

**Rejected.**
- Native only, dropping the image: loses the portable artifact and Docker users. Node in production or system-wide: no runtime need, and R4.
- One environment required for the app and `torch`: conflicting pins would couple upgrades; allowed only if they happen to coexist.
- udocker on compute nodes as the HPC default: its emulation overhead hits exactly the heavy work (table above).

**Superseded in part by ADR-0051.** The Docker/udocker deployment option, decision 4 and Apptainer on HPC are gone; native and HPC-on-native stand. Docker remains for local development.
