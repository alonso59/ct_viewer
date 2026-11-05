# ADR-0045 Cohort dashboard: read-only imaging metadata by category; editable data in separate sections
Status: Accepted · Date: 2026-11-04 (owner decision, same date)
Extends: ADR-0011 (variable catalog), ADR-0020 (layers), ADR-0022 (event store). Does not change ADR-0012.

**Context.** The converter keeps the DICOM headers as intact as it can: about 140 row fields per scan in `metadata.jsonl` (DICOM_CONVERTER §Row fields) and a full sidecar per series (DCM-04).
The app profiles those fields into variables (VAR-01..05), but only shows them as a catalog (Variables view), as Explorer filters, or one item at a time (Image view).
A curator, physician or engineer has no ordered place to read the values of a case and its scans, compare scans, or narrow the cohort by a value without first knowing the field name.
The owner also wants to add clinical data (treatments, survival time, other covariates) next to the imaging metadata, later with longitudinal analysis.

**Decision.**
1. A project-level **Cohort** dashboard (editor tab) with sections. Its first section, **Metadata**, shows imaging metadata strictly **read-only**: no cell editors, no writes to `metadata.jsonl`, sidecars or the index. A wrong value is flagged through Curation (correction queue), never edited (R1).
2. Every catalog variable gets a **category** (VAR-14) that groups it for navigation. Converter fields are mapped to categories named after DICOM modules (Patient, Study, Series, Equipment, Technique, Contrast, Geometry, …) by a fixed field map; fields outside the converter schema go to **Dataset fields**. The map is field knowledge of the converter schema, not study knowledge, so the app still names no study field (ADR-0011). The user can override a category like a type.
3. The Metadata section reads only derived, rebuildable state (`index/variables.parquet`, the catalog, API-22 sidecars on demand); the server filters, sorts and pages, the client never loads the whole table (ADR-0009).
4. Editable data lives only in later sections, **Clinical** (per-patient fields) and **Timeline** (dated events per patient). They will be written as events in the shared event store (ADR-0022) and become variables like label columns (VAR-12). Their storage, levels and date policy need their own ADR before work starts.
5. Survival and longitudinal statistics stay out of scope (VISION §Out of scope, ADR-0012) until a further ADR supersedes that.

**Consequences.** One new owner doc (`frontend/COHORT.md`, prefix `COH-`), one catalog field (`category`) and one read endpoint family. The Search view and Cohort share the filter model (VAR-10); no second filter syntax.
The Metadata section is safe for view-only links, except the flag action. New converter fields need a category in the map (a test enforces it).

**Rejected alternatives.**
Editable metadata cells stored as overrides (blurs what the scanner wrote with what a person decided; Curation and Labeling already hold decisions).
Categories inferred from field names at runtime (unstable, study-specific names would land in DICOM categories).
A separate clinical database or server (contradicts ADR-0002 and R3).
Extending the radiomics dashboard (it is scoped to one run, DB-01; metadata exists without any run).
