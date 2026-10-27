# ADR-0038 Individual segmentation label removal and management panel
Status: Accepted (owner 2026-10-27) · Date: 2026-10-27
Supersedes: ADR-0037 §5 management location; extends ADR-0015 and ADR-0036.

**Context.** Removing a whole segmentation set cannot retire one unwanted structure across
all cases. Visibility checkboxes are temporary display controls; deleting source masks or
rewriting combined masks in place violates source immutability.

**Decision.**
1. A dedicated project segmentation editor owns Import, Reindex, set lifecycle controls and
   searchable per-label Remove/Restore actions. Layers links to it and keeps display controls.
   The names/colors catalog remains project metadata and is reachable from the editor.
2. `SegmentationSet.removed_labels` stores original set values, independently of the project
   label mapping. One removal affects every case in that set, preserves other labels/sets,
   and requires a confirmation identifying its scope. Atomic idempotent actions avoid lost
   updates between concurrent per-label removals. View-only links cannot mutate it.
3. Sources and immutable manifests stay unchanged. Workers materialize disposable filtered
   NIfTI caches for downloads/task inputs; binary members are excluded before composition
   so overlapping retained structures remain visible. Meshes and radiomics exclude removed
   values. Cache identities and run input snapshots include the exclusions; changed exclusions
   refuse resume. Cache preparation runs inside the tracked job before executor publication,
   and cancellation drains the active cache worker before releasing job exclusivity.
4. Restoration changes metadata immediately. Reindex retains exclusions; explicitly replacing
   a removed set with a new import starts a new label selection with its new artifact.
5. Inspector sections remain mounted while collapsed, preserving unfinished forms. Visibility
   defaults on; section state and explicit user visibility preferences persist per project.

**Consequences.** No destructive mask editing or pixel-copy job is required to remove/restore
a label. The first subsequent consumer may build a filtered cache in a worker. Removal does
not erase historical task/radiomics results or rewrite their provenance.

**Rejected alternatives.** Deleting source members, changing only the global catalog, or
treating a visibility checkbox as a persisted removal would conflate distinct operations.
