# ADR-0047 DICOM conversion runs outside the host allocation pool (interim)
Status: Accepted (interim; to be redesigned) · Date: 2026-11-05 (owner decision)
Supersedes: ADR-0035 §coordinated host admission, only for the pool lease. Extends: ADR-0043.

**Context.** The host allocation pool holds one lease at a time. A long nnU-Net job reserves 12 CPUs, 32 GB and a GPU, so every DICOM conversion sat in `waiting_for_resources` until it finished, although the host has 503 GB of RAM and conversion needs no GPU.

**Decision.** DICOM conversion does not acquire or release a pool lease. It is bounded only by its own budgets (`DICOM_CPU_THREADS`, `DICOM_MEMORY_MB`, inventory limits) and by the one-at-a-time DICOM workspace lease. Segmentation admission is unchanged. Consequence: CPU use can exceed the nominal 12-CPU budget while both run (up to `DICOM_CPU_THREADS` extra threads), and the pool no longer protects a segmentation from a conversion's memory.

**Precedent, to improve soon.** This is a stopgap, not the target design. The next design iteration should replace the single-lease pool with per-owner reservations against one shared CPU/memory budget, so each owner is admitted only when its share fits, and DICOM and segmentation coexist by accounting rather than by exemption. That needs its own ADR and a change to the runner pool (`plugins/runner/gpu.py`). Until then, watch host memory when large conversions run beside segmentation.

**Rejected alternatives.** Raising a DICOM quota (the wait is exclusivity, not quantity). Cancelling segmentation to free the pool (loses hours of GPU work).
