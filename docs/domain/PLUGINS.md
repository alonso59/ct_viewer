# Plugins

Scope: the first-party plugin model, manifest, contribution points, Plugin Library, catalog.
Read when: adding or changing any plugin, or the Library view.
Depends: ADR-0016, ADR-0018..0022, TASKS.md (run protocol), UI_SHELL.md (registry UI-02).

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| PLG-01 | v3 ships first-party plugins only, in `plugins/<id>/` (backend + `plugin.json`) and `frontend/src/plugins/<id>/` (lazy UI). No third-party loading or marketplace. | M |
| PLG-02 | `plugin.json` declares id, version, title, description, icon, `contributes` (§Contribution points), `requires` (core version, other plugins, capabilities) and `scope` (`workspace` \| `project`). | M |
| PLG-03 | Plugins register through the shell registry (UI-02) when activated; heavy UI lives in lazy chunks so NFR-07 holds. | M |
| PLG-04 | Every shipped plugin is installed per workspace and enabled by default. | M |
| PLG-05 | Plugin Library view (activity bar): each plugin with version, what it adds, status (`ready`, `needs runner`, `needs derived root`, `needs segmentation`, `pending`) and an **Open** action to its main surface. | M |
| PLG-06 | Status is computed from `requires` (e.g. a runner heartbeat, `ALLOWED_DERIVED_ROOTS`, a segmentation set) and explains how to satisfy it (UI-18). | M |
| PLG-07 | Plugin state is namespaced: `{project}/plugins/{id}/` and `{WORKSPACE_ROOT}/plugins/{id}/`; human decisions go to the event store namespace `{id}` (ADR-0022). | M |
| PLG-08 | New plugin HTTP routes mount under `/api/v1/plugins/{id}/`; existing first-party routes (radiomics, curation, analytics) keep their paths. | M |
| PLG-09 | A plugin that is `pending` is listed in the Library with its description and requirements, but cannot be opened. | S |
| PLG-10 | Per-project enable/disable, updates and plugin management. | C (later) |

## Contribution points

| Point | What it adds | Example |
|---|---|---|
| `tasks` | Jobs with the TSK protocol (builtin or external runtime) | `dicom.convert`, `radiomics.pyradiomics` |
| `views` | Activity-bar view | Curation, Radiomics, Labeling |
| `editors` | Editor tab type | Dashboard, queue editor, labeling table |
| `overlays` | Modal work window launched by a button | DICOM converter |
| `panels` | Bottom-panel tab | Measurements |
| `commands` | Palette commands + menu entries | "Convert DICOM…" |
| `columns` | Metadata layers (ADR-0020) | phase, organ match, labeling columns |
| `packs` | Study pack: label map, phases, organ profile, radiomics profile (ADR-0019) | `ccrcc` |

## Catalog (v3)

| Plugin | Contributes | Scope | Requires | Status |
|---|---|---|---|---|
| DICOM converter | overlay, task `dicom.convert` | workspace | derived root | P7c |
| Phase analyzer | task, `columns: phase` | project (chained by the converter) | metadata rows | P7c |
| Organ & readiness analyzers | tasks, columns | project | metadata rows | P7c |
| Curation & QC | view, inspector, queue editor, commands | project | event store | P7c (repackaged) |
| Labeling table | view, editor, columns | project | event store | P7c (new) |
| Radiomics | view, editor, task | project | segmentation set | P7c (repackaged) |
| Dashboard & analysis | editor, panels | project | a features run | P7c (repackaged) |
| Study pack ccRCC | pack | project | — | P7c |
| `segment.threshold` | task (test only, hidden from the Library) | project | runner | done (CI) |
| nnU-Net segmentation | task (external) | project | runner, GPU | **pending** (end) |
| VOI extractor | task: crops VOIs (image + mask, per side) from a segmented mask | project | **a segmentation set** with the target labels | **pending** (end; reference code from the owner; settles the legacy `.npy` axis order, SRC-12) |
