# ADR-0026 Phase selection is native to the app, not a curation decision
Status: Accepted · Date: 2026-09-25
Amends: ADR-0020 §3 (adds a native, non-plugin layer), ADR-0022 (adds the `phase` namespace to the shared event store, consumed natively), ADR-0025 (`dataset.jsonl` `phase` provenance)
Refines: CUR-06/07/08/10/15, ANZ-07, LBL-02

**Context.** The legacy app let a reviewer set a scan's phase with one click (a row of phase buttons), applied instantly — but by rewriting the converter's output file directly, which ADR-0020/R1 later ruled out on purpose. v3 kept the one-click *shape* but moved it behind the `curation` plugin as `CUR-06 proposed_phase`: an event that never becomes the effective value, requiring a separate reconciliation step nothing currently performs. That mismatch is the friction being fixed. Separately, `phase_vocabulary` already lives in core project config (`project.json`, PRJ-16) — treating phase *selection* as plugin-owned while its vocabulary is core is an inconsistency.

**Decision.**
1. **Phase selection is native**, not part of the `curation` plugin, and not gated by any plugin being enabled. One-click buttons (one per `phase_vocabulary` value) sit in the case/scan header and Explorer row actions; a click writes an event immediately, replacing the effective phase for that scan — no propose/apply split, no "wrong phase, unsure" flag (a direct correction replaces it outright). Requirements move to a new owner doc, `docs/domain/PHASE.md` (`PHS-*`).
2. **Storage**: a new `phase` namespace on the shared event store (ADR-0022's core service, not the `curation` plugin's). Latest event per `(case_id, scan_idx)` wins. This never touches `metadata.jsonl`, `phase.json`, or the index (R1) — it is a layer joined at read time on top of `Item.phase.canonical` (INPUT_METADATA §Phase resolution, unchanged).
3. **`analyzers` plugin is unchanged**: it still only guesses (`analyzer.phase`, confidence/evidence, ANZ-01..06). Accepting a guess (previously ANZ-07's curation event) is now the same native one-click action with `source: "analyzer_accept"`.
4. **Curation drops phase entirely**: `CUR-06`, the `phase` target, and the `wrong_phase_suspected` status are removed from CURATION.md. `CUR-15`'s `curated_phase` mapping moves to a native import-compat rule in PHASE.md.
5. **Exports/dataset.jsonl**: `dataset_table`/`dataset.jsonl`'s `phase` reflects the effective value (native selection, else the resolved value); a `phase_source` note distinguishes `manual` from the INPUT_METADATA resolution winner — same provenance pattern ADR-0025 already uses for reconstructed sidecars. `curation`'s `phase_proposals.json` export (CUR-10) is replaced by a native `exports/phase_selections.json` (PHASE.md).
6. **Labeling gains a read-only "reference column"** (`LBL-02`): a column that mirrors an existing *comparable* variable (native phase, analyzer `phase`, `target_match`, `readiness`, another table's column) instead of being author-edited; no new events. Which variables qualify is a new `comparable` flag (`VAR-13`), true for categorical/layer-sourced variables, false for continuous ones — lets a reviewer put the app's phase (guess and/or confirmed) next to their own manual classification without re-entering it.

**Consequences.**
- \+ One-click parity with legacy without reintroducing file mutation (R1 holds).
- \+ Phase works with `analyzers`/`curation` disabled or `pending`.
- \+ Labeling gets side-by-side comparison for free.
- − A new precedent: a layer graduates from plugin-owned to native when its *vocabulary/schema* is already core config (`phase_vocabulary`), even though its *content* stays pluggable (`analyzer.phase`). Future "native or plugin" calls should use this rule.
- − One more owner doc (`PHASE.md`) and prefix (`PHS-`) to keep in sync with ANALYZERS.md/CURATION.md/LABELING.md.

**Rejected.**
- Keeping `phase` as a curation target with an explicit "apply" step: the exact friction this ADR fixes.
- Keeping `wrong_phase_suspected` as a separate "flag, unsure" status: a direct one-click correction is as fast and strictly more useful; nothing needs the extra state.
- Reproducing legacy's direct file mutation: breaks R1/ADR-0020 (snapshot integrity, provenance, multi-user safety).

**Doc updates required:** new `docs/domain/PHASE.md` (`PHS-*`); `CURATION.md` (remove CUR-06, `phase` target, `wrong_phase_suspected`, CUR-10/15 phase parts); `ANALYZERS.md` (ANZ-07); `LABELING.md` (LBL-02 reference columns); `VARIABLES.md` (VAR-13 `comparable`); `DATA_MODEL.md` (PhaseEvent entity); `PLUGINS.md` (native-vs-plugin note); `PROJECT_FORMAT.md` (`exports/` tree); `docs/adr/README.md`; `docs/INDEX.md` (`PHS-` ownership row).
