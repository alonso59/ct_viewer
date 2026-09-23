# Curation

Scope: reviewer identity, curation events, statuses, rollups, correction queue, exports.
Read when: building curation UI/API, audit, or multi-user sync.
Depends: DATA_MODEL.md, PROJECT_FORMAT.md, ADR-0004.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| CUR-01 | On first write in a browser, ask for a reviewer name or initials. Store it in `localStorage` and show it in the status bar, where it can be changed. | M |
| CUR-02 | Every decision is an append-only event in `curation/events.jsonl`. There is no update or delete; a correction is a new event. | M |
| CUR-03 | Decisions target an Item (and optionally a label) or a whole Case. | M |
| CUR-04 | QC status set: see §Status. One-click buttons for the common ones, plus a keyboard shortcut per status (UI-12). | M |
| CUR-05 | Free-text comment and priority (`low`, `medium`, `high`) on any decision. | M |
| CUR-06 | Phase proposal: `proposed_phase` from `phase_vocabulary`. Stored as an event only; the index is unchanged. | M |
| CUR-07 | Side/laterality flag: `wrong_side_suspected` with optional `proposed_side`. | M |
| CUR-08 | Derived state = latest event per `(item_id, target)`. Case rollup = worst status by the severity order below. | M |
| CUR-09 | Correction queue = items whose latest status is in the queue set, or with `add_to_queue=true`; exportable as CSV for 3D Slicer work. | M |
| CUR-10 | Exports: `curation_state.csv`, `events.jsonl` copy, and `phase_proposals.json` (shaped like `phase.json`) into `exports/`. | M |
| CUR-11 | Live sync: new events are pushed to other open browsers via SSE (API-40). The UI shows "Updated by {reviewer}". | M |
| CUR-12 | Conflict policy: last-writer-wins on derived state; history shows every event. | M |
| CUR-13 | Import v2 `curation_review.csv` as events (`source: "v2_import"`). | S |
| CUR-14 | History panel per item and per case, newest first. | M |

## Status

| Status | Severity (rollup order, high→low) | In queue |
|---|---|---|
| `rejected` | 8 | ✓ |
| `needs_major_correction` | 7 | ✓ |
| `wrong_phase_suspected` | 6 | ✓ |
| `wrong_side_suspected` | 6 | ✓ |
| `needs_minor_correction` | 5 | ✓ |
| `missing` | 4 | ✓ |
| `cannot_assess` | 3 | |
| `accepted` | 1 | |
| `not_reviewed` | 0 | |

## Targets

`seg` (whole mask) · `label:{value}` (e.g. `label:2`, tumor) · `voi_mask` · `phase` · `side` · `case`.
Targets follow the project label map (PRJ-07), so no label names are hard-coded.

## Event schema (v1)

```jsonc
{
  "event_id": "01J…", "schema_version": 1,
  "at": "2026-09-23T10:00:00Z",
  "reviewer": "Dr. AP",
  "session_id": "…",                     // random per browser tab, for audit
  "item_id": "case_00001.01.complete.-", // or null when target = case
  "case_id": "case_00001",
  "target": "label:2",
  "status": "needs_minor_correction",
  "priority": "medium",
  "comment": "Tumor boundary leaks into renal sinus on slices 110–118",
  "proposed_phase": null, "proposed_side": null,
  "add_to_queue": false,
  "context": {                            // snapshot for audit; not used for logic
    "image_fp": "…", "mask_fp": "…", "phase": "NP", "import_id": "01J…",
    "viewer": { "axis": "axial", "slice": 114, "ww": 400, "wl": 50 }
  },
  "source": "ui"                          // ui | v2_import | api
}
```

## Correction queue CSV columns

`case_id, item_id, scope, side, phase, target, status, priority, comment, reviewer, at, image_path_abs, mask_path_abs`.
Absolute paths are resolved at export time so the 3D Slicer user can open the files directly.

## Deferred

- Review sessions (start/stop timer, per-session progress): v3.1.
