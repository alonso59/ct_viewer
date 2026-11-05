# Cohort Dashboard

Scope: the project-level Cohort tab: one case → scans grid over every variable, grouped by origin; read-only imaging metadata, editable clinical and label columns, scan comparison, column summary; the planned Timeline.
Read when: working on `features/cohort` or its read endpoints, or on clinical data.
Depends: ADR-0045, ADR-0046, domain/VARIABLES.md (VAR-10, VAR-14), domain/LABELING.md, DATA_MODEL §Item, DICOM_CONVERTER (DCM-04/05), CURATION.md, UI_SHELL.md, ADR-0009.

## Status

Accepted 2026-11-04 (ADR-0045, ADR-0046); roadmap phase P7k in three parts, all implemented 2026-11-05: **K1** read-only grid, **K2** clinical and label editing (§K2), **K3** Timeline (§K3, ADR-0049).

## Purpose

Read the imaging metadata of every case and scan in order, next to the clinical data and every other non-image variable, without getting lost in numbers: narrow the cohort by value, compare a case's scans, see how a field is distributed, enter clinical values, and jump to the viewer or the radiomics dashboard.

## Navigator groups (origin, VAR-14)

| Group | Holds | In Cohort |
|---|---|---|
| Metadata | `metadata.jsonl` fields and promoted tags, by category (VARIABLES §Categories) | Read-only |
| Automatic results | Analyzer and task annotation layers (`phase.analyzer`, readiness, target match, …) | Read-only |
| Review | Effective phase (`phase.effective`), curation status (CUR-08) | Read-only; changed in Curation and the viewer |
| Clinical & labels | Label table columns (`lbl.*`) at patient, scan or item level; external tables until retired | Editable from K2 (ADR-0046) |
| Derived | Derived variables (VAR-06) | Read-only; defined in Variables |

## Layout

```text
┌ Navigator ─────────┬ Case ▸ scans grid ──────────────────────────────┬ Column summary ──┐
│ Search fields…     │ Filters: [manufacturer = SIEMENS ×]              │ kvp              │
│ ▾ Metadata         │ case_00012  M  64   3 scans   ≠ kvp            │ 100 ▇▇           │
│    Patient     4   │   01  arterial  120  B30f  1.0                  │ 120 ▇▇▇▇▇▇       │
│    Technique  14   │   02  venous    120  B30f  1.0                  │ 140 ▇            │
│    …               │   03  delayed   100  B40f  5.0                  │ missing 3 %      │
│ ▸ Automatic results│ case_00013 …                                    │ [Show as table]  │
│ ▸ Review           │                                                 │                  │
│ ▸ Clinical & labels│                                                 │                  │
│ ▸ Derived          │                                                 │                  │
└────────────────────┴─────────────────────────────────────────────────┴──────────────────┘
```

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| COH-01 | A **Cohort** editor tab per project (`/p/{pid}/cohort`), opened from a Cohort activity-bar view, from the Explorer case menu ("Show in Cohort", which focuses that case) and from the Image view. It is available on view-only links (UI-26) without the actions flagged `writes`. | M |
| COH-02 | Navigator: the origin groups of VAR-14 in fixed order, Metadata split into its categories, each with its variable count (the catalog's `visible` flag only affects other views), and a search over variable names. Metadata variables with no category (a NIfTI import has no DICOM fields to classify) list under Other. The grid always shows the cases with the fixed columns (case, scan, phase, modality); choosing a group or category adds its variables as columns after them; a variable can be pinned so it stays visible. Constant variables are listed as "Same for all: value" instead of a column. | M |
| COH-03 | Case → scans grid: one row per case with its case-level values, expanding to one row per scan with its scan-level values. A scan-level variable in a case row shows the value when all its scans agree, else "n values" with a "differs" icon. Server-side filter, sort (any column) and paging; the grid is virtualized. | M |
| COH-04 | Only Clinical & labels cells are editable (COH-12); every other cell is read-only and nothing writes to `metadata.jsonl`, sidecars, the index or catalog values. A cell's menu offers Copy value, Filter by this value, Open scan in viewer and Add to correction queue (a curation event, CUR-*, flagged `writes`). | M |
| COH-05 | Filters use the `var.{name}` model of VAR-10 (API-20), plus phase and text on case / patient ID, shown as removable chips with Clear filters. Send to Explorer and Open in dashboard (a radiomics run, DB-02) apply the same filter there. Filters, open group, pinned and expanded rows persist per project (UI-13). | M |
| COH-06 | Column summary for the focused column over the filtered rows at the variable's level: bars for categorical values (top 20 + Other), a histogram for continuous and date values, and the missing count. Clicking a bar or bin adds the filter. Show as table gives the same rows (DB-11). | S |
| COH-07 | Compare scans (from a case row): variables as rows and the case's scans as columns (header: scan, phase, modality), grouped as the navigator; "Differences only" hides rows equal across scans. | M |
| COH-08 | DICOM tags of one scan on demand (API-22), grouped by category where a tag maps to one, with a search; same PHI rule as DCM-05 and the partial-sidecar badge of the Image view. | S |
| COH-09 | Export the current grid (visible columns, filtered rows, one row per scan) as CSV. `sensitive` variables are left out unless chosen; absolute paths, UIDs and raw blobs never appear (VAR-09). Charts export as PNG (theme or light background) and SVG. | S |
| COH-10 | Keyboard and screen readers: the grid follows the table row keys of DB-03 (one Tab stop, arrows, Enter opens, Shift+F10 menu), expandable rows report `aria-expanded`, cells report their column name; the "differs" marker has a text label. | M |
| COH-11 | Promote a DICOM tag to a variable from COH-08: the tag is read from every scan's sidecar into a project-level variable of source `raw` (extends the VAR-08 allowlist per project; same PHI and exclusion rules). | C |
| COH-12 | Clinical & labels editing (ADR-0046): cells of label columns are edited in the grid at their table's level with the LBL-03 editors, bulk fill and paste, written as LBL-04 events with history, undo and live sync (LBL-05). A patient-level table edits the case row; scan and item tables edit scan rows. | M |
| COH-13 | Balance check without a radiomics run: a contingency heat map of two categorical variables with χ²/Fisher (the DB Balance check view over variables only), e.g. a clinical group × manufacturer. | S |
| COH-14 | Timeline (ADR-0049) of one case from its cell menu: its scans and events on one day axis (days from the earliest dated scan, no calendar date), a table alternative (DB-11), PNG and SVG export, and a form that adds an event to an event table (kind, day) or removes one. View-only links see it without the form. | S |

## Implementation plan

| Step | Work | Verify |
|---|---|---|
| C1 | VAR-14: `category` on `Variable` and `VariableOverride`, origin group computed from source and layer; the field map in `backend/app/variables/schema.py`; API-16 additive | Unit: every converter field has a category; override round trip; OpenAPI snapshot |
| C2 | Read endpoints (next free API IDs, added through `rw-api-change`): `POST …/cohort/rows` `{columns, filters, q, phase, sort, offset, limit ≤ 500}` → `{n_cases, n_scans, rows: [{case_id, values, differs[], scans: [{scan_idx, item_id, phase, modality, values}]}]}`; `POST …/cohort/summary` `{column, filters}` → counts or bins | API tests on `.fixtures/synthetic`: paging, sort, differs, filters equal to API-20 |
| C3 | `frontend/src/features/cohort/`: view, editor tab, navigator, grid, filters (shared with Search), Send to Explorer, Open in dashboard | Component tests; mock mode |
| C4 | Compare scans, column summary (ECharts, DB-11 rules), DICOM tags panel | Component tests |
| C5 | Export (CSV, PNG light/theme, SVG; the same chart export in the radiomics dashboard, DB-06), keyboard/ARIA pass, view-only check, e2e journey (open Cohort → filter by a bar → compare scans → open in viewer) | `rw-verify`, e2e |

C2 reads `index/variables.parquet` with column projection (scan unit = the scan's `complete` item) and reuses `table.matching_ids`; backend code lives in `app/cohort/` (read-only service + router) and never imports the labeling or curation writers.

## Implementation notes (K1)

- Cohort requests name variables plainly (`filters: {manufacturer: [...]}`); only the Explorer's query string uses the `var.` prefix.
- A bar of the column summary adds the filter value; a histogram bin adds `lo..hi` (inclusive range, VAR-06).
- The grid export pages through the API (500 cases a request) so it holds every filtered case, not the open page. The compare, summary and tags panels are session state; only group, pins, expansion and filters persist per project.
- The summary chart is `ValueSummary` in the dashboard plugin (lazy), so the Cohort and the radiomics dashboard share ECharts, the table view and the PNG / light PNG / SVG exports (DB-06).
- The navigator lists and the grid shows every non-constant variable of a group, whatever the catalog's `visible` flag says: the converter's acquisition fields are hidden by default elsewhere and are what this view is for.

## Agent requirements (ADR-0048)

Requests for after K1, not blockers; new Cohort code must not make them harder.

1. View state stays serializable plain data (filters, columns, colour-by) so it can move server-side; the dashboard's `GlobalFilters.var` and `CohortFilters.vars` converge on one filter shape.
2. An item-level source-dataset variable (import alias or `source_key`, category provenance) so merged projects can be grouped by origin.
3. Embedding: t-SNE as a method, `n_components=3` in the UI, an exposed seed.
4. Descriptives reachable without a full Analysis (or confirm that `Analysis.descriptives` is the path).
5. A workspace spans runs and datasets: no one-run assumptions in new Cohort code.

## K2: Clinical & labels (ADR-0046)

Implemented 2026-11-05.

| Step | Work | Where |
|---|---|---|
| K2.1 | Cohort edits Clinical & labels cells in place (COH-12): double-click (a yes/no cell toggles), or Edit value in the cell menu; Fill the filtered rows with this value; Paste values from here down; every write is a LBL-04 event with an Undo toast. | `features/cohort/ClinicalCell.tsx`, `clinical.ts`, `CellMenu.tsx` |
| K2.2 | Packs ship label table templates (`clinical_tables`, mCODE-aligned names); New table has a "Start from a template" choice for the applied packs. | `plugins/ccrcc/pack.json`, API-28, `NewTableDialog.tsx` |
| K2.3 | New external tables are retired (VAR-07, API-18 deprecated); Balance check over variables (COH-13, API-78). | `app/cohort/service.py`, `ContingencyMap` |

Notes: patient tables edit case rows, scan tables edit scan rows, item tables only in their own tab, reference columns never. Fill and Paste cover the filtered rows in the grid's current sort, one value per row, a spreadsheet's first column. COH-11 (promote a DICOM tag to a variable) is not built: the grid's variables read the index's `raw_metadata` keywords while the tags panel shows sidecar tag numbers, so it needs a sidecar reader and its own PHI review first.

## K3: Timeline (ADR-0049)

Implemented 2026-11-05 (COH-14, LBL-11/12, VAR-15, API-79/80). Events are rows of an `event` level label table (`kind`, `day`, optional columns); the Timeline reads scans and events as days from the case's earliest dated scan and never returns a calendar date. Time-to-event variables (`lbl.{table}.{kind}_days`, `_occurred`, `followup_days`) appear in the Clinical & labels group.

## Decisions

- Charts: ECharts in the browser over server aggregates (ADR-0009, DB-05); no server-rendered images. Charts are configured (variable, split, scale), not free-form; the chart type follows the variable type.
- External tables move to label table CSV import (ADR-0046 §5).
- The Search view stays during P7k; retiring it in favor of Explorer filters and Cohort is a separate cleanup after P7k.
