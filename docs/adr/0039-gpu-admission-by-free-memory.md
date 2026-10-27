# ADR-0039 GPU admission by available memory
Status: Accepted · Date: 2026-10-27
Supersedes: ADR-0034 §5 admission criterion only; ownership, reservations and all other decisions remain in force.

**Context.** The owner authorizes sharing GPUs that have enough free memory for nnU-Net.
Requiring no compute processes and almost no allocated memory rejects usable devices.
GPU inventory indices also differ from Linux device minors on this deployment.

**Decision.**
1. Compare fresh total minus used GPU memory with the operator's per-GPU budget; activity and outside processes do not independently block admission.
2. Preserve the shared host reservation, UUID selection, exact device-node mapping, process containment and verified cleanup.
3. After the owned attempt boundary is empty, fresh accounting must show no GPU process in that attempt. Unrelated GPU contexts do not prevent release.
4. Display free memory and the admission budget in the frontend. Unknown memory remains unavailable.
5. Keep actual inference errors in task results and show a notification. CUDA failures stop later batches; completed masks remain immutable and resumable.

**Consequences.** Sharing is cooperative; free memory can change after admission and CUDA out of memory remains possible.
The budget is configured for the deployed model, not a guarantee for arbitrary models or image sizes.

**Rejected alternatives.** Evicting other processes, disabling containment, and treating a successful process exit or a full progress counter as proof of valid masks.

Operational configuration: `../domain/SEGMENTATION_RUNTIMES.md`.
