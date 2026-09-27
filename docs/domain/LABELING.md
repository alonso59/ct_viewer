# Labeling table plugin

Scope: user-defined label tables at patient, CT or item level; columns, editing, storage, variables.
Read when: working on `plugins/labeling/` or label-derived variables.
Depends: ADR-0020, ADR-0022, ADR-0026, PLUGINS.md, VARIABLES.md (VAR-13 `comparable`), CURATION.md (event rules), PHASE.md.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| LBL-01 | A project can hold several tables; each has a name and a **level**: `case` (patient), `scan` (one CT) or `item` (scan × scope × side). Rows are the project's cases, scans or items, filtered like the Explorer. | M |
| LBL-02 | Columns: name (free, or picked from the project label map), type (`bool`, `category` with levels, `number` with unit/min/max, `text`, `date`), optional description and default. A rename keeps the column id; a deleted column is hidden, and its events are kept. | M |
| LBL-09 | Reference column (ADR-0026): instead of an authored type, a column can mirror an existing `comparable` variable (`VAR-13`, e.g. native phase, analyzer `phase`, `target_match`, `readiness`, another table's column) — resolved live, read-only, no cell events. Add-column picker lists only `comparable` variables. | S |
| LBL-03 | Spreadsheet-style editor tab: keyboard navigation, type-aware cell editors, bulk fill of a selection, paste from a spreadsheet (TSV), column filter and sort, "open in viewer" for the row (split with the case tab). From the case: the Inspector section "Labels · this case / scan" shows, per table, the cells of the row on screen (the case, its scan or the item, by level) with the same editors and cell events. | M |
| LBL-04 | Every cell change is an event in namespace `labeling` (ADR-0022): `{table_id, column_id, target, value, reviewer, session_id, at}`. State = latest event per `(table, column, target)`; the cell history is visible. | M |
| LBL-05 | Live multi-user: edits by others appear through SSE; last-writer-wins per cell (as CUR-12). View-only links see the table read-only. | M |
| LBL-06 | Each column is a metadata layer (ADR-0020) and a typed variable `lbl.{table}.{column}` at the table's level (VAR-*): filters, colour-by, analysis, task selection. | M |
| LBL-07 | Import a CSV keyed by `case_id` / `patient_id` / scan or `item_id` into a table (a match report as VAR-07); export a table as CSV/Parquet. | S |
| LBL-08 | Progress per table (filled / total rows per column) in the Labeling view. | S |
| LBL-10 | A table can be renamed (id and slug kept, so `lbl.{table}.*` names don't change) and deleted. Delete hides the table: it leaves the Labeling view, its columns stop being layers and variables (LBL-06), and its cells can't be written; its events stay in `events/labeling.jsonl` and its slug stays reserved, so Restore brings it back unchanged. Nothing is erased (ADR-0022). Deleted columns (LBL-02) can be restored the same way. | S |

## Storage

```text
{project}/plugins/labeling/tables.json   # table + column schemas (API process is the only writer)
{project}/events/labeling.jsonl          # append-only cell events (LBL-04)
```

## Implementation notes

- Backend `app/labeling/` (+ `app/api/v1/labeling.py`, API-56..58, also `GET …/tables/{tid}/history`), plugin manifest `plugins/labeling/plugin.json`. Tables and columns get a `slug` from their first name (unique; kept on rename), which names the variable `lbl.{table}.{column}`. Cell writes validate all cells first (422 lists every bad one), then append one event each through the core event store; `null` clears a cell. Types: `bool` (yes/no, true/false, 1/0), `category` (a level, case-insensitive), `number` (`,` decimal accepted, min/max), `text` (≤ 2000), `date` (ISO). Rows: active cases / `case.scan` / items in index order; the row's viewer item is its complete-scope item.
- LBL-06: a layer provider (dataset table column `lbl.{t}.{c}@labeling:{t}`) and variables of source `layer` with the column's type (`bool`/`category` → categorical, `number` → continuous); scan and item tables use the scan unit (an item value lands on its scan). The catalog is rebuilt 1 s after the last write (coalesced).
- LBL-07: CSV/TSV import keyed by `case_id`, `patient_id`, `scan`, `item_id` or `target`; columns matched by name or slug; report = matched / unmatched keys, matched and ignored columns, invalid values, events written. Export CSV / Parquet (`target, case_id, columns…`).
- UI (`frontend/src/plugins/labeling/`, lazy): the Labeling view (tables with per-column progress, New table with columns named freely or from the project labels), the table tab `/p/{pid}/labeling/{tid}`: virtualized grid, arrow/Tab/Enter navigation, typing or Enter/F2 edits (type-aware editors), Space toggles yes/no, Delete clears the selection, Shift+click / Shift+arrows select, paste of a TSV block at the active cell, "Fill selection", per-column filters (`-` = empty) and sort, open the row in the viewer, cell history panel, CSV import report, export. Live sync: `labeling.appended` (or `project.updated` with `labeling`) refreshes the table. View-only links show the view and tab with a "Read only" badge and no editing.
- LBL-09: a column with `ref` (a variable name, set on creation only) is a reference column: the variable must be `comparable` and, for a patient table, case-level (422 otherwise). Values are read from `index/variables.parquet` on each cell read, so they follow their source after the catalog rebuild (≈ 1 s after a phase selection or a cell write); writes and CSV import refuse it; it is not a layer, a variable or a progress column itself; the CSV/Parquet export includes its current values. UI: the type "Reference (read-only)" in Add column / New table, a link icon in the header, muted read-only cells.
- LBL-02/10 (UI): a column header menu has Edit column… (name, description; levels for `category`; unit, min, max for `number`; the type is fixed) and Delete column…; a table card menu has Edit table… (rename, restore deleted columns) and Delete table…. Deleted tables are listed under "Deleted tables" in the Labeling view with Restore; deleting a table closes its tab. Writes and CSV import to a deleted table answer 404.

## Relation to Curation & QC

Curation records **QC decisions** about images and masks (status, queue, targets with `seg_id`). Labeling records **study annotations** as typed columns. Both use the same event store and sync (ADR-0022) and never write to `metadata.jsonl` (ADR-0020).
