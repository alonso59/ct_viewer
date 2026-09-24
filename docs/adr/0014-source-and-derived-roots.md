# ADR-0014 Source and derived roots
Status: Accepted · Date: 2026-09-24
Amends: AGENTS.md R1, ADR-0002, ADR-0005 (aliases gain a role), ADR-0007 (a third mount)

**Context.** Until now the app never created image data. The DICOM converter (volumes, sidecars) and segmentation tasks (masks) must write volumes somewhere. Writing next to source data breaks R1. Writing into the project folder makes projects huge and mixes study state with bulk data.

**Decision.**
1. **Every path root has a role.** `project.json.path_roots[].role` is `source` (default; all roots today) or `derived`.
2. **R1 becomes:** "Never write to `source` roots (images, masks, input metadata). App state lives in the project folder. Task outputs are written only into `derived` roots."
3. **The user chooses the derived folder** through the folder browser, limited to the new `ALLOWED_DERIVED_ROOTS`. It is alias `DERIVED` (renamable) and may be shared by several projects (user decision 2026-09-24).
4. **Layout** (under `{DERIVED}/{project_id}/{task_id}/`):
   - **Runs** go to `runs/{run_id}/`. Each is written by its task only and never modified once finished; a rerun is a new `run_id`.
   - **Accumulating datasets** go to `dataset/`, for incremental tasks such as the converter. They are append-only: new files are added and existing files are never rewritten.
   - **Open-mode exports** (SRC-14, owner addendum 2026-09-24) go to `{derived root}/_open/`, the only derived location outside a project; files there are written once and never modified.
5. **Deletion** happens only by an explicit, confirmed user action ("Delete run outputs"). Nothing is deleted automatically.
6. **Provenance.**
   - The project keeps `derived/runs.jsonl` (run, task, version, settings hash, outputs with sha256).
   - Items reference files as `DERIVED:rel/path`. Relink and verification apply unchanged (PRJ-05).
7. **Bundles** carry manifests and refs, never derived volumes or DICOM sidecars (PHI, NFR-17).
8. **Deployment.**
   - The container gets a third, writable, mirror-mounted mount (OPS-05), so paths match for the external runner (ADR-0016).
   - Startup refuses a derived root that overlaps a data root (like OPS-04).

**Consequences.**
- \+ R1 stays strict for sources.
- \+ Projects stay small and bundle-friendly.
- \+ Outputs can be opened in 3D Slicer.
- − One more mount and env var.
- − Derived data can go missing like source data (same relink path).
- Owners: PROJECT_FORMAT, DEPLOYMENT, NFR, DATA_MODEL.

**Rejected.**
- Derived data inside the project folder: size and bundles.
- Writing next to sources: R1.
- A managed blob store: ADR-0002, ADR-0005.
