# Docs Index (router)

Read only the files routed for your task. Each file declares its scope in its header.

## Task → files

| Task | Read |
|---|---|
| Understand the product / scope | `product/VISION.md` |
| Plan or pick next work | `product/ROADMAP.md` |
| Unknown term | `product/GLOSSARY.md` |
| Project folder, IDs, path aliases | `domain/PROJECT_FORMAT.md` |
| Importing `metadata.jsonl` / VOI catalog | `domain/INPUT_METADATA.md` |
| File formats, NIfTI/DICOM/NumPy sources, Open mode, case identity | `domain/SOURCES.md` |
| Tasks, plugins, runner, run protocol | `domain/TASKS.md` |
| DICOM → NIfTI converter | `domain/DICOM_CONVERTER.md` |
| Phase / organ / readiness analyzers, annotations | `domain/ANALYZERS.md` |
| Native phase selection (one-click, precedence, exports) | `domain/PHASE.md` |
| Plugin model, Plugin Library, catalog | `domain/PLUGINS.md` |
| Labeling table plugin | `domain/LABELING.md` |
| Entities and relations | `domain/DATA_MODEL.md` |
| Curation, QC status, correction queue | `domain/CURATION.md` |
| Radiomics extraction, settings, IBSI | `domain/RADIOMICS.md` |
| Study variables, types, group-by, derived vars | `domain/VARIABLES.md` |
| Statistics, test choice, recommendations | `domain/ANALYSIS.md` |
| Backend modules, jobs, concurrency | `backend/ARCHITECTURE.md` |
| HTTP endpoints / contracts | `backend/API.md` |
| Frontend structure, state, libraries | `frontend/ARCHITECTURE.md` |
| Shell layout (QuPath panes, VS Code shell, GitHub Dark, icons) | `frontend/UI_SHELL.md` |
| 2×2 viewer, NiiVue, overlays, W/L | `frontend/VIEWER.md` |
| Radiomics dashboard | `frontend/DASHBOARD.md` |
| Docker / udocker / env vars | `ops/DEPLOYMENT.md` |
| Local and remote dev loop | `ops/DEV_ENV.md` |
| Tests and fixtures | `ops/TESTING.md` |
| (Humans) multi-agent prompts per step | `ops/AGENT_RUNBOOK.md`; agents skip it |
| Performance, safety, privacy targets | `product/NFR.md` |
| Run or triage the quality audit | `audit/PLAN.md` → one `audit/findings/A*.md` |
| Why a decision was made | `adr/README.md` → one ADR |

## Ownership (one fact, one place)

| ID prefix | Owner file | Topic |
|---|---|---|
| `PRJ-` | domain/PROJECT_FORMAT.md | Projects, folders, aliases, sharing |
| `IMP-` | domain/INPUT_METADATA.md | Import and indexing |
| `SRC-` | domain/SOURCES.md | Formats, adapters, Open mode, identity |
| `TSK-` | domain/TASKS.md | Tasks, plugins, runtimes |
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
| `AUD-` | audit/PLAN.md, audit/findings/ | Audit findings |

## Doc conventions (keep tokens low)

- Header block: `Scope`, `Read when`, `Depends`. No intro prose.
- Target ≤ 200 lines per file. Split rather than grow.
- Tables and compact schemas over paragraphs. No duplicated examples.
- Requirements: `| ID | Requirement | Pri |`, where Pri is `M` (must), `S` (should) or `C` (could).
- Reference other docs by ID or path; never copy their content.
- `Open questions` section at the end of a file only while something is undecided; move answers to `Decisions`.
- `archive/` is frozen v2 history. Do not read or update it.
