# Metadata analyzers

Scope: metadata-only tasks (phase, organ focus, readiness): interface, annotations, activation, presets.
Read when: working on `plugins/analyzers/`, phase guessing, series selection, or annotation proposals.
Depends: ADR-0017, ADR-0020, ADR-0026, TASKS.md, INPUT_METADATA.md §Phase resolution, PHASE.md (native selection, accepting a guess), PROJECT_FORMAT.md (PRJ-16 packs).

Analyzers read metadata rows only (no pixels, no files besides the rows) and **propose** values; they never overwrite data.
Code and term lists: `plugins/analyzers/` (ported from `legacy/convert/policy.py` and `legacy/convert/metadata.py`, reference only, R9). The term lists live in code, not in this doc.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| ANZ-01 | Interface: `analyze(rows, config) → annotations`, where each annotation is `{key, field, value, confidence, evidence, rules_version}`. `key` is `item_id` in a project, or the row key `(case_identity_key, series_uid)` inside the converter. Pure and deterministic. | M |
| ANZ-02 | Two modes: a stage inside `dicom.convert` (between scan and convert), or a standalone task (`input: rows`) on an imported project. The code is the same in both. | M |
| ANZ-03 | `confidence` ∈ `high`, `medium`, `low`, `unknown`. `evidence` is a short human-readable reason (e.g. "non-contrast text", "delay 32 s"). | M |
| ANZ-04 | Annotations are metadata layers (ADR-0020): never written into `metadata.jsonl`, also when the converter chains the analyzer. Activation: `project.json.annotation_sources = {field: run_id \| null}`. Changing it rebuilds the index (PRJ-10); a new run is not active until the user activates it (default: activate if none is active). | M |
| ANZ-05 | Study packs (PRJ-16) configure the analyzers: the `ccrcc` pack → target `kidneys` + vocabulary NC/CMP/NP/EP/UNK. With no pack: target `generic`, raw phase values mapped to UNK only when empty; the converter overlay still offers the phase analyzer. | M |
| ANZ-06 | Output values are in the project `phase_vocabulary` or `UNK`. Compound or conflicting guesses (e.g. text vs timing) become `UNK` with `confidence: low` and the conflict in `evidence`. | M |
| ANZ-07 | Accepting a phase proposal is a native phase event (PHS-04, `source: "analyzer_accept"`), not a curation event; annotations themselves are never edited. | M |
| ANZ-08 | Rerunning with changed rules is a new run with a new `rules_version`; older runs stay for comparison. | S |

## Analyzers

| Task | Field(s) | Inputs used | Rule summary |
|---|---|---|---|
| `analyzer.phase` | `phase` | study/series description, protocol name, contrast bolus tags, series vs injection times | Text terms first; contrast timing (delay seconds) second; text/timing conflict → `UNK` (ANZ-06); contrast without evidence → `UNK` |
| `analyzer.target` | `target_match` (`strong` \| `compatible` \| `weak` \| `excluded` \| `none`) | body part, descriptions, protocol | Profile term lists (`generic`, `kidneys`, `pancreas`, `lung`, `brain`, `heart`); inside the converter, `excluded` series aren't converted unless `convert_excluded` |
| `analyzer.readiness` | `output_role` (`PRIMARY` \| `SECONDARY` \| `EXCLUDED`), `readiness` | modality, image type, localizer/scout, intervention, geometry codes (DCM-03), spacing quality | Localizer and intervention → `EXCLUDED`; unsafe geometry → `not_ready` with the codes as evidence |

## Where annotations enter

- Phase resolution (INPUT_METADATA): `phase.json` → `curated_phase` → `canonical_phase` → `phase` → **active `analyzer.phase` run** → `phase_guess` → `UNK`. `phase_source` names the winner (`analyzer:{run_id}`). This is the index-time resolution only; a native phase selection (PHASE.md, PHS-03) joins on top at read time and wins over all of it when present.
- `target_match` and `readiness` become study variables (VAR-*), usable in filters and task selection (TSK-03).
- The Image view shows each annotation with confidence and evidence; Search can filter "low-confidence phase".

## Implementation notes (P7b Wave 3)

- Values: `target_match` ∈ `strong`, `compatible`, `weak`, `excluded`, `none`; `output_role` ∈ `PRIMARY`, `SECONDARY`, `EXCLUDED` (evidence = the reason, e.g. `localizer`); `readiness` ∈ `ready`, `ready_with_warning`, `review_required`, `unsuitable`, `unknown` (evidence = the codes or reasons). Phase guesses map to the vocabulary: NC → `NC`; CMP → `CMP` or `ART`; NP → `NP` or `PV`; excretory/delayed → `EP` or `DELAYED`; anything else → `UNK`.
- Tasks `analyzer.phase|target|readiness` (`input: rows`): rows are the items' `extra` plus `item_id`, `case_id`, `scan_idx`, `modality`. `target_profile` defaults to the preset's (`ccrcc` → `kidneys`, `generic-ct` → `generic`) through the job's `context`.
- Annotations are stored as `tasks/runs/{run_id}/annotations.jsonl` lines `{item_id, field, value, confidence, evidence, rules_version}`. Activation and deactivation (API-48 PUT) start a reindex job; active non-phase fields are joined into the items' `extra` (study variables).
