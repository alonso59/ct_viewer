# ADR-0021 CT tools without a project; workspace tasks; the converter overlay
Status: Proposed · Date: 2026-09-24
Amends: ADR-0014 (a second derived location outside projects), SRC-09 (tasks in Open mode), VW-17

**Context.** Opening a file or folder without a project works, but Open mode lacks the CT controls of the case tab. Converting DICOM requires a project today, while users want to convert first and decide later.

**Decision.**
1. **One CT tool set** for the case tab and Open mode, for a file or a folder alike:
   - **Must:**
     - W/L presets, numeric W/L, the DICOM header window;
     - layout; zoom/pan; crosshair; slice slider; reset; screenshot;
     - HU probe; header info (NIfTI header / DICOM tags);
     - modality selector when assumed.
   - **Should:** slab MIP / MinIP / average with thickness; distance, angle and ROI mean/SD in HU; invert.
   - **Could:** cine; histogram; colour maps for MR.

   Measurements are not persisted without a project (VW-17 moves from C to S).
2. **Workspace tasks.** A task manifest may declare `scope: workspace`, meaning it runs without a project. Its outputs go to `{derived root}/_datasets/{name}/`, which is write-once and never modified, and can then be opened (SRC-09) or imported into a project. The converter is the first workspace task. Project-bound plugins (curation, labeling, radiomics) still need a project.
3. **Converter overlay window.** One button opens it from Welcome, from Open mode on DICOM, from the Library, and from a project's Data tab. It is a modal work window with these steps:
   1. source;
   2. settings (schema form: organ focus, phase analyzer on/off, anonymize);
   3. dry-run estimate;
   4. run with progress;
   5. result: the `metadata.jsonl` artifact, with Open / Create project / Add to project.

**Consequences.**
- \+ Anyone can view and convert in minutes without project ceremony.
- \+ One tool set to maintain.
- − Two derived locations outside projects (`_open/` exports and `_datasets/`), both write-once.
- Owner docs on acceptance: VIEWER (VW-22..), SOURCES (SRC-09/14), TASKS (`scope`), DICOM_CONVERTER (DCM-14 overlay, workspace scope), ADR-0014 note, UI_SHELL (overlay).

**Rejected.**
- A hidden scratch project for projectless conversion: pollutes the registry (as in ADR-0013).
- Separate simplified tools for Open mode: two tool sets drift.
