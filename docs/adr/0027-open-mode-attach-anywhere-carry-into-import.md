# ADR-0027 Open mode: attach a segmentation from anywhere under the shared folders; it travels into the import
Status: Accepted (owner 2026-09-27) · Date: 2026-09-26
Supersedes: ADR-0013 §3 and SRC-10 / SOURCES §Open mode on *where* an attached segmentation may come from ("inside the opened folder")
Amends: ADR-0024 §2 (the import wizard may pre-fill the converter's own naming)

**Context.** Attach (SRC-10) accepted a segmentation only from inside the opened folder. With one opened file the folder is the file's parent (`nifti/`, `imagesTr/`), so the usual layouts (`nifti/` + `seg/`, nnU-Net `imagesTr/` + `labelsTr/`) were refused with "Validation failed" and a non-clickable "Open the folder instead" that opened the wrong folder (AUD-A2-03). The mask attached in Open mode was then dropped by "Create project from this", and a single converter-named file (`01_case_00030_0000`) became case `01_case_00030_0000` with two noise warnings (AUD-A2-12). The folder rule protected nothing: the path guard (ALLOWED_DATA_ROOTS) and the geometry check decide whether a file may be read and shown.

**Decision (owner 2026-09-25 for 1; 2–3 follow the finding's proposal).**
1. **Attach from anywhere under ALLOWED_DATA_ROOTS** (read-only, R1). The geometry check stays the guard: same shape, affines within the IMP-08 tolerance, never resampled; a mismatch shows both geometries. An attachment outside the session root keeps its absolute path in the session (memory only) and every read is guarded again. The attach browser starts in a `seg*/labels*/masks*` folder inside or next to the opened one.
2. **The attachment travels.** "Create project from this" and "Add to project…" with an attached mask import from the folder holding both files: `nifti-files` with an `include` list and the explicit `masks` pair (image → mask), so the mask becomes the item's segmentation. Nothing is guessed from names.
3. **The converter's own naming is recognised in the wizard.** When every image name being imported follows the converter's output naming `{scan_idx}_[{MOD}_]{case_id}_{channel}` (DICOM_CONVERTER, kept by ADR-0024 §3), the Detect step pre-fills that `pattern`, visibly and editably, with a note; the user can clear it (one case per stem). The adapter default stays one case per stem; `imagesTr/`/`labelsTr/` remain unspecial.

**Consequences.**
- \+ G1 works for the layouts users actually have, in one dialog; the Open-mode choice is not lost on import.
- \+ No new read surface: the same guard as Open, detect and import.
- − An Open session may reference a file outside its root (absolute path in memory; never in the URL, NFR-17).
- − Importing a single file with its mask uses the common parent as the alias root (broader than the file's folder).
- − A pre-filled pattern is a default the user must notice; the note and the editable field are the mitigation.

**Rejected.**
- "Open {common parent} with this mask attached": two sessions, a folder of hundreds of files for one image.
- Accepting masks only from sibling folders named `seg`/`labels*`: a naming rule where the geometry check already decides.
- Making the converter pattern the `nifti-files` default: reintroduces hidden naming defaults (ADR-0024 §2).
