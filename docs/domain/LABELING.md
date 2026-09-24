# Labeling table plugin

Scope: user-defined label tables at patient, CT or item level; columns, editing, storage, variables.
Read when: working on `plugins/labeling/` or label-derived variables.
Depends: ADR-0020, ADR-0022, PLUGINS.md, VARIABLES.md, CURATION.md (event rules).

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| LBL-01 | A project can hold several tables; each has a name and a **level**: `case` (patient), `scan` (one CT) or `item` (scan × scope × side). Rows are the project's cases, scans or items, filtered like the Explorer. | M |
| LBL-02 | Columns: name (free, or picked from the project label map), type (`bool`, `category` with levels, `number` with unit/min/max, `text`, `date`), optional description and default. A rename keeps the column id; a deleted column is hidden, and its events are kept. | M |
| LBL-03 | Spreadsheet-style editor tab: keyboard navigation, type-aware cell editors, bulk fill of a selection, paste from a spreadsheet (TSV), column filter and sort, "open in viewer" for the row (split with the case tab). | M |
| LBL-04 | Every cell change is an event in namespace `labeling` (ADR-0022): `{table_id, column_id, target, value, reviewer, session_id, at}`. State = latest event per `(table, column, target)`; the cell history is visible. | M |
| LBL-05 | Live multi-user: edits by others appear through SSE; last-writer-wins per cell (as CUR-12). View-only links see the table read-only. | M |
| LBL-06 | Each column is a metadata layer (ADR-0020) and a typed variable `lbl.{table}.{column}` at the table's level (VAR-*): filters, colour-by, analysis, task selection. | M |
| LBL-07 | Import a CSV keyed by `case_id` / `patient_id` / scan or `item_id` into a table (a match report as VAR-07); export a table as CSV/Parquet. | S |
| LBL-08 | Progress per table (filled / total rows per column) in the Labeling view. | S |

## Storage

```text
{project}/plugins/labeling/tables.json   # table + column schemas (API process is the only writer)
{project}/events/labeling.jsonl          # append-only cell events (LBL-04)
```

## Relation to Curation & QC

Curation records **QC decisions** about images and masks (status, queue, targets with `seg_id`). Labeling records **study annotations** as typed columns. Both use the same event store and sync (ADR-0022) and never write to `metadata.jsonl` (ADR-0020).
