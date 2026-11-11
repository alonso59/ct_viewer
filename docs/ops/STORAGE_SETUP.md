# Storage setup

Scope: where the application keeps its state and where project data lives, on a workstation or server and on a cluster; what works today and what ADR-0056 plans.
Read when: installing the app, adding a dataset folder, or working on Settings → Storage.
Depends: DEPLOYMENT.md (§Config, OPS-04, OPS-11, OPS-12, OPS-15), ../domain/PROJECT_FORMAT.md (PRJ-19), ../adr/0056-storage-locations-local-and-managed-workspaces.md.

No step here needs root, sudo or a change of file ownership or modes. Standalone needs no SLURM, Lustre or `ws_*` tool.

## Three places

| Place | Holds | Where |
|---|---|---|
| Application state | Project registry (`WORKSPACE_ROOT`), configuration, releases, logs | HOME: `~/.local/share/radiology-workbench/`; locks and the per-job files in `~/.local/state/radiology-workbench/` |
| Project storage | Datasets, each project's state (`.workbench/`) and outputs (`derived/`) | Folders the operator allows; on a cluster, managed workspaces |
| Temporary storage | Scratch of a task, conversion inventories, disposable caches | Local disk; job-local disk under a scheduler |

Application state is small and must persist; project data is large and stays where the user put it.
The registry records where each project is; it never holds images, masks or outputs.

## Today: configured by the operator

The allowed folders are settings in `config/runtime.env` of the state folder (DEPLOYMENT.md §Config). There is no Settings → Storage screen yet.

| Step | How |
|---|---|
| Application state | Create `~/.local/share/radiology-workbench/config/` and `releases/`; set `WORKSPACE_ROOT` to `…/radiology-workbench/workspace` |
| Initial project storage | Pick or create a folder you own, for example `~/rw-data`, and list it in `ALLOWED_DATA_ROOTS` |
| More dataset folders | Add each to `ALLOWED_DATA_ROOTS` (`:`-separated, absolute); restart the app |
| A folder the app must not write | List it in `ALLOWED_DATA_ROOTS` and keep it read-only for your Unix user; a project on it cannot use dataset-local storage (PRJ-19 needs a writable dataset folder) |
| Outputs outside a dataset | A separate writable folder in `ALLOWED_DERIVED_ROOTS` (OPS-11); it must not overlap a data root (OPS-12) |
| A project | In the app: new project → choose a dataset folder under an allowed root; its state goes to `.workbench/` and its outputs to `derived/` in that folder (PRJ-19) |
| The segmentation runner | Its operator file lists the same folders (../domain/SEGMENTATION_RUNTIMES.md §Operator configuration); today that list is edited by hand |

Validation that exists today:

- Startup refuses overlapping data and derived roots, relative roots, and an empty `ALLOWED_DATA_ROOTS` in container mode.
- Every path a request names is resolved and must lie under an allowed root, else `path-outside-root`; a missing file is `source-missing`.
- `rw-native.py run` refuses to start when the state folder lacks working file locks or SQLite write-ahead logging (OPS-22).
- Effective Unix permissions decide the rest: the app runs as you and can read and write only what you can.

Compatibility: projects keep their absolute paths and aliases. Moving a dataset folder is handled by "Reopen from a dataset folder…" (PRJ-19) and relink (PRJ-05); nothing is moved or rewritten automatically.

## Planned: Settings → Storage (ADR-0056, not implemented)

| Planned | Meaning |
|---|---|
| Storage registry | Named locations (`local_directory` or `managed_hpc_workspace`, read-only or read-write) in one file in the application state, read by the app and the runner |
| Registration in the app | Add a location at or below a root the operator allows; the app cannot widen that policy |
| Test | Canonical path, symlinks, permissions and one probe file for a writable location |
| Default location | For new projects only; changing it moves nothing |
| Unavailable storage | The project stays in the registry, marked unavailable; other projects are unaffected |
| Workspace status | Expiry, remaining time and extensions of a managed workspace, with copyable site commands; the app never runs them |
| Project-state backup | An explicit action; 1 GiB per backup and 2 GiB in total by default; never automatic, never images or outputs |

Until these exist, the table under §Today is the whole procedure.

## On a cluster

| Topic | Rule |
|---|---|
| HOME | Application state, releases and conda environments only. It is small: never set a data, derived or managed derived root there |
| Managed workspaces | Datasets and outputs. Allocate and renew them yourself with the site's commands (HPC_INSTALL.md §Workspaces); list the workspace folder in `ALLOWED_DATA_ROOTS` |
| Group-shared workspace | List its folder the same way; your effective permissions decide what works. Dataset-local projects need the dataset folder writable by you |
| Expiry | A workspace is deleted some time after it expires, with the project state inside it. The app does not track expiry yet: keep your own reminder (the site's reminder file, where it has one) |
| Copies | Keep anything irreplaceable (curation, labels) also outside the workspace; until the backup action exists, copy the dataset's `.workbench/projects/` folder yourself while the app is stopped |
| Job-local disk | For temporary files only. It is private to one job and removed when the job ends: never the only copy of a result |
| Lustre | Follow the site's guide for striping and many small files. Set striping on a folder before writing into it; moving files does not change it. The app sets none |

Site values (filesystems, limits, commands) are in HPC_ACCEPTANCE.md, never in the application.
