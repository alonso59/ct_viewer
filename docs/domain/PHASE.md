# Phase

Scope: native phase selection — one-click correction, storage, precedence, exports.
Read when: touching phase anywhere (case/scan header, Explorer, labeling reference columns, exports).
Depends: ANALYZERS.md (phase guesses, resolution), INPUT_METADATA.md (`phase.json`, §Phase resolution), PROJECT_FORMAT.md (`phase_vocabulary`, PRJ-16), ADR-0022 (event store), ADR-0026.

Phase selection is a native app capability (ADR-0026) — always available, not gated by any plugin. The `analyzers` plugin still guesses (ANALYZERS.md); `curation` does not touch phase.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| PHS-01 | One-click phase buttons, one per `phase_vocabulary` value, in the case/scan header and Explorer row actions. A click writes an event immediately and replaces the effective phase for that scan; no confirmation step, no separate "unsure" flag. | M |
| PHS-02 | Storage: the `phase` namespace on the core event store (ADR-0022), `events/phase.jsonl`. Event: `{event_id, at, reviewer, session_id, case_id, scan_idx, value, source: "manual" \| "analyzer_accept" \| "v2_import" \| "converter_import", accepted_run_id}`. State = latest event per `(case_id, scan_idx)`. | M |
| PHS-03 | Effective phase precedence: latest `phase` event (if any) → `Item.phase.canonical` (INPUT_METADATA §Phase resolution, unchanged). The event never touches `metadata.jsonl`, `phase.json` or the index (R1) — it is a layer joined at read time (ADR-0020 §3), same pattern curation/labeling state already use. | M |
| PHS-04 | Accepting the active `analyzer.phase` run's guess is the same one-click action, `source: "analyzer_accept"`, `accepted_run_id` set (replaces the prior curation-event flow, ANZ-07). | M |
| PHS-05 | Live sync: a `phase.appended` event pushes to other open browsers via SSE (as ADR-0022); "Updated by {reviewer}". | M |
| PHS-06 | Export: `exports/phase_selections.json`, shaped like `phase.json` (INPUT_METADATA §`phase.json`), so a correction can be fed back in as a future import override. | M |
| PHS-07 | History panel per scan, newest first (same pattern as CUR-14). | S |
| PHS-08 | Import compatibility: the standalone converter's `curation.csv` `curated_phase` (previously CUR-15) and v2's `phase_issue` map to a native `phase` event (`source: "converter_import"` / `"v2_import"`) instead of a curation event. One import per `case_id|scan_idx` (v2: the latest row per scan). An import never overrides a scan that already has a selection: that row is reported under `skipped` with the reason "phase already set", and `phase_events` counts the events written. | S |

## Where the effective phase surfaces

- Case/scan header, Explorer, viewer: PHS-03's effective value, always.
- `dataset_table` / `dataset.jsonl` (ADR-0020 §4, ADR-0025): `phase` = effective value; a `phase_source` note is `manual` or the INPUT_METADATA resolution winner (e.g. `analyzer:{run_id}`).
- Labeling reference columns (LABELING.md LBL-02, `VAR-13 comparable`): the native phase (and, separately, the analyzer's guess) can be added read-only into any label table.

## Implementation (ADR-0026 amendment)

- Backend `app/phase/` (API-63..65): events via the core event store; the effective phase is joined where the index is loaded (`phase.source = "manual"`, the replaced value in `phase.resolved`), never written to `index/`.
- Frontend `features/phase/` (core, not a plugin): `PhaseButtons` in the case header ("Set phase", next to the scan switcher, whose chips only move between scans) and in each Explorer scan row (shown on hover, focus or the active row); "Accept guess" when the effective value comes from the active `analyzer.phase` run (`analyzer:{run_id}`); "was …" shows the replaced value; a history dialog per scan (PHS-07); "updated by" toasts for other browsers (PHS-05); the command "Export phase selections" (Project menu, PHS-06). View-only links show the chip only.

## Relation to Curation & QC / Analyzers

Curation records QC decisions about images and masks; it no longer has a phase target or status. Analyzers only guess; accepting a guess is a phase event, not a curation event. Both still use the same shared event store (ADR-0022), under a different, native namespace.
