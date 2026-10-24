---
name: rw-review
description: Review the current diff of this repo against its hard rules, layering and doc ownership before commit. Findings only; does not edit.
---

Scope: `git diff HEAD` plus `git ls-files --others --exclude-standard`. Rules are in `AGENTS.md` (R1-R9, code standards); doc ownership in `docs/INDEX.md`. Do not restate them; check the diff against them.

Checks:
1. R1/R5: `git diff HEAD | grep -nE 'https?://|open\(.*["'"'"']w'` in `backend plugins scripts frontend/src`; any write outside project/derived roots or runtime network call is a finding.
2. Layering: `backend/tests/test_layering.py`, `frontend/src/app/boundaries.test.ts` still pass.
3. Behavior changed -> the owning doc updated (`docs/INDEX.md` ownership); changed decision -> new superseding ADR.
4. Endpoint change -> `rw-api-change` done (snapshot, `schema.d.ts`, `API.md`).
5. Touched tests name the requirement IDs they cover (`docs/ops/TESTING.md`).
6. Duplicated logic, dead code, needless abstraction (`make deadcode`).
7. Dependents of every edited file updated (grep importers).
8. Map drift: an added, renamed or removed package, feature, plugin, entry point or test location is reflected in `backend/`, `frontend/` or `plugins/` `AGENTS.md`; a new doc or ID owner has its `docs/INDEX.md` row; doc edits follow `docs/CONVENTIONS.md`.

Output: findings by severity as `file:line - problem - fix`. Say explicitly if none.
