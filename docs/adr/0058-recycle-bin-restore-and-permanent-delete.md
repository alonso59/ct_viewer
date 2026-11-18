# ADR-0058 Recycle bin panel: restore and permanent delete
Status: Accepted · Date: 2026-11-18
Supersedes: ADR-0029 "a restore UI is outside this change" and its rejection of permanent deletion. Everything else in ADR-0029 stands.

**Context.** Scans recycled with CUR-16 can only be recovered by hand, and a recycle bin
only grows. On 2026-11-18 the owner asked for a project panel that lists the recycled
scans and restores or permanently deletes each one, with a confirmation dialog. The owner
decided two points: a permanent delete keeps nothing (no manifest, audit or metadata
backup), and a restore whose original path is taken is refused, not renamed.

**Decision.** CUR-17 owns the behavior and API-82 the HTTP contract.
- A restore is a previewed, confirmed and reviewer-stamped transaction like the recycle.
  It moves the files back and merges the removed rows into the current metadata. It does
  not write back the old backups, because that would undo every change made since the
  recycle. It re-adds the items to the index of every affected project and drops the
  journal entry. It is refused when a file's original path exists, when an item ID is
  already indexed, when an affected project is archived or gone, or when a job is running.
- A permanent delete removes the whole `recycle_bin/{recycle_id}/` folder. In each active
  project, the journal entry keeps only `recycle_id`, `item_ids` and `purged: true`, so an
  index rebuild from the import snapshots does not bring back items whose files are gone.
  It records no reviewer, date, file list or metadata.

**Consequences.** Restoring writes to `source` roots again, under the same R1 exception as
CUR-16. A restore over a source that was re-imported or edited fails until the conflicting
file is moved away. After a permanent delete nothing can be recovered; the confirmation
dialog asks the user to type the case ID.

**Rejected alternatives.** Writing back the metadata backups (it loses later edits);
restoring under a new file name (the owner chose to refuse); dropping the journal entry on
a permanent delete (a rebuild would bring back items whose files are gone).
