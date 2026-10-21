# ADR-0030 Dataset-local projects with a lightweight global workspace
Status: Accepted · Date: 2026-10-21
Supersedes: ADR-0002 project-location clause and ADR-0014 overlap prohibition only for managed dataset-local storage; extends ADR-0029.

**Context.** The owner approved a VS Code-style folder workflow: work on multiple
datasets anywhere under HOME, keep project state and results alongside each dataset,
and reopen portable projects from the GUI. Existing projects must keep working.

**Decision.** PRJ-19 owns storage and folder-opening behavior; API-67 owns the open
contract. New GUI projects require a dataset folder. The global workspace registers
its location; project state lives in `DatasetID/.workbench/projects/{project_id}/`,
archived state in `.workbench/.archive/`, and the project DERIVED alias defaults to
`DatasetID/derived/`. Tasks retain their per-project/run isolation there. Managed
folders cannot be symlinked or registered as source inputs and discovery skips
`.workbench/`, `derived/` and `recycle_bin/`. Source images/masks/metadata keep R1;
only CUR-16 recycles them. Dataset folder creation and `.gitignore` entries for the
three managed folders are authorized project-management writes. Legacy global
projects remain in place. A per-project filesystem lock prevents a second server
from writing the same local project through another global workspace.

**Consequences.** Dataset roots must be writable. The GUI can open projects from
a moved dataset and rebase dataset-relative path roots; legacy absolute metadata
still requires relinking/reimporting. Bundles remain independent copies and do
not claim a dataset-local storage location. OPS-15 allows an explicitly configured
`MANAGED_DERIVED_ROOT` equal to the global workspace’s sibling `derived/`, so a
HOME-wide browsing root can coexist with a persistent global conversion fallback.
Other overlapping source/derived roots remain forbidden.

**Rejected alternatives.** Global-only project state (not portable with the dataset);
unrestricted nested task output folders (can overwrite source files).
