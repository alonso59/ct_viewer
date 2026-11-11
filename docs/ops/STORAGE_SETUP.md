# Storage setup

Scope: where the application keeps its state and where project data lives, on a workstation or server and on a cluster.
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

## The operator's folders

The allowed folders are settings in `config/runtime.env` of the state folder (DEPLOYMENT.md §Config). They are the outer bound: the app never goes beyond them.

| Step | How |
|---|---|
| Application state | Create `~/.local/share/radiology-workbench/config/` and `releases/`; set `WORKSPACE_ROOT` to `…/radiology-workbench/workspace` |
| Initial project storage | Pick or create a folder you own, for example `~/rw-data`, and list it in `ALLOWED_DATA_ROOTS` |
| More dataset folders | Add each to `ALLOWED_DATA_ROOTS` (`:`-separated, absolute); restart the app |
| A folder the app must not write | List it in `ALLOWED_DATA_ROOTS` and keep it read-only for your Unix user; a project on it cannot use dataset-local storage (PRJ-19 needs a writable dataset folder) |
| Outputs outside a dataset | A separate writable folder in `ALLOWED_DERIVED_ROOTS` (OPS-11); it must not overlap a data root (OPS-12) |
| A project | In the app: new project → choose a dataset folder under an allowed root; its state goes to `.workbench/` and its outputs to `derived/` in that folder (PRJ-19) |
| The segmentation runner | Its operator file lists the same folders (../domain/SEGMENTATION_RUNTIMES.md §Operator configuration); a run whose output folder it does not list is refused when it starts, naming the folder |

Validation that exists today:

- Startup refuses overlapping data and derived roots, relative roots, and an empty `ALLOWED_DATA_ROOTS` in container mode.
- Every path a request names is resolved and must lie under an allowed root, else `path-outside-root`; a missing file is `source-missing`.
- `rw-native.py run` refuses to start when the state folder lacks working file locks or SQLite write-ahead logging (OPS-22).
- Effective Unix permissions decide the rest: the app runs as you and can read and write only what you can.

Compatibility: projects keep their absolute paths and aliases. Moving a dataset folder is handled by "Reopen from a dataset folder…" (PRJ-19) and relink (PRJ-05); nothing is moved or rewritten automatically.

## In the app: Storage (ADR-0056)

Open it from the home screen (Setup › Storage), the Settings view or the palette. Nothing here needs SLURM, Lustre or root, and nothing changes data on disk.

| Action | What happens |
|---|---|
| Add a location | Pick a folder inside the operator's folders, read-write or read-only, with an optional name. Refused outside them, through a symlink that leaves them, inside the application state, when missing, or when your permissions do not allow the chosen access (API-83) |
| Locations exist | The folder browser starts at them and stays inside them; adding a location still browses every allowed folder |
| Test | Writes and removes one probe file where task outputs may go (`ALLOWED_DERIVED_ROOTS`); elsewhere it checks your permissions only, so a source is never written |
| Use for new projects | The new-project dialog starts browsing there; changing it moves nothing |
| Read only | No project is created or opened there and no run writes its outputs there; a read-write location inside it is the closer one and wins |
| Remove | Forgets the location; its files and projects stay |
| Unavailable | The location and its projects are shown unavailable; other locations and projects keep working |
| Cluster workspaces | Where the site has `ws_list`, the runner reads it: expiry, remaining time, extensions left, a warning from 14 days before expiry, and copyable `ws_extend` and `ws_allocate` lines. You run them; the app never does |

The registry is `storage.json` in `WORKSPACE_ROOT`. Existing projects keep their paths and are not migrated.

### Project-state backup

Project settings › Data › Backups copies one dataset-local project's state (curation, labels, settings; never images, masks, outputs or caches) into `WORKSPACE_ROOT/backups/` as a project bundle, only when you ask (API-84).
It shows the estimated size and the space used, and refuses above `BACKUP_MAX_MB` (1 GiB) per backup or `BACKUP_TOTAL_MB` (2 GiB) for all of them; free space is shown but does not prove quota.
A failed backup leaves the earlier ones untouched. To restore, download a backup and use Import bundle on the home screen.

## On a cluster

| Topic | Rule |
|---|---|
| HOME | Application state, releases and conda environments only. It is small: never set a data, derived or managed derived root there |
| Managed workspaces | Datasets and outputs. Allocate and renew them yourself with the site's commands (HPC_INSTALL.md §Workspaces); list the workspace folder in `ALLOWED_DATA_ROOTS` |
| Group-shared workspace | List its folder the same way; your effective permissions decide what works. Dataset-local projects need the dataset folder writable by you |
| Expiry | A workspace is deleted some time after it expires, with the project state inside it. Storage shows the expiry the runner last read and warns before it; a run whose output workspace ends before its wall time is refused. Keep the site's own reminder too |
| Copies | Back up a project's state to HOME before a workspace can expire (§Project-state backup) |
| Job-local disk | For temporary files only. It is private to one job and removed when the job ends: never the only copy of a result |
| Lustre | Follow the site's guide for striping and many small files. Set striping on a folder before writing into it; moving files does not change it. The app sets none |

Site values (filesystems, limits, commands) are in HPC_ACCEPTANCE.md, never in the application.
