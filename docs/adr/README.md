# Architecture Decision Records

Read only the ADR you need. To change a decision, add a new ADR with `Supersedes: ADR-XXXX` and set the old one to `Superseded`.

Template: `Status · Date · Context · Decision · Consequences · Rejected alternatives` (≤ 40 lines).

| ADR | Title | Status |
|---|---|---|
| 0001 | Web app first; Electron as a thin shell later | Accepted |
| 0002 | Project-folder storage; no database server | Accepted (amended by 0014) |
| 0003 | Client-side rendering with NiiVue | Accepted |
| 0004 | No accounts; link sharing; reviewer name stamp | Accepted (amended by 0019) |
| 0005 | Register data in place with path aliases | Accepted (amended by 0014) |
| 0006 | Radiomics via engine adapter; PyRadiomics default; IBSI reference hidden from the GUI | Accepted (spike passed; pinned upstream commit; amended by 0016) |
| 0007 | One OCI image for Docker and udocker | Accepted (amended by 0014, 0016) |
| 0008 | Drop MUI; Radix + tokens + codicons + dockview | Accepted |
| 0009 | Analytics on Parquet + DuckDB; ECharts for charts | Accepted |
| 0010 | QuPath-style layout in a VS Code shell, GitHub Dark theme | Accepted |
| 0011 | Study-agnostic variable catalog | Accepted (extended by 0019) |
| 0012 | Simple guided statistics in-app (supersedes QC-only dashboard) | Accepted |
| 0013 | Source adapters with one internal contract; Open mode; identity policy | Accepted (§3 attach location superseded by 0027, proposed) |
| 0014 | Source and derived roots (amends R1) | Accepted (amended by 0021) |
| 0015 | Segmentation sets per item | Accepted |
| 0016 | Tasks and plugins: one contract, builtin and external runtimes | Accepted (amended by 0018) |
| 0017 | DICOM converter as a task; metadata analyzers as separate, composable tasks | Accepted (amended by 0020) |
| 0018 | First-party plugin platform and Plugin Library | Accepted |
| 0019 | Neutral projects, study packs, view-only links | Accepted |
| 0020 | `metadata.jsonl` belongs to the converter; plugin data lives in layers | Accepted (amended by 0026) |
| 0021 | CT tools without a project; workspace tasks; the converter overlay | Accepted |
| 0022 | Shared event store; Curation & QC and Labeling table as plugins | Accepted (amended by 0026) |
| 0023 | Decouple literal VS Code/GitHub signals from the shell's visual identity | Accepted |
| 0024 | Open mode shows images only (segmentations by attach); nnU-Net naming moves to the nnU-Net plugin | Accepted (amended by 0027, proposed) |
| 0025 | A JSONL whole-project export; reconstructed sidecars for `metadata-v1` imports | Accepted (amended by 0026) |
| 0026 | Phase selection is native to the app, not a curation decision | Accepted |
| 0027 | Open mode: attach a segmentation from anywhere under the shared folders; it travels into the import | Proposed |
