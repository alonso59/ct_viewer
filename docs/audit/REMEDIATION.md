# Remediation plan (fix batches FB1..FB8)

Scope: order, content and exit of the fix batches for every open finding of A0..A7.
Read when: running or reviewing a fix batch.
Depends: audit/PLAN.md (§Triage and fix batches), audit/findings/A*.md, product/MVP.md (REL-02/03/04/06).

Owner decision (2026-09-26): batches run one after another in this session while the owner is away, one commit each on `version_3-dev` (no push). Findings with an owner decision follow it; **findings without one follow the Proposal of their row** (recorded as `fixed … (proposal)`). A change that needs a new ADR is made with that ADR in `Proposed`, flagged in the batch report for the owner.

## Rules per batch

1. Fix code + tests + the owning doc (R8); a golden-path fix adds or extends a Playwright step.
2. Gates before commit: `make check` green, `make docs` green, the batch's E2E specs green (Chromium; Firefox for journey specs).
3. Decision cell → `fixed <date> <sha>` (the sha of the batch commit is written in the next batch's commit, or `fixed <date> FBn`); MVP.md status column updated for the REL gates the batch moves.
4. A finding that turns out larger than its Effort, or needs an owner choice not covered here, is marked `defer (FBn: reason)` and listed in §Owner review; the batch continues.
5. Nothing on the deferred list is touched.

## Batches (order)

| # | Theme | Findings | Key decisions / notes | E2E |
|---|---|---|---|---|
| FB1 | PHI and view-only boundary | A5-03, A1-19, A5-16, A2-15, bundle residual paths (A5-02 residual: `sources/imports.jsonl`, `index/qc_warnings.jsonl`) | A5-03: token never returns `project_id` or absolute paths; `include_sensitive` stays allowed; document `/projects` visibility (ADR-0004). A1-19: `/open/{sid}` in the URL. A2-15: `anonymize: basic` never derives names from folder names | view-only, open-mode, projects-bundle |
| FB2 | Curation, segmentation sets, labeling correctness | A5-05, A5-06, A5-07, A5-08, A5-09 + A6-02, A0-02, A5-11, A5-15, A2-16, A1-05, A6-04 (live-sync tests) | A5-09: server-side `?curation_status=` (API-20). A5-15: "partially reviewed" rollup. A1-05: Inspector section "Labels · this case / scan" | tst08-multiuser, labeling, p2-flow |
| FB3 | Navigation and keyboard | A1-01, A1-02, A1-03, A1-04, A2-02, A2-09 + A1-17, A1-06, A1-07, A1-09, A1-10, A1-11, A6-04 (keybinding tests), A4-03 + A5-10 (archive UI, archive refused while a job runs) | A1-04: "Next unreviewed" + navigation context (Outliers / queue / Problems / table). A1-09: menus from categories, About (NFR-16, A4-05) | new `g3-review` spec (start), smoke, p2-flow |
| FB4 | Open mode, import and converter | A2-03, A2-04, A2-07 + A3-03, A2-13, A6-05, A2-10, A2-11 + A3-05, A2-12, A2-14, A1-15, A1-16, A5-13 | A2-03: attach from anywhere under ALLOWED_DATA_ROOTS; **new ADR superseding SRC-10's rule** (Proposed). A6-05: move Open-mode logic from `api/v1/sources.py` into `sources/` | open-mode, converter, tasks-dicom, new `g1-open`, `g2-dicom` specs |
| FB5 | Radiomics, dashboard and analysis | A2-05, A2-06, A5-04, A3-04, A1-08 + A2-08, A3-15, A3-10, A3-14, A3-13, A3-21, A1-18 + A3-06, A5-14, A5-12 | A2-06: sort by features over threshold then max \|z\|, top 10 + "show all". A5-04: effective phase at read time. A3-04: English number format, inputs accept `,` and `.` | new `g4-radiomics` spec (A6-01) |
| FB6 | Visual and readability | A3-01, A3-02, A3-16, A3-23, A1-12, A1-13, A1-14, A3-07, A3-08, A3-09, A3-11, A3-12, A3-17, A3-18, A3-19, A3-20, A3-22 | A3-16: Interface size Compact / Default (14 px) / Large. A3-23: themes Dark / Light / System now; **new ADR superseding part of ADR-0023** (active indicator, title-bar toggles), Proposed | smoke, viewer-fov, ct-tools |
| FB7 | Docs conformance and hygiene | A4-02, A4-04 + A6-09, A4-05 (if not done in FB3), A4-06, A4-07 (retired-ID rows CUR-06, API-29; ADR README note), A4-08, A4-10, A4-11, A4-12, A4-13, A4-14, A4-15, A4-16, A4-17 rest, A7-05, A7-08, A7-11, A4-01 (cite IDs in touched tests) | A4-16: one global LRU budget for Open scratch + project `cache/`. NFR-12 network-allowlist spec (REL-06) | new network-allowlist spec |
| FB8 | Tests, performance budget and code health | A0-01, A6-01 (if not closed in FB5), A6-16, A6-03, A6-07, A6-08, A6-10, A6-11, A6-12, A6-13, A6-14, A6-15, A6-17, A6-18, A6-19, A0-05 | A0-01: bring initial JS under 300 KB gzip and add a size gate to `make check` (REL-04). A6-03 (L): mock = responses recorded from the real API on the fixtures, re-record script; may be split and partly deferred per rule 4 | full `make e2e` ×1 Chromium + Firefox |

## Deferred (not in any batch)

| Item | Why | When |
|---|---|---|
| AUD-A6-06 shared run lifecycle / `tasks/service.py` split | owner 2026-09-26 | with AUD-A4-09 (API-30..37 migration) |
| AUD-A4-09 migrate frontend to API-42..47, drop API-30..37 aliases | coupled to A6-06 | same batch as A6-06, after FB8 |
| `DERIVED_HOST` fallback rule (A0-03 open question) | owner: pending with udocker | ROADMAP Step 4 |
| udocker verification, amd64 image, Dataset820 check (REL-07) | remote server | ROADMAP Step 4 |

## Owner review (filled by the batches)

| Batch | Commit | Needs review |
|---|---|---|
| — | — | — |
