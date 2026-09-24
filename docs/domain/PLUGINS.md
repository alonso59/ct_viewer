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

## Manifest (`plugin.json`)

```jsonc
{ "plugin": 1, "id": "dicom",            // = folder name, [a-z][a-z0-9_-]*
  "version": "1.0.0", "title": "DICOM converter", "description": "…", "icon": "file-binary",   // codicon
  "scope": "workspace",                   // workspace | project
  "contributes": { "tasks": ["dicom.convert"], "commands": ["tasks.convertDicom"] },   // ids per point
  "requires": { "core": ">=3.0", "plugins": [], "capabilities": ["derived_root"] },
  "pending": false,                       // PLG-09
  "hidden": false }                       // CI plugins: tasks load, the Library does not list it
```

- Loading: `app/plugins/registry.py` reads `{BUILTIN_PLUGINS_ROOT}/*/plugin.json`; unknown keys, an id that differs from its folder, an unknown capability or a missing required plugin make it invalid (listed in API-49 `invalid`). Backend-less plugins (curation, radiomics, dashboard) keep their code in `app/` and only declare themselves here.
- Capabilities → status (first unmet wins, PLG-06): `derived_root` → `needs_derived_root` (no `ALLOWED_DERIVED_ROOTS`); `runner` → `needs_runner` (an external task with no fresh runner); `segmentation` → `needs_segmentation` (API-49 `?project=` given and no item has a mask); `event_store`, `features_run` are informative. API status values are snake_case (`needs_runner`, …).
- Task ownership (TSK-01): every task id is contributed by one plugin (`TaskInfo.plugin`); a `PLUGINS_ROOT` manifest whose id no `plugin.json` contributes is invalid.
- Frontend: `frontend/src/plugins/host.ts` (`FrontendPlugin {id, activate(ctx), open?}`); `plugins/index.ts` lists the shipped ones and bootstrap activates them all (PLG-04). `open` is the Library's Open; a plugin without one (pending) cannot be opened.

## Catalog (v3)

| Plugin | Contributes | Scope | Requires | Status |
|---|---|---|---|---|
| DICOM converter (`dicom`) | overlay, task `dicom.convert` | workspace | derived root | P7c Wave 1 (overlay Wave 3) |
| Metadata analyzers (`analyzers`): phase, organ target, readiness | tasks, `columns` | project (phase chained by the converter) | metadata rows | P7c Wave 1 |
| Curation & QC (`curation`) | view, inspector, queue editor, commands | project | event store | P7c Wave 1 (repackaged) |
| Labeling table | view, editor, columns | project | event store | P7c (new) |
| Radiomics (`radiomics`) | view, editor, task | project | segmentation set | P7c Wave 1 (repackaged) |
| Dashboard & analysis (`dashboard`) | editor, panels | project | a features run | P7c Wave 1 (repackaged) |
| Study pack ccRCC | pack | project | — | P7c |
| `segment.threshold` (`threshold`, `hidden`) | task (test only, hidden from the Library) | project | runner | done (CI) |
| nnU-Net segmentation (`nnunet`, `pending`) | task (external) | project | runner, GPU | **pending** (end) |
| VOI extractor (`voi`, `pending`) | task: crops VOIs (image + mask, per side) from a segmented mask | project | **a segmentation set** with the target labels | **pending** (end; reference code from the owner; settles the legacy `.npy` axis order, SRC-12) |
