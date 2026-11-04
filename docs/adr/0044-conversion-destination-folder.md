# ADR-0044 Projectless conversions write to a destination folder the user chooses
Status: Accepted · Date: 2026-11-04 (owner decision, same date)
Supersedes: ADR-0002 and ADR-0014 only to let a projectless conversion create a new dataset folder inside an allowed source root; the `{derived}/_datasets/` location of TSK-13 becomes the fallback. Extends: ADR-0030.

**Context.** A projectless conversion wrote to `{first derived root}/_datasets/{name}/`. With the persistent installation that root is `~/.local/share/radiology-workbench/derived/`, so the dataset sat below a folder named `derived` (PRJ-19 refuses it as a dataset folder, so "Create project" failed after every conversion) and inside a dot folder (the folder browser never enters one, so the user could not find it again).

**Decision.** A projectless conversion (TSK-13, DCM-14) and every batch of a batch plan (DCM-22) take a destination: an existing, writable folder inside the allowed roots, reached without symlinks, not inside a managed folder (`.workbench`, `derived`, `recycle_bin`, `.git`), the source being converted, the workspace, a derived root or the host allocation pool. The conversion creates one new folder `{destination}/{name}/` there (a `-1`, `-2` … suffix when taken) and writes only inside it; existing files are never opened for writing. That folder is an ordinary dataset folder: it opens in Open mode and can become a PRJ-19 project in place. Without a destination the API keeps the old `{derived}/_datasets/` location. The overlay suggests the last destination used in the browser, else the folder that holds the source.

**Consequences.** R1 gains one more authorized write: creating a new dataset folder in a destination the user picked. Source files are still never modified. Datasets already in `_datasets/` stay readable as before.

**Rejected alternatives.** One fixed `DATASETS_ROOT` setting (one more server variable, still a single place for every user's data). Keeping `_datasets/` and creating a global project that imports it (contradicts PRJ-19, data stays hidden).
