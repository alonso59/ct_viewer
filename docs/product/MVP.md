# MVP: the v3.0 release cut

Scope: what v3.0 contains, what blocks it, the release gates (REL-*), and what comes after v3.0.
Read when: deciding whether something is in v3.0, or preparing the release.
Depends: VISION (§Journeys), SRS (requirement grammar), NFR, ROADMAP (Step 4), audit/PLAN.md (findings).

## Definition

v3.0 = journeys G1..G4 (VISION §Journeys) complete on the fixtures, every `M` requirement met, no open P0/P1 audit finding, and every gate in §Release gates green, including Docker **and** udocker. Everything else is §After v3.0 (owner decision 2026-09-26).

## Journeys → requirements

Every `M` row is in v3.0 unless §Deferred lists it. Which rows sit behind which journey is computed from the Refs column of VISION §Journeys (SRS §3 column **Journeys**; counts in `make docs-srs`). Rows behind no journey (projects, tasks, plugins, backend, frontend, runtime) are the platform all four journeys use.

## Deferred

No `M` requirement is deferred. A deferral is a row here (`ID · reason · target release`) plus the owner's approval.

## Blocking findings

REL-03 counts findings whose Decision is not `fixed`, `defer` or `reject` (`make docs-srs` prints the numbers). State on 2026-09-26: P0 all fixed (`e858eab`); P1 36 open (7 accepted, 29 undecided), 33 after FB1, 26 after FB2, 18 after FB3, 11 after FB4, 5 after FB5, 3 after FB6 and FB7 (2026-09-27; FB7 held P2 findings only), 0 after FB8 (2026-09-27). Fix order: PLAN §Triage and fix batches.

## Release gates

| ID | Gate | Check | Status |
|---|---|---|---|
| REL-01 | Unit, lint and type checks green, requirement check included | `make check` | pass (the NFR-07 bundle gate included since FB8; knip + vulture dead-code gate and parallel pytest since FB9) |
| REL-02 | One Playwright spec walks each journey G1..G4 end to end (Chromium + Firefox, TST-05) | `make e2e` | pass: G1 `e2e/g1-open.spec.ts`, G2 `e2e/g2-dicom.spec.ts`, G3 `e2e/g3-review.spec.ts` (whole path since FB8, AUD-A6-16) and G4 `e2e/g4-radiomics.spec.ts` green in Chromium + Firefox (FB8 full run); the older specs are kept, their shared steps are in `e2e/helpers.ts` |
| REL-03 | No open P0/P1 audit finding | `make docs-srs` counts | pass (P0 0, P1 0 after FB8) |
| REL-04 | NFR-07 initial JS within budget, enforced by a gate | `make bundle-size` (in `make check`) | pass: 227.0 KiB of 400, +0.0 against the baseline (FB9; gate since FB8, AUD-A0-01) |
| REL-05 | NFR-10 image size | `make image`, `docker image ls` | pass (arm64 947 MB, amd64 935 MB) |
| REL-06 | NFR-11, NFR-12, NFR-16, NFR-17 verified | TST-07, network allowlist spec, About | pass: TST-07 hook; `e2e/network-allowlist.spec.ts` green in Chromium + Firefox (FB7, AUD-A4-02); About with "Research use only" (FB3, AUD-A4-05) |
| REL-07 | TST-10 under Docker and under udocker on the remote server: ROADMAP P7 remaining items and Step 4 (amd64 image, Dataset820 import check, IBSI phantom smoke in the Linux image) | `make container-smoke`, `scripts/udocker-run.sh` | Docker pass; udocker open |
| REL-08 | Docs site builds with no warnings; requirement check has no errors | `make docs`, `make docs-srs` | pass |
| REL-09 | Version set in `backend/pyproject.toml`, git tag `v3.0.0`, one release note line in ROADMAP | manual | open |

## After v3.0

| Item | Refs |
|---|---|
| `S` and `C` requirements not done by the cut | SRS §3 (Pri column) |
| Targeted at v3.1: side-by-side compare, paired comparison, voxel-based feature maps | VW-18, ANA-10, RAD-14 |
| Later: per-project plugin enable/disable, updates, management | PLG-10 |
| Pending plugins: VOI extractor, nnU-Net | PLG-09, ROADMAP §Pending plugins |
| Electron desktop build | P8, ADR-0001 |
| P2 audit findings not accepted into a fix batch | audit/findings/ |
