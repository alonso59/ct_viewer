# Non-Functional Requirements

Scope: measurable quality targets.
Read when: designing for performance, safety, privacy, or compatibility; writing TST-09.
Depends: none.

Design envelope: **500–3,000 cases per project**, ≈2–4 scans per case, ≤ 10k items.
Reference volume: abdominal CT 512×512×600 int16 `.nii.gz` (~180 MB compressed), local SSD, Chromium, integrated or better GPU.

| ID | Requirement | Pri | Target |
|---|---|---|---|
| NFR-01 | Open item → first slice visible (reference volume, local server) | M | < 3 s |
| NFR-02 | Slice scroll / W/L drag frame time (client-side) | M | ≥ 30 fps, target 60 |
| NFR-03 | Explorer with 10k items: filter + scroll | M | < 100 ms per interaction |
| NFR-04 | Index 1,000 items (headers + quick fingerprints) | M | < 60 s |
| NFR-05 | Mesh for one label (cached miss) | M | < 5 s |
| NFR-06 | Radiomics throughput reported per run; no UI blocking during runs | M | reported, not fixed |
| NFR-07 | Initial JS bundle | M | ≤ 300 KB gzip |
| NFR-08 | API process RSS at idle with 4 projects cached | M | ≤ 500 MB |
| NFR-09 | Browser memory with `VIEWER_MAX_LOADED=3` | M | ≤ 3 GB |
| NFR-10 | OCI image size | M | ≤ 1.5 GB |
| NFR-11 | `source` roots never modified (R1); `derived` writes only inside run folders or append-only datasets; verified by TST-07 | M | mandatory |
| NFR-12 | No telemetry, no external requests (R5), verified by E2E network allowlist | M | mandatory |
| NFR-13 | Browsers: Chromium ≥ 120, Firefox ≥ 120, Safari ≥ 17 (WebGL2 required) | M | must |
| NFR-14 | Every curation event is durable once acknowledged (flushed before HTTP 201) | M | mandatory |
| NFR-15 | Reproducibility: re-running the same profile on unchanged inputs gives identical features | M | bitwise, or ≤ 1e-9 relative |
| NFR-16 | Not a medical device; the UI shows "Research use only" in About | M | mandatory |
| NFR-17 | PHI: DICOM sidecars and tags stay in the derived root; never in bundles, exports, logs or E2E artifacts; optional `anonymize: basic` (DCM-05). Source paths (folder names are often patient names) never go into URLs (Open mode `/open/{sid}`, `POST /fs/list`), logs (alias refs instead) or default dataset names | M | mandatory |
| NFR-18 | Geometry fidelity: DICOM → NIfTI and NumPy → NIfTI keep world coordinates (voxel ↔ RAS mm) within 0.01 mm and never swap axes, verified by TST-13 | M | mandatory |
