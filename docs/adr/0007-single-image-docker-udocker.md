# ADR-0007 One OCI image for Docker and udocker
Status: Accepted · Date: 2026-09-23

**Context.** Local machines have Docker. Remote servers have no sudo; udocker runs OCI images in user space but cannot build images, has no compose, and does not isolate the network.

**Decision.** A single multi-stage image containing API + SPA + job workers (no DB, no sidecars). The run contract is env vars + two mounts (workspace rw, data). Compose is used for Docker; `scripts/udocker-run.sh` gives the udocker equivalent from the same `.env`. Build on a Docker host, then `docker save` → `udocker load` (or registry pull).

**Consequences.** + Identical artifact everywhere. − No multi-container patterns (queues, DB) without revisiting this ADR. − udocker-specific notes (bind address, ro mounts, exec mode) must be kept in DEPLOYMENT.md.

**Rejected.** Separate images for API, workers and DB (incompatible with the simplicity needed for udocker). Native install without containers on servers (dependency drift).

**Amended by ADR-0014 and ADR-0016.** A third, writable mount holds the derived root; heavy plugins run outside the image through a host runner and a file queue, and the image stays the one core artifact.
