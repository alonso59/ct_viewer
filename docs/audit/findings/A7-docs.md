# A7 · Documentation structure

Scope: findings of audit A7 (PLAN.md §A7): doc inventory, Sphinx + MyST trial build, classification, and the proposal for a publishable structure with PRD, SRS and MVP that keeps the agent router intact.
Read when: approving the docs target tree, or running the docs restructure batch.
Depends: audit/PLAN.md (§A7 owner decisions), INDEX.md (routing, ownership, conventions), AUD-A4-* (doc hygiene already reported, not repeated), AGENTS.md.

Run 2026-09-26 on `version_3-dev` @ `b08a5c3`, static plus a trial build in the session scratchpad (`a7/`: `inv.py`, `srs_proto.py`, `srcB/` with `_sphinx/conf.py`, never in the repo). Sphinx 9.1.0, myst-parser 5.1.0, furo 2025.12.19 via `uvx`. No repo file changed except this one.

## Summary

| Measure | Value |
|---|---|
| Files audited | 64 `.md` in `docs/` (excluding `archive/`: 3 frozen v2 files, not read) + `README.md`, `AGENTS.md`, `LANE_NOTES.md`; 29 PNG (audit screenshots, brand logo) |
| Structure | Every file has exactly one H1 and no heading-level jumps. No orphans: every file is routed by INDEX, `adr/README.md` or `audit/PLAN.md`. Only 4 Markdown links exist in the whole set, all in `README.md`; docs cite each other by backtick path, ID or `§Heading` (AUD-A7-05) |
| Over 200 lines | `ops/AGENT_RUNBOOK.md` 417 (AUD-A4-17), `LANE_NOTES.md` 748 (append-only log, root). Close to the cap: `product/ROADMAP.md` 187, `domain/PROJECT_FORMAT.md` 184 |
| Trial build, as is | `sphinx-build -W --keep-going`: **72 warnings**: 63 `toc.not_included` (no toctree), 9 `misc.highlighting_failure` (`jsonc` code fences). 0 broken links, 0 missing anchors, 0 duplicate labels, 0 heading warnings, 0 image warnings |
| Trial build, with the proposed `docs/SITE.md` + `docs/_sphinx/conf.py` | **0 warnings**, `-W` passes; site 6.6 MB; no CDN or font fetches (only theme attribution `href`s, never loaded) |
| Silent render defects (no warning) | 2 rows lose their Pri cell (AUD-A7-01), 9 API rows are not a table (AUD-A7-02), `linkify` would add ≈ 78 bogus `http://X.md` links (AUD-A7-05) |
| Requirement rows (prototype parser) | 367 ID rows in 21 owner docs, 366 unique (RAD-13 twice, AUD-A4-06). Pri: M 200 · S 54 · C 4 · non-standard 8 (AUD-A7-03) · none 101 (API, TST and NFR tables) |

## Inventory

| Group | Files | Lines (max) | Header block | IDs owned | Inbound | Notes |
|---|---|---|---|---|---|---|
| Root | `README.md`, `AGENTS.md`, `LANE_NOTES.md` | 48 · 39 · 748 | none (router / landing / log) | R1..R9 (AGENTS) | README ← GitHub; LANE_NOTES ← ROADMAP ×17, DICOM_CONVERTER, runbook, A0 | not in `docs/`, cannot be in the site as is |
| `INDEX.md` | 1 | 75 | none (router) | ownership table | AGENTS, README, 5 docs | agents' entry; clashes with Sphinx `index` on macOS (§Root doc) |
| `product/` | VISION, NFR, GLOSSARY, ROADMAP | 73 · 29 · 55 · 187 | SRD; GLOSSARY SR only (A4-17) | NFR 18 | INDEX + 1–4 docs each | no PRD/SRS/MVP yet |
| `domain/` | 14 | 184 (PROJECT_FORMAT) | SRD all | PRJ IMP SRC TSK DCM ANZ PHS PLG LBL CUR RAD VAR ANA (REC none) | INDEX + 4–12 each | DATA_MODEL owns no IDs (entities) |
| `backend/` | API, ARCHITECTURE | 130 · 81 | SRD | API 64, BE 15 | INDEX + 3–7 | API table split (A7-02) |
| `frontend/` | ARCHITECTURE, UI_SHELL, VIEWER, DASHBOARD | 172 (UI_SHELL) | SRD | FE 11, UI 26, VW 26, DB 9 | INDEX + 4–8 | |
| `ops/` | DEPLOYMENT, DEV_ENV, TESTING, AGENT_RUNBOOK | 95 · 41 · 68 · 417 | SRD | OPS 14, TST 20 (no ownership row, A4-17) | INDEX + 3–7 | runbook is process, 80 % done steps |
| `adr/` | README + 26 ADRs | 10–51 | ADR template (`Status · Date · Amends`), not SRD (A7-09) | ADR-nnnn | README ← INDEX; ADRs by ID only | |
| `audit/` | PLAN + 7 findings + `img/` 28 PNG | 112 (PLAN) | SRD | AUD, and G1..G4 (A7-07) | INDEX → PLAN → findings | screenshots cited as paths, not embedded |
| `brand/` | `logo-master.png` | — | — | — | `frontend/src/theme/BrandMark.tsx` | reuse as `html_logo` |
| `archive/v2/` | 3 | — | — | — | never read | excluded from build |

## Findings

| ID | Sev | Path | Finding | Evidence | Proposal | Refs | Effort | Decision |
|---|---|---|---|---|---|---|---|---|
| AUD-A7-01 | P2 | — | Two requirement rows have an unescaped `\|` inside a code span, which GFM treats as a cell break: CUR-15 and PHS-08 render with Pri = "scan_idx\`." and their real Pri (M) is dropped. Any table parser (SRS, `trace.py`) misreads them the same way. | `domain/CURATION.md:30`, `domain/PHASE.md:20` (`` `case_id|scan_idx` ``); built `domain/CURATION.html` row CUR-15; `a7/srs_proto.py` Pri column | Write `case_id\|scan_idx`. The SRS parser fails when a row's cell count ≠ header's | CUR-15, PHS-08 | S | |
| AUD-A7-02 | P2 | — | A blank line splits the API table: API-56..64 (9 rows) render as one paragraph of pipes, not a table, and lose the header. | `backend/API.md:74` (blank between API-55 and API-56); built `backend/API.html` | Remove the blank line (sort rows with A4-06). Parser fails on ID rows that follow a blank line without a header | API-56..64 | S | |
| AUD-A7-03 | P2 | — | Pri holds values outside `M/S/C`: `C (v3.1)` (VW-18, ANA-10, RAD-13), `C (later)` (PLG-10), `—` (PRJ-12 superseded, ANA-11 out of scope). Release targeting is mixed into priority, so neither the SRS nor the MVP cut can be computed. | `a7/srs_proto.py` "odd pri"; INDEX §Doc conventions (M/S/C only) | Pri ∈ `M`,`S`,`C`,`—`; `—` = not a requirement (retired or out of scope, text says which, AUD-A4-06 retired rows). Release target lives only in MVP §After v3.0. ANA-11 → VISION §Out of scope | INDEX conventions, A4-06 | S | |
| AUD-A7-04 | P2 | — | The three ID tables without Pri mean different things: NFR (`Requirement \| Target`, targets mix "mandatory", "must" and numbers), API (interfaces, `Ref`), TST (`Layer \| Tooling \| Covers`, verification methods, not requirements). An SRS that treats them alike would be wrong; NFR-07 (a release gate) has no priority at all. | `product/NFR.md:10`, `backend/API.md`, `ops/TESTING.md` headers | NFR gets a `Pri` column (Target stays). SRS: API → §3.1 interfaces, NFR → §3.3 quality, TST → §4 verification only | NFR-*, API-*, TST-* | S | |
| AUD-A7-05 | P2 | — | The published site would have no links between pages: 4 Markdown links in the set (all in README); docs cite by `path.md`, ID and `§Heading`, which is right for agents but inert in HTML. Enabling MyST `linkify` makes it worse: bare `PHASE.md` becomes `http://PHASE.md` (`.md` is a TLD), ≈ 78 bogus external links. | `a7/inv.py` (`md links 4`); `grep -o 'href="http://[A-Z_]*.md"' a7/_bB` | No `linkify`. The docs extension (§SRS generator) adds a read-only transform: `XXX-nn` → its SRS row anchor, `` `dir/FILE.md` `` → that page. Sources stay as they are, so agent tokens do not change | R5, R8 | M | |
| AUD-A7-06 | P2 | — | No build config, no root document, no toctree (63 `toc.not_included`), and `docs/index.md` cannot coexist with `docs/INDEX.md` on case-insensitive macOS. | trial build `a7/warn.txt` | `docs/SITE.md` as `root_doc` with captioned toctrees, config in `docs/_sphinx/` (`-c`), redirect `index.html` → `SITE.html`; verified 0 warnings with `-W` (§Root doc) | PLAN §A7 | S | |
| AUD-A7-07 | P2 | — | The golden paths G1..G4, the basis of the MVP and of TST-05 coverage, are defined only in a process doc (`audit/PLAN.md`); VISION has no goals, success metrics, journeys, assumptions or risks. The PRD and MVP cannot cite an audit plan as owner. | `audit/PLAN.md:25-32`; `product/VISION.md` sections | Move the G1..G4 table to VISION §Journeys (owner); PLAN keeps a one-line reference; ownership row `G1..G4 → product/VISION.md` (§PRD) | R8 | S | |
| AUD-A7-08 | P2 | — | No release definition exists: ROADMAP has phase exits but no v3.0 criterion; "v3.0" appears only as the version in VISION. With 36 open P1 findings, the release gate cannot be evaluated. | `product/ROADMAP.md:8,129`; `product/VISION.md:16`; §MVP counts | New `product/MVP.md` (§MVP) owning release gates `REL-nn` | PLAN §A7 | M | |
| AUD-A7-09 | P2 | — | INDEX says every file has a `Scope / Read when / Depends` header, but ADRs follow their own template and the routers (AGENTS, INDEX, `adr/README`) and README have none. The rule is right in practice and wrong as written. | `docs/INDEX.md:69`; `adr/0001-*.md:2`; `a7/inv.py` hb column | INDEX conventions: "ADRs use the ADR template (`adr/README.md`); routers and root files have no header block". No file changes | INDEX conventions | S | |
| AUD-A7-10 | P2 | — | Process material sits among product/ops docs and will be published by default: `ops/AGENT_RUNBOOK.md` (417 lines; Steps 0–3b, P7b, P7c, addendum are done, ≈ 330 lines) and `audit/**` (transient; screenshots cited as paths are not copied into the site). | `ops/AGENT_RUNBOOK.md` headings 58–392; `audit/findings/img/` | Runbook: keep lane rules + Step 4 + Step 5 at the same path (< 100 lines); move done steps to `archive/v3/AGENT_RUNBOOK-done.md` (archive = frozen history, never read). Exclude `INDEX`, runbook, `audit/**`, `archive/**` from the site (refines the A4-17 split) | AUD-A4-17 | S | |
| AUD-A7-11 | P2 | — | ROADMAP is at 187 / 200 lines and grows with done-phase detail that repeats LANE_NOTES (P7b/P7c waves), plus §Lanes (process). A release section would push it over the cap. | `product/ROADMAP.md:31-52,131-172` | Release cut lives in MVP.md, not ROADMAP. Collapse done phases to one line each + LANE_NOTES heading; move §Lanes to the runbook | R8, INDEX conventions | S | |
| AUD-A7-12 | P2 | — | The findings' `Decision` column is free text and stale: AUD-A2-01 still reads "accept P0" although `e858eab` closed it, so "no open P0/P1" (MVP gate) is not computable. | `audit/findings/A2-workflows.md` row A2-01; `git show e858eab` subject | Fixed vocabulary: `accept · defer · reject · fixed <date> <sha>` (+ free note); `make docs-srs` also counts open P0/P1 for MVP REL-03 | PLAN §Triage | S | |

## Owner decisions (2026-09-26)

All eleven recommendations accepted: root `docs/SITE.md` + `docs/_sphinx/` (INDEX.md unchanged for agents); `product/VISION.md` keeps its name and grows into the PRD with G1..G4 in §Journeys (PLAN.md references them); the SRS table is generated at build time and never committed (`make docs-srs` writes a git-ignored review file) and the requirement check joins `make check`; not published: INDEX, AGENT_RUNBOOK, `audit/**`, `archive/**`, root files; the runbook keeps lane rules + Steps 4–5 and moves finished steps to `archive/v3/` (archive = frozen history); Pri = `M`/`S`/`C` or `—`, release targets move to MVP.md, NFR gets a Pri column; Decision column vocabulary `accept · defer · reject · fixed <date> <sha>`; MVP = all M requirements unless MVP.md defers one, VOI / nnU-Net / Electron after v3.0; theme furo, versions pinned in the Makefile, nothing added to `pyproject.toml`, `package.json` or the image.

## Proposal

### Target tree (minimal moves: 3 new files, 1 split, 0 renames)

| Path | Class | Site | Change |
|---|---|---|---|
| `docs/SITE.md` | site root | root | **new**: 1-line purpose + captioned toctrees; agents skip |
| `docs/_sphinx/` `conf.py`, `reqs.py`, `_templates/redirect.html` | build | — | **new**, dev-only (R5: never in the image) |
| `docs/INDEX.md` | router | excluded | +3 routes, +2 ownership rows, +2 convention lines (§Migration) |
| `product/VISION.md` | product · PRD | Product | grows into the PRD (§PRD); name kept |
| `product/MVP.md` | product | Product | **new** (§MVP); owns `REL-` |
| `product/SRS.md` | requirements | Requirements | **new** frame; table generated at build (§SRS) |
| `product/NFR.md`, `GLOSSARY.md`, `ROADMAP.md` | product | Product | NFR + Pri column; ROADMAP trimmed (A7-11) |
| `domain/*`, `backend/*`, `frontend/*` | design | Design (Domain / Backend / Frontend) | unchanged (fixes A7-01/02/03 only) |
| `ops/DEPLOYMENT.md`, `DEV_ENV.md`, `TESTING.md` | operations | Operations | unchanged |
| `ops/AGENT_RUNBOOK.md` | process | excluded | active steps only (A7-10) |
| `adr/*` | decisions | Decisions | unchanged |
| `audit/**` | process | excluded | unchanged |
| `archive/v2/`, `archive/v3/AGENT_RUNBOOK-done.md` | archive | excluded | v3 part **new** (moved text) |
| `README.md`, `AGENTS.md`, `LANE_NOTES.md` (root) | landing · router · log | not in site | README +1 line (`make docs`) |

Site toctree order: **Product** (VISION, MVP, NFR, GLOSSARY, ROADMAP) · **Requirements** (SRS) · **Design** (domain, backend, frontend) · **Operations** · **Decisions**. Classification lives in the toctree captions, not in folders, so no path moves.

### Root-doc solution

| Option | Agent cost | Verdict |
|---|---|---|
| A · `root_doc = "INDEX"` + hidden toctree in INDEX | +15 lines on every agent read; the site home is the agent router | reject |
| B · `docs/SITE.md` root, config in `docs/_sphinx/` (`sphinx-build -c docs/_sphinx docs build/docs`), `html_additional_pages = {"index": "redirect.html"}` | 0 on AGENTS read order; INDEX +1 convention line | **recommended**; verified 0 warnings |
| C · rename INDEX to e.g. `ROUTER.md` and add `index.md` | breaks AGENTS read order, habits, 7 inbound refs | reject |

`conf.py` essentials: `extensions = ["myst_parser", "reqs"]`, `myst_enable_extensions = ["colon_fence", "deflist"]` (no `linkify`), `root_doc = "SITE"`, `exclude_patterns = ["archive/**", "audit/**", "_sphinx/**", "INDEX.md", "ops/AGENT_RUNBOOK.md"]`, `jsonc` mapped to the JSON lexer, `html_theme = "furo"`, `html_logo = "../brand/logo-master.png"`, `html_show_sphinx = False`. INDEX convention line: "`SITE.md` and `_sphinx/` build the published site; agents skip them."

### SRS generator spec (design only)

| Aspect | Rule |
|---|---|
| Code | One stdlib module `docs/_sphinx/reqs.py`: parser + Sphinx directive + CLI. `make trace` (AUD-A4-01, accepted) imports the same parser, so one table grammar exists |
| Sources | `docs/**/*.md` except `archive/`, `audit/`, `adr/`; code fences skipped |
| Row | Table whose header starts with `ID`; row whose first cell matches `^[A-Z]{2,4}-\d{2}$`; cells split on unescaped `\|` |
| Kinds (by header) | `ID \| Requirement \| Pri` → functional / constraint · `ID \| Requirement \| Pri \| Target` (NFR after A7-04) → quality · `ID \| Method & path \| Purpose \| Ref` → interface · `ID \| Layer \| Tooling \| Covers` → verification. Other ID tables ignored |
| Grouping and order | By owner file, in INDEX ownership-table order; group heading = the ownership `Topic` (one fact, one place). SRS §3.1 interfaces (API), §3.2 functions (PRJ … DB), §3.3 quality (NFR), §3.4 constraints (BE, FE, OPS + AGENTS R1..R9 by reference), §4 verification (TST) |
| Columns | ID (anchor `req-cur-15`) · Requirement (owner cell, rendered inline) · Pri · Owner (link) · MVP (✓ when the ID is behind a journey in MVP.md) · Verified by (count of test files citing the ID, A4-01; `—` while untagged) |
| Errors (exit 1, build fails) | duplicate ID (RAD-13, A4-06) · prefix not in ownership table, or defined outside its owner file · cell count ≠ header (A7-01) · ID rows after a blank line with no header (A7-02) · Pri ∉ {M,S,C,—} (A7-03) |
| Warnings | ID cited but never defined (CUR-06 today, A4-07); `adr/` and `archive/` exempt |
| Output | Build time only: ```` ```{srs-table} ```` directives in `product/SRS.md`; the table is **never committed** (R8). `make docs-srs` runs the CLI without Sphinx: validates, writes git-ignored `build/docs/srs.csv` + `srs.md` + counts (Pri, MVP, open P0/P1 from findings) |
| Make | `DOCS = uvx --from sphinx==9.1.0 --with myst-parser==5.1.0 --with furo==2025.12.19`; `make docs` = `$(DOCS) sphinx-build -W --keep-going -b html -c docs/_sphinx docs build/docs`; `make docs-srs` = `python3 docs/_sphinx/reqs.py`. Nothing in `pyproject.toml`, `package.json` or the image |

`product/SRS.md` frame (IEEE 29148 layout, hand-written, ≈ 80 lines, facts by reference): **1 Introduction** · 1.1 Purpose (this SRS, audience) · 1.2 Scope → VISION §Purpose, §In/Out of scope · 1.3 Definitions → GLOSSARY · 1.4 References → owner docs (INDEX ownership), `adr/README.md` · 1.5 Conventions: ID grammar, Pri meaning, retired rows, "M = in v3.0 unless MVP defers it". **2 Overall description** · 2.1 Product perspective → VISION, ADR-0010 · 2.2 Product functions → VISION §Journeys G1..G4 · 2.3 Users → VISION §Users · 2.4 Constraints → AGENTS R1..R9, ADR-0007 · 2.5 Assumptions and dependencies → VISION §Assumptions, NFR design envelope · 2.6 Apportioning → MVP §After v3.0. **3 Specific requirements** (generated, §3.1–3.4 above). **4 Verification** → TESTING (TST-*), A4-01 tagging rule, MVP release gates. **Appendix** generated counts and retired IDs.

### PRD outline (`product/VISION.md`, name kept)

Keep the name: 9 inbound references including 4 ADRs (history, never edited), the INDEX route and PLAN `Depends`. H1 becomes "Vision & product requirements"; INDEX route "Understand the product, scope, journeys (PRD)". Target ≈ 150 lines.

| Section | Today | Add |
|---|---|---|
| Problem | — | 4–6 lines: CT dataset work spread over Slicer, QuPath, scripts and spreadsheets; no provenance between QC, radiomics and stats |
| Goals | Purpose paragraph | 3–5 goals, each tied to a metric |
| Success metrics | — | table: metric · target · source. NFR IDs by reference; journey measures (e.g. G3 next case without the mouse, actions per case from A1's matrix) |
| Users | ✓ table | — |
| Journeys | — (in PLAN) | G1..G4 table moved from `audit/PLAN.md` (A7-07), owner here |
| Scope / non-goals | ✓ In / Out of scope | ANA-11 row moves here (A7-03) |
| Principles, Decisions | ✓ | — |
| Assumptions | — (NFR envelope) | local FS, WebGL2 browser, reference volume, fixtures-only testing → cite NFR, do not copy |
| Risks | — | 5 rows: browser memory on large volumes (NFR-09), udocker unverified (Step 4), PHI leakage (NFR-17), PyRadiomics pin (ADR-0006), doc/code drift (A4) |
| Releases | version line | "v3.0 cut: MVP.md; after: ROADMAP" |

### MVP outline (`product/MVP.md`, draft, not the final doc)

1. **Definition.** v3.0 = G1..G4 complete on the fixtures with their M requirements, no open P0/P1 findings, gates REL-01..nn green, Docker + udocker verified. Everything else is "after v3.0".
2. **Journeys → requirements** (from PLAN refs and `a4/trace.csv`; the build computes this table, MVP.md only lists the refs per path):

   | Path | Refs | M rows | M without a test citing them |
   |---|---|---|---|
   | G1 Open & inspect | UI-17, UI-24, SRC-09/14/15, VW-* | 21 | 8 |
   | G2 DICOM → project | UI-25, DCM-*, IMP-*, UI-08/09 | 22 | 9 |
   | G3 Review & curate | CUR-*, PHS-*, LBL-*, UI-26 | 25 | 8 |
   | G4 Radiomics → analysis | RAD-*, DB-*, ANA-*, VAR-06 | 26 | 6 |
   | Platform (all paths) | PRJ 14, UI 14, BE 12, OPS 12, SRC 11, TSK 11, FE 9, PLG 8, VAR 8, ANZ 7 | 106 | see trace |

3. **Blocking findings.** P0: 4, all fixed by `e858eab` (A2-01's Decision cell still says "accept", A7-12). P1 open: **36** (7 accepted, 29 undecided, 0 fixed); by path: G1 12 · G2 5 · G3 16 · G4 8 · all 3 · none 4 (A0-01, A4-03, A5-07, A6-03). A5-09 = A6-02 (merge at triage).
4. **Release gates (`REL-`, owned here).** REL-01 `make check` green · REL-02 one Playwright spec per G path (G4 has none, A6-01) · REL-03 no open P0/P1 · REL-04 NFR-07 ≤ 300 KB gzip, enforced by a gate (fails today, A0-01) · REL-05 NFR-10 image ≤ 1.5 GB (947 / 935 MB, passes) · REL-06 NFR-11 via TST-07, NFR-12 network allowlist spec (missing, A4-02), NFR-16 About (A4-05), NFR-17 · REL-07 TST-10 under Docker (passes) **and** udocker on the remote server: ROADMAP Step 4 (amd64 image, Dataset820 import check, IBSI phantom smoke in the Linux image) · REL-08 `make docs` `-W` clean and `make docs-srs` 0 errors · REL-09 version, tag and changelog line.
5. **After v3.0.** S and C rows (54 + 4), former `C (v3.1)` / `C (later)` rows, pending plugins (VOI extractor, nnU-Net; PLG-09 `pending`), P8 Electron (ADR-0001), P2 findings not accepted.

### Migration map (one restructure batch)

| Old | New | Kind |
|---|---|---|
| — | `docs/SITE.md`, `docs/_sphinx/{conf.py,reqs.py,_templates/redirect.html}` | new |
| — | `docs/product/SRS.md`, `docs/product/MVP.md` | new |
| `product/VISION.md` | same path | grown into PRD; + G1..G4 from `audit/PLAN.md` |
| `audit/PLAN.md` §Golden paths | VISION §Journeys | moved; PLAN keeps the walk instructions + a reference |
| `ops/AGENT_RUNBOOK.md` Steps 0–3b, P7b, P7c, addendum | `archive/v3/AGENT_RUNBOOK-done.md` | split; lane rules + Step 4 + Step 5 stay |
| `product/ROADMAP.md` §Lanes, done-phase detail | runbook / one line per phase | trimmed (A7-11) |
| `product/NFR.md` | same | + `Pri` column |
| `CURATION.md:30`, `PHASE.md:20`, `API.md:74`, 8 Pri cells | same | fixes A7-01/02/03 |
| `Makefile`, `.gitignore`, `README.md` | same | `docs`, `docs-srs` targets; `build/docs/`; one README line |

**AGENTS.md:** read-order line 3 becomes "Never read `docs/archive/**` (frozen history) unless the task is v2 migration". Nothing else.
**INDEX.md:** routes + `Requirements overview, SRS frame → product/SRS.md` · `Release scope, v3.0 gates → product/MVP.md` · `Build or publish docs → product/SRS.md §1.5, docs/_sphinx/`; the VISION route label as in §PRD. Ownership + `G1..G4 → product/VISION.md` · `REL- → product/MVP.md` (and `TST-`, A4-17). Conventions + Pri values (A7-03) · header exemptions (A7-09) · "`SITE.md`, `_sphinx/`: site only; agents skip" · archive = "frozen history (v2, done v3 runbook steps)".
