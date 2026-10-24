# Docs Index (router)

For domain, product and ops facts. Code tasks start at the area map (`backend/AGENTS.md`, `frontend/AGENTS.md`, `plugins/AGENTS.md`). Read one file, and in a large file only the section you need (`grep -n '^#' <file>`). §Ownership names the file that owns each requirement prefix: change those facts only there.

## Routes (paths relative to `docs/`)

| Topic | Read |
|---|---|
| Product, scope, journeys (PRD) | `product/VISION.md` |
| Release scope, v3.0 gates (MVP) | `product/MVP.md` |
| All requirements, requirement grammar (SRS) | `product/SRS.md` (frame; `make docs-srs` for the table) |
| Plan or pick next work | `product/ROADMAP.md` |
| Performance, safety, privacy / PHI targets | `product/NFR.md` |
| Unknown term | `product/GLOSSARY.md` |
| Project folder, IDs, path aliases, sharing | `domain/PROJECT_FORMAT.md` |
| Importing `metadata.jsonl` / VOI catalog, QC codes | `domain/INPUT_METADATA.md` |
| File formats, NIfTI/DICOM/NumPy sources, Open mode, case identity | `domain/SOURCES.md` |
| Entities and relations | `domain/DATA_MODEL.md` |
| Tasks, run protocol, builtin and external runtimes | `domain/TASKS.md` |
| Plugin model, Plugin Library, catalog | `domain/PLUGINS.md` |
| nnU-Net segmentation generation, model profiles, multi-GPU inference | `domain/SEGMENTATION.md` |
| Local/server execution, future SLURM | `domain/SEGMENTATION_RUNTIMES.md`; `adr/0034-capability-based-segmentation-runtimes.md` |
| DICOM → NIfTI converter | `domain/DICOM_CONVERTER.md` |
| Phase / organ / readiness analyzers, annotations | `domain/ANALYZERS.md` |
| Native phase selection (one-click, precedence, exports) | `domain/PHASE.md` |
| Labeling tables | `domain/LABELING.md` |
| Curation, QC status, correction queue | `domain/CURATION.md` |
| Radiomics extraction, settings, IBSI | `domain/RADIOMICS.md` |
| Study variables, types, group-by, derived variables | `domain/VARIABLES.md` |
| Statistics, test choice, recommendations | `domain/ANALYSIS.md` |
| Backend internals: module layout, jobs, concurrency | `backend/ARCHITECTURE.md` |
| HTTP endpoints, contracts, error slugs | `backend/API.md` |
| Frontend internals: folder layout, state, routes, API layer | `frontend/ARCHITECTURE.md` |
| Shell layout, theme, icons, keybindings | `frontend/UI_SHELL.md` |
| 2×2 viewer, NiiVue, overlays, W/L | `frontend/VIEWER.md` |
| Radiomics dashboard | `frontend/DASHBOARD.md` |
| Docker / udocker / image / env vars | `ops/DEPLOYMENT.md` |
| Local and remote dev loop | `ops/DEV_ENV.md` |
| Test layers, fixtures, gates | `ops/TESTING.md` |
| Why a decision was made | `adr/README.md` → one ADR |
| Audit findings cited in code and commits (frozen, closed 2026-09-27) | `archive/v3/audit/` |

## Ownership (one fact, one place)

| ID prefix | Owner file | Topic |
|---|---|---|
| `PRJ-` | domain/PROJECT_FORMAT.md | Projects, folders, aliases, sharing |
| `IMP-` | domain/INPUT_METADATA.md | Import and indexing |
| `SRC-` | domain/SOURCES.md | Formats, adapters, Open mode, identity |
| `TSK-` | domain/TASKS.md | Tasks, plugins, runtimes |
| `SEG-` | domain/SEGMENTATION.md | nnU-Net segmentation generation |
| `DCM-` | domain/DICOM_CONVERTER.md | DICOM conversion |
| `ANZ-` | domain/ANALYZERS.md | Metadata analyzers |
| `PHS-` | domain/PHASE.md | Native phase selection |
| `PLG-` | domain/PLUGINS.md | Plugins |
| `LBL-` | domain/LABELING.md | Labeling tables |
| `CUR-` | domain/CURATION.md | Curation workflow |
| `RAD-` | domain/RADIOMICS.md | Radiomics engine |
| `VAR-` | domain/VARIABLES.md | Study variables |
| `ANA-`, `REC-` | domain/ANALYSIS.md | Guided statistics |
| `API-` | backend/API.md | Endpoints |
| `BE-` | backend/ARCHITECTURE.md | Backend internals |
| `FE-` | frontend/ARCHITECTURE.md | Frontend internals |
| `UI-` | frontend/UI_SHELL.md | Shell and UX |
| `VW-` | frontend/VIEWER.md | Viewer |
| `DB-` | frontend/DASHBOARD.md | Dashboard |
| `OPS-` | ops/DEPLOYMENT.md | Runtime and deployment |
| `NFR-` | product/NFR.md | Quality targets |
| `TST-` | ops/TESTING.md | Test layers |
| `G1`..`G4` | product/VISION.md | Journeys (golden paths) |
| `REL-` | product/MVP.md | Release gates |
| `AUD-` | archive/v3/audit/ (frozen: v3 audit closed 2026-09-27) | Audit findings cited in code and commits |

## Active plans

Read only for the named work. At phase exit, move durable facts into the owning doc above, then move the plan to `archive/`.

| Work | Read |
|---|---|
| Supervised segmentation jobs (P7g): approved plan, GPU safety, acceptance matrix | `domain/SEGMENTATION_JOB_PLAN.md`; `ops/SEGMENTATION_JOB_TEST_PLAN.md`; `adr/0033-supervised-segmentation-jobs.md` |
| DICOM discovery, background conversion, interruption/resume | `domain/DICOM_JOB_PLAN.md`; `ops/DICOM_JOB_TEST_PLAN.md`; `adr/0035-durable-dicom-source-operations.md` |

## Not for agents

Editing docs: `CONVENTIONS.md`. Humans only: `ops/AGENT_RUNBOOK.md` (multi-agent prompts), `SITE.md` and `_sphinx/` (docs site, `make docs`). `archive/` is frozen history: read it only when the task says so.
