# ADR-0046 Clinical data and label tables are edited in Cohort, on the labeling engine
Status: Accepted · Date: 2026-11-04 (owner decision, same date)
Extends: ADR-0045, ADR-0022 (Labeling as a plugin on the event store). Partially supersedes: ADR-0011 for the external table (VAR-07).

**Context.** Non-image data about a case reaches the app three ways: label tables (LBL-*, edited in their own tab), external tables (VAR-07, imported once, read-only) and study fields inside `metadata.jsonl`.
Users see this as scattered: clinical facts, study groups and image annotations live in different views, with two CSV import paths.
For analysis, each of them is a typed variable at a level (patient, scan, item); only time-to-event data needs more (a time and an event).
The owner wants the Cohort dashboard to hold clinical data next to imaging metadata, without a new engine and without reshaping the app.

**Decision.**
1. Clinical data is stored as **label tables** (LBL-01) at patient level: no new store, event namespace or engine. Cell writes stay LBL-04 events with their validation, history, undo and live sync.
2. Cohort shows every label column in its **Clinical & labels** group (ADR-0045 navigator) and edits those cells in place through the same write path; Metadata, Automatic results, Review and Derived columns stay read-only there. View-only links stay read-only (UI-26).
3. One editor: the Cohort grid and the label table tab share the cell editors and the write path. The Labeling view keeps defining tables (create, columns, rename, delete, progress).
4. Study packs (PRJ-16) may ship clinical table templates (columns, types, units, levels, descriptions). Column names follow mCODE where a matching element exists; the core still names no field (ADR-0011).
5. CSV import into a label table (LBL-07) replaces the external table: once K2 ships, the app no longer offers new external tables, and existing ones stay readable as variables.
6. Dated events (Timeline: treatment, follow-up, recurrence, death) need an `event` level and a date policy (days from a per-patient anchor, time-to-event pairs, NFR-17). They require their own ADR before Timeline work.

**Consequences.** Clinical fields become variables (`lbl.{table}.{column}`, VAR-12) and so reach Explorer filters, the radiomics dashboard (DB-02, DB-07) and the Analysis panel (DB-08) with no extra integration.
VAR-07 becomes retired once K2 ships; its rows in VARIABLES.md and API-18 change then. LBL docs gain the Cohort editing path.

**Rejected alternatives.**
A separate clinical store or event namespace (a second engine with the same cell semantics).
Editing clinical values inside `metadata.jsonl` or as metadata overrides (R1; mixes scanner facts with human input).
Keeping external tables next to table CSV import (two ways to load the same data).
