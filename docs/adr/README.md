# Architecture Decision Records

Read only the ADR you need. To change a decision, add a new ADR with `Supersedes: ADR-XXXX` and set the old one to `Superseded`.

Template: `Status · Date · Context · Decision · Consequences · Rejected alternatives` (≤ 40 lines).

| ADR | Title | Status |
|---|---|---|
| 0001 | Web app first; Electron as a thin shell later | Accepted (amended by 0054) |
| 0002 | Project-folder storage; no database server | Accepted (amended by 0014) |
| 0003 | Client-side rendering with NiiVue | Accepted |
| 0004 | No accounts; link sharing; reviewer name stamp | Accepted (amended by 0019) |
| 0005 | Register data in place with path aliases | Accepted (amended by 0014) |
| 0006 | Radiomics via engine adapter; PyRadiomics default; IBSI reference hidden from the GUI | Accepted (spike passed; pinned upstream commit; amended by 0016) |
| 0007 | One OCI image for Docker and udocker | Superseded by 0051 |
| 0008 | Drop MUI; Radix + tokens + codicons + dockview | Accepted |
| 0009 | Analytics on Parquet + DuckDB; ECharts for charts | Accepted |
| 0010 | QuPath-style layout in a VS Code shell, GitHub Dark theme | Accepted |
| 0011 | Study-agnostic variable catalog | Accepted (extended by 0019; external table superseded by 0046) |
| 0012 | Simple guided statistics in-app (supersedes QC-only dashboard) | Accepted |
| 0013 | Source adapters with one internal contract; Open mode; identity policy | Accepted (§3 attach location superseded by 0027) |
| 0014 | Source and derived roots (amends R1) | Accepted (amended by 0021; partially superseded by 0029) |
| 0015 | Segmentation sets per item | Accepted |
| 0016 | Tasks and plugins: one contract, builtin and external runtimes | Accepted (amended by 0018; DICOM execution in §3 partially superseded by 0035) |
| 0017 | DICOM converter as a task; metadata analyzers as separate, composable tasks | Accepted (amended by 0020, 0026) |
| 0018 | First-party plugin platform and Plugin Library | Accepted |
| 0019 | Neutral projects, study packs, view-only links | Accepted |
| 0020 | `metadata.jsonl` belongs to the converter; plugin data lives in layers | Accepted (amended by 0026) |
| 0021 | CT tools without a project; workspace tasks; the converter overlay | Accepted (write-once clause partially superseded by 0029) |
| 0022 | Shared event store; Curation & QC and Labeling table as plugins | Accepted (amended by 0026) |
| 0023 | Decouple literal VS Code/GitHub signals from the shell's visual identity | Accepted (scope clause on title-bar toggles and the active indicator superseded by 0028) |
| 0024 | Open mode shows images only (segmentations by attach); nnU-Net naming moves to the nnU-Net plugin | Accepted (amended by 0027) |
| 0025 | A JSONL whole-project export; reconstructed sidecars for `metadata-v1` imports | Accepted (amended by 0026) |
| 0026 | Phase selection is native to the app, not a curation decision | Accepted (Explorer editing clause superseded by 0031) |
| 0027 | Open mode: attach a segmentation from anywhere under the shared folders; it travels into the import | Accepted |
| 0028 | One "Layout" menu in the title bar; a neutral active indicator | Accepted |
| 0029 | Explicit scan recycling with full audit metadata | Accepted (partially supersedes 0014 and 0021 for CUR-16) |
| 0030 | Dataset-local projects with a lightweight global workspace | Accepted (partially supersedes 0002 and 0014) |
| 0031 | Explorer phases are read-only indicators | Accepted (partially supersedes 0026) |
| 0032 | nnU-Net v2 inference as a partitioned external segmentation task | Superseded by 0033 |
| 0033 | Supervised segmentation jobs and approved GPU allocation | Superseded by 0034 |
| 0034 | Capability-based segmentation runtimes without administrator access | Accepted (§5 admission criterion superseded by 0039) |
| 0035 | Durable DICOM source operations and verified resume | Accepted (§5 whole-run input pin superseded by 0042) |
| 0036 | Folder-per-case import, mask path templates and mask sets | Accepted (partially supersedes 0027 §3) |
| 0037 | Manual segmentation import and soft removal | Accepted (§5 management location superseded by 0038) |
| 0038 | Individual segmentation label removal and management panel | Accepted (extends 0015/0036; supersedes 0037 §5 management location) |
| 0039 | GPU admission by available memory | Accepted (partially supersedes 0034) |
| 0040 | Batched DICOM source operations | Accepted (extends 0035) |
| 0041 | CTFlow: a domain command console over the existing task services | Accepted |
| 0042 | Standalone DICOM converter package with per-unit input pinning | Accepted (supersedes 0035 §5 whole-run input pin) |
| 0043 | Three deployment options: native, container, HPC | Accepted (supersedes 0007's rejection of native installs) |
| 0044 | Projectless conversions write to a destination folder the user chooses | Accepted (partially supersedes 0002/0014 for that folder) |
| 0045 | Cohort dashboard: read-only imaging metadata by category; editable data in separate sections | Accepted (amended by 0046) |
| 0046 | Clinical data and label tables are edited in Cohort, on the labeling engine | Accepted (partially supersedes 0011 for external tables) |
| 0047 | DICOM conversion runs outside the host allocation pool (interim, to be redesigned) | Accepted (partially supersedes 0035) |
| 0048 | Agent interface over CTFlow: MCP client, agent origin, zones | Accepted (extends 0041) |
| 0049 | Timeline events are label table rows at an `event` level, dated in days from an anchor | Accepted (extends 0046) |
| 0050 | The VOI extractor takes sides from patient coordinates and previews boxes before cropping | Accepted (extends 0014, 0016) |
| 0051 | Native conda is the only production deployment; the image is for tests and local Docker; udocker is removed | Accepted (supersedes 0007; partially supersedes 0043) |
| 0052 | Source operations: one record owner, flows in their own modules | Accepted (extends 0035) |
| 0053 | SLURM v2: several jobs at once, job arrays and a sandbox on compute nodes | Proposed (extends 0034) |
| 0054 | Electron: which backend the desktop app starts on each operating system | Accepted (amends 0001) |
