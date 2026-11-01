# ADR-0040 Batched DICOM source operations
Status: Accepted · Date: 2026-11-01 (owner: partition by top-level patient folder; create each project manually; batch names `<dataset>-bNN`)
Extends: ADR-0035 (durable DICOM source operations). Does not change ADR-0014 output locations or ADR-0020 metadata ownership.

**Context.** A source with hundreds of patient folders (about 2.4 M files, 1.1 TB) cannot be converted in one operation: one inventory outgrows its cap, discovery runs for hours, and curators review the result in groups of about 40 patients. `patient_pattern` and `patient_limit` cannot express "batch k", and the inventory always scans the whole source.

**Decision.**
1. A **batch plan** splits a source into batches of top-level patient folders. Folders are sorted case-insensitively (the converter's own order) and the partition is frozen when the plan is created. Folders that appear later join only a new trailing batch through an explicit action.
2. Each batch is **one ordinary source operation** (ADR-0035) limited to its folders by an explicit folder scope, and produces **one workspace dataset** named `<plan name>-bNN` (zero-padded to the batch count). The scope is part of the operation's request identity and of its inventory, so scopes never mix; `patient_folders` carries the same list into the converter settings.
3. Batches run **sequentially**: the next batch is submitted only after the previous batch's dataset is complete, because admission refuses rather than queues. Every batch stops after its dry run until the user converts it; `auto` converts batches after the first automatically.
4. The plan **pauses** on any failed, partial, limited or interrupted batch. The user repairs it with the existing resume/retry controls of that operation, then continues the plan. The orchestrator never retries by itself.
5. A plan is a durable record in the workspace (`plugins/dicom/batches/{id}/plan.json`). Progress is re-derived from the operation records on every job end and at startup, using one idempotency key per plan and batch, so a restart never submits a batch twice.
6. **Project creation stays manual**; the backend never registers a project for a batch.
7. Patient identity across batches is compared through salted hashes stored in the plan. A patient seen in an earlier batch raises a plan warning and never blocks.
8. Patient folder names and PatientIDs never appear in URLs, logs, exports or API payloads; folder names live only in `plan.json`.

**Consequences.**
- With batching unused, the single-operation flow is unchanged; `folders` is optional and absent from old request identities.
- Each batch walks and reads only its scope, keeps its own inventory below the cap and can be reviewed independently.
- One dataset per batch restarts case numbering; merging batch datasets is out of scope.
- The orchestrator holds no state outside plan and operation records.

**Rejected alternatives.**
- One operation with a moving `patient_limit` window: cannot express a stable "batch k" and rescans the whole source.
- Queueing batch conversions in the admission layer: changes ADR-0035 refusal semantics for all callers.
- Auto-creating a project per batch: the owner reviews each batch before it becomes a project.
- Storing PatientIDs for the cross-batch check: only salted hashes are kept, so the plan holds no identifiers.
