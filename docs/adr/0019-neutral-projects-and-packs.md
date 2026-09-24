# ADR-0019 Neutral projects, study packs, view-only links
Status: Accepted · Date: 2026-09-24
Supersedes: PRJ-12 (presets chosen at creation). Amends: ADR-0004 (view-only link), ANZ-05

**Context.** A project exists to give data an ID, a share link and a place where several people view and work together. Today "New project" forces a study preset (ccRCC / Generic CT / None) that seeds labels and phases before any data is seen.

**Decision.**
1. **A project is neutral.** It has a ULID, a name, a description, a share link, sources and a **default modality** (`CT` | `MR` | `mixed`, default `CT`). The default modality only decides the viewer default when an item has none (VW-05). "New project" asks for a name only; the modality is optional.
2. **Study packs.** Presets become first-party plugin `packs` (ADR-0018). A pack holds a label map, a phase vocabulary and mapping, an organ profile for `analyzer.target`, and optionally a radiomics profile. A pack is applied from Project settings at any time; applying one records `packs[]` and never deletes curation or data. `ccrcc` is the first pack. With no pack, labels are named from mask values (PRJ-07) and phases are raw values.
3. **Project settings view** with tabs:
   - General: name, description, link, default modality;
   - Display:
     - layout;
     - initial W/L per modality, with the DICOM `WindowCenter/Width` first;
     - W/L presets;
     - interpolation;
     - radiological (default) or neurological convention;
   - Labels: label map, default segmentation set, import from 3D Slicer `.ctbl`, ITK-SNAP label descriptions or nnU-Net `dataset.json`;
   - Data;
   - Plugins.
4. **Concurrency.** Settings writes (API-03) require `If-Match: {etag}`; a stale write gets `412 conflict` and the UI offers reload + reapply. Other multi-user rules are unchanged: single writer, SSE, last-writer-wins with history (CUR-12).
5. **View-only link.**
   - `project.json.view_token` (random, rotatable) gives `/v/{token}`. The browser then talks only to read-only routes `/api/v1/view/{token}/…`, which mirror the GET endpoints and never reveal the `project_id`.
   - Writes are impossible on that path, and the UI hides every editing control.
   - The full link (PRJ-03) keeps today's behaviour. There are still no accounts (ADR-0004).
6. **Migration.** `format_version` 3: existing projects get `default_modality: CT`, `packs: [preset]` (e.g. `ccrcc`), a `display` block with the current defaults, and no `view_token` until one is created.

**Consequences.**
- \+ Creating a project is instant.
- \+ Study knowledge is reusable and optional.
- \+ There is a safe way to share for viewing only.
- − Another format migration.
- − The view routes mirror part of the API.
- Owner docs on acceptance: PROJECT_FORMAT (PRJ-12 → packs, PRJ-14.., v3), API (API-03 ETag, view routes, packs), UI_SHELL (New project, Project settings), VIEWER (display defaults), ANALYZERS (ANZ-05), CURATION (read-only in view mode), GLOSSARY.

**Rejected.**
- Keeping presets at creation: premature study assumptions.
- Accounts or roles for read-only access: ADR-0004.
