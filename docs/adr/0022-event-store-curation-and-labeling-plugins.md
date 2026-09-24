# ADR-0022 Shared event store; Curation & QC and Labeling table as plugins
Status: Accepted · Date: 2026-09-24
Amends: CUR-02 (the event log becomes a core service), ADR-0018 (first plugins on it)

**Context.** Curation already has an append-only, reviewer-stamped, SSE-synced event log with last-writer-wins state. A labeling table (user-defined columns at patient or CT level) needs exactly the same guarantees. Both should be plugins the user reaches from the Library.

**Decision.**
1. **Core event store.** Append-only JSONL per namespace (`events/{namespace}.jsonl`) with reviewer stamp, `session_id`, SSE fan-out (API-40), a derived last-writer-wins state per key, and history. Curation keeps its file (`curation/events.jsonl`) as namespace `curation`, so nothing migrates.
2. **Curation & QC plugin.** It is today's CUR-* unchanged (statuses, targets with `seg_id`, queue, exports, v2 and converter-CSV imports, shortcuts, history, live sync), packaged as a plugin: view, inspector section, queue tab and commands. It is enabled by default.
3. **Labeling table plugin** (new LABELING.md, LBL-*):
   - the user creates tables at **patient (case)**, **CT scan** or **item** level;
   - each table has typed columns (yes/no, category, number, text, date) named freely or after the project labels;
   - editing is spreadsheet-style: keyboard, bulk fill, paste from spreadsheets, filter by any variable, a row opens the viewer;
   - every cell edit is an event in namespace `labeling`;
   - every column is a metadata layer (ADR-0020) and therefore a variable (`lbl.{table}.{column}`), usable in filters, analysis and task selection.
4. **View-only links** (ADR-0019) see both plugins read-only.

**Consequences.**
- \+ One audit and sync mechanism for every human decision.
- \+ Labeling turns into study variables without code.
- − Curation code moves behind a plugin boundary (no data change).
- Owner docs on acceptance: CURATION (plugin note, event store), LABELING.md (new, LBL-), DATA_MODEL (EventNamespace, LabelTable), API (event store + labeling routes), VARIABLES (`lbl.*`), UI_SHELL.

**Rejected.**
- Labels stored as new columns in `metadata.jsonl`: ADR-0020.
- A separate sync mechanism for labeling: duplicates CUR-11/12.
