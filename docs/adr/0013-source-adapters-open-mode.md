# ADR-0013 Source adapters with one internal contract; Open mode; identity policy
Status: Accepted · Date: 2026-09-24

**Amended by ADR-0024.** Open mode shows every opened file as an image; a segmentation only by attach (NIfTI, same geometry). nnU-Net naming is not a `nifti-files` default.
**ADR-0027 (Proposed)** supersedes where an attachment may come from: anywhere under ALLOWED_DATA_ROOTS, not only the opened folder.
Amends: IMP-02 (INPUT_METADATA.md), the `case_id` pattern of contract v1, VISION §Out of scope (DICOM)

**Context.** Import accepts only contract v1 (`metadata.jsonl` from the v2 converter). A plain NIfTI folder, one NIfTI or DICOM file, or one segmentation fails with an empty "Validation failed". Users also want to look at a single file without creating a study. Case numbering lives inside the external converter, although other sources need it too (nnU-Net asks for `{case}_0000.nii.gz`).

**Decision.**
1. **Contract v1 stays the only internal form.** Everything after import reads normalized `Item`s. A `SourceAdapter` (`detect → preview → materialize`) turns a source into v1 rows. The rows are snapshotted in `sources/{import_id}/` together with `source.json` (adapter, version, options). Adapters: `metadata-v1` (today) and `nifti-files` (a folder or one file). DICOM enters through the converter task (ADR-0017), which emits v1 rows (SRC-*).
2. **Only compatible formats are accepted:**
   - NIfTI `.nii` / `.nii.gz`, as images or label maps;
   - DICOM, as a series folder or a single file;
   - NumPy `.npy`, read-only and only with explicit geometry and axis order (SRC §NumPy), until the future VOI work.

   Anything else is refused with a reason.
3. **Open mode.** One file or folder of any accepted kind (image, segmentation, DICOM) opens in the viewer without a project.
   - Nothing is written to a project, and DICOM/NumPy are converted to NIfTI in the disposable `WORKSPACE_ROOT/.scratch/`.
   - A segmentation can be attached to an open image if the geometry matches. There is no resampling.
   - "Create project from this" pre-fills the import wizard.
4. **Identity policy** (shared by the adapters and the converter):
   - strategies `dicom_patient_id` (sequential), `filename_pattern` and `table`;
   - a template (default `case_{n:05d}`);
   - a persistent registry `sources/identity.json`, so incremental imports never renumber.

   `case_id` is a URL-safe slug (`[A-Za-z0-9_-]+`); `case_\d{5}` is only the default template.

   nnU-Net names are produced when a task stages its inputs, never required on disk.
5. **Errors always state the cause and a next action** (e.g. "no `metadata.jsonl`; 11 NIfTI files → import as NIfTI files").

**Consequences.**
- \+ Any compatible file can be seen in two clicks.
- \+ The core pipeline and existing projects are untouched.
- − More adapters to test.
- − Slug `case_id`s widen what code may assume.
- Owners: SOURCES.md (SRC-*), INPUT_METADATA, VIEWER, UI_SHELL, API.

**Rejected.**
- A second internal contract per source.
- Phase from folder names.
- A hidden scratch project for Open mode (pollutes the registry).
- Guessing NumPy axis order silently.
