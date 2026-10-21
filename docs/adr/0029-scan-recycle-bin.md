# ADR-0029 Explicit scan recycling with full audit metadata
Status: Accepted · Date: 2026-10-21
Supersedes: ADR-0014 §2/4/5 and ADR-0021 write-once clause, only for CUR-16; all other source and output writes remain prohibited.

**Context.** The owner requests a button to remove unwanted CT scans, clean active
`metadata.jsonl` and derived rows/files, and preserve full metadata in a separate
recycle audit. On 2026-10-21 the owner explicitly authorized this for imported
`source` datasets as an exception to AGENTS.md R1.

**Decision.** CUR-16 owns the behavior and layout. The native project action is an
explicit, previewed and confirmed file operation. Its scope is a scan with all
associated items. Dataset recycling is the sole source mutation allowed; ordinary
curation, imports and tasks keep the previous read/write boundaries. Existing
import snapshots and append-only events stay historical. The deletion journal
excludes recycled items from future index rebuilds. API-66 owns the HTTP contract.

**Consequences.** Dataset folders must be writable for this action, including
source mounts (see OPS-05); normal viewing still works with read-only mounts.
A transaction manifest and metadata backups precede file moves. Failed operations
roll back, pending operations recover before serving requests, and copies across
mounts are verified before unlinking. Full audit metadata stays local in the
dataset recycle bin; project bundles carry only deletion references. Physical
restoration is a manual operation; a restore UI is outside this change.

**Rejected alternatives.** Tombstones inside `metadata.jsonl` (the owner wants
clean active metadata); permanent deletion (loses recoverability and provenance);
project-only hiding (leaves unwanted dataset files and metadata active).
