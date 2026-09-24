# ADR-0020 `metadata.jsonl` belongs to the converter; plugin data lives in layers
Status: Proposed · Date: 2026-09-24
Amends: ADR-0017 (the converter emits no phase or curation fields), DCM-08/09, ANZ-04, INPUT_METADATA §contract v1

**Context.** The legacy converter mixed three concerns into `metadata.jsonl`:
- image facts;
- guesses (`phase_guess`, target match);
- human decisions (`curated_*`, `curation.csv`, `group`).

In v3, phase is a plugin, curation is a plugin, and `group` is no longer a core concept (ADR-0011). Plugins must add data without rewriting a file that is also an input snapshot.

**Decision.**
1. **The converter owns `metadata.jsonl`.** Its artifact is contract v1 core fields plus DICOM facts (DICOM_CONVERTER §Row fields). It contains no `phase_guess*`, `curated_*`, `group`, `include_guess`/`target_match_*` or other study logic, in the app and in the CLI alike. The CLI no longer writes `curation.csv`.
2. **Compatibility.** Imports keep accepting existing `metadata.jsonl` files that carry the legacy fields: IMP phase resolution reads them, and an old `curation.csv` is imported once through CUR-15.
3. **Plugin data is layers, never file edits.**
   - Each plugin output (phase annotations, organ/readiness, labeling columns, curation state) is a **column layer** stored by that plugin in the project, keyed by case, scan or item, with provenance (plugin, version, run or reviewer, time).
   - The **metadata table** the UI shows is the converter/adapter rows joined with the active layers. Variables (VAR) read that table.
4. **Exports.** `metadata.jsonl` is never regenerated with plugin columns. A separate **dataset table export** (CSV / Parquet, `exports/dataset_table.*`) gives the merged view on demand, with one column per active layer and a header naming each layer's source.
5. **Phase with the converter.** The converter overlay (ADR-0021) can chain `analyzer.phase` right after conversion (on by default). Its result is the phase layer, not a field of `metadata.jsonl`.

**Consequences.**
- \+ Clean ownership: facts in the converter file, guesses and decisions in layers.
- \+ Nothing is overwritten; everything is traceable and multi-user safe.
- − Two exports to explain (converter artifact vs dataset table).
- Owner docs on acceptance: DICOM_CONVERTER (DCM-08/09/13), INPUT_METADATA, ANALYZERS (layers), VARIABLES, DATA_MODEL (Layer), CURATION.

**Rejected.**
- Rewriting `metadata.jsonl` with plugin columns: breaks R1 and snapshots, and loses provenance.
- A merged file named `metadata.jsonl`: confusable with the converter artifact.
