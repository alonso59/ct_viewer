# ADR-0017 DICOM converter as a task; metadata analyzers as separate, composable tasks
Status: Accepted · Date: 2026-09-24
Amends: VISION §Out of scope ("DICOM import, DICOM→NIfTI conversion"), INPUT_METADATA §Phase resolution

**Context.** The owner's converter (`legacy/convert/`, reference only, R9; pydicom + SimpleITK) mixes seven stages in one pipeline: discovery, header inspection, case numbering, organ focus and series selection, phase inference, NIfTI writing, and `metadata.jsonl` / `curation.csv` writing. Only NIfTI writing touches pixels. Phase and organ rules should be rerunnable without reconverting, and usable on data from other sources.

**Decision.**
1. **Split by concern.**
   - `plugins/dicom/` is `dicom.convert`: scan → select → convert, plus DICOM JSON sidecars.
   - `plugins/analyzers/` holds `analyzer.phase`, `analyzer.target` (organ focus) and `analyzer.readiness`.
   - Both are builtin tasks.
2. **Analyzer interface.** A pure function `analyze(rows, config) → annotations` with value, confidence and evidence; no pixels. It runs in two ways:
   - inside the converter, before conversion (the organ focus saves disk);
   - standalone on an imported project.
3. **Annotations never overwrite data.** The active run per field joins resolution with provenance; phase: after the explicit fields, before `phase_guess` (ANZ-04). Users accept a proposal through curation (CUR-06).
4. **Presets drive the analyzers.** A preset (PRJ-12) names the target profile and phase vocabulary; `ccrcc` = `kidneys` + NC/CMP/NP/EP.
5. **Faithful metadata.**
   - Contract v1 rows, plus one DICOM JSON Model sidecar per series (PS3.18 §F.2, no PixelData).
   - Case numbering follows the identity policy (ADR-0013).
   - Manual decisions are curation events; an existing `curation.csv` is imported once (CUR-15).
6. **Standalone CLI.** It keeps working outside the app.

Details: DICOM_CONVERTER.md (DCM-*), ANALYZERS.md (ANZ-*).

**Consequences.**
- \+ Rules evolve without reconversion.
- \+ The converter stays small.
- \+ The same rules apply to any source.
- − The code must be ported and wrapped (P7b); `legacy/convert/` is then deleted.

**Rejected.**
- Analyzers kept inside the converter: not rerunnable.
- Fully independent programs with their own formats: two contracts.
