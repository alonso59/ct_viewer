# Testing

Scope: test layers, fixtures, safety and compliance tests, CI gates.
Read when: writing tests or adding a feature (every requirement ID should map to ≥1 test).
Depends: all domain docs.

| ID | Layer | Tooling | Covers |
|---|---|---|---|
| TST-01 | Backend unit | pytest | services, reducer (CUR-08), path guards (BE-02) |
| TST-02 | Parsers | pytest + hypothesis | IMP input variants, phase normalization table |
| TST-03 | API contract | pytest + httpx; OpenAPI diff | API-*, problem+json slugs |
| TST-04 | Frontend unit | Vitest + Testing Library | features, stores, schema-driven form (RAD-01/04) |
| TST-05 | E2E | Playwright (Chromium, Firefox) | import → explore → view → curate → radiomics → dashboard |
| TST-06 | IBSI compliance | pytest | Engine output vs IBSI digital phantom + CT phantom reference values, within the IBSI-published tolerances; results stored with `ibsi_map_version` |
| TST-07 | Source immutability | pytest / E2E hook | SHA-256 of every fixture source file before and after the full E2E suite must match (R1); derived writes only inside run folders / append-only datasets |
| TST-08 | Multi-user | Playwright (2 contexts) | CUR-11 SSE sync, CUR-12 last-writer-wins |
| TST-09 | Performance | scripted bench | NFR-01..05 on the reference volume |
| TST-10 | Container smoke | `scripts/container-smoke.sh` (Docker), `scripts/container_smoke.py --url … --root …` (udocker) | Image boots under Docker and udocker; health OK; one item viewable |
| TST-11 | Fixtures | `make fixtures` | Synthetic dataset (below) |
| TST-12 | Statistics | pytest vs SciPy/statsmodels reference | ANA test choice, p/q/effect sizes, each REC rule triggered by a fixture |
| TST-13 | Orientation | pytest | A synthetic DICOM series and NumPy `xyz`/`zyx` arrays with an asymmetric marker (known L/A/S voxel) convert to NIfTI with the marker at the expected RAS mm (NFR-18) |
| TST-14 | Task protocol | pytest | Builtin and external runtimes on the fake `segment.threshold` plugin: queue, runner claim, progress, cancel, resume, `waiting_for_runner`, mask registration as a segmentation set |
| TST-15 | Sources | pytest + hypothesis | `nifti-files` patterns, single-file import, identity registry stability across incremental imports, Open mode (NIfTI, DICOM file, label map, attach mismatch), refusal `actions[]` |
| TST-16 | Analyzers | pytest | Phase text/timing/conflict cases, target profiles, readiness codes, activation reindex (ANZ-*) |

## Synthetic fixture dataset (TST-11)

Generated, not committed: `make fixtures` writes `.fixtures/synthetic/` (generator `backend/tools/make_fixtures.py`, oracle `expected.json`). It is small (64³–128³ int16 volumes, 3 labels as spheres/ellipsoids) and deterministic (fixed seed).
It contains `metadata.jsonl`, `phase.json`, `voi/voi_catalog.jsonl` and a legacy `.npy` VOI, plus **deliberate defects**:
missing SEG, shape mismatch, ambiguous phase, ambiguous side, duplicate identity, missing file.
Every IMP-08 warning code must be produced by at least one fixture row.
P7b fixtures (generated, no real data): a synthetic DICOM series (pydicom, CT, with study/series descriptions and contrast times for the phase rules; one PHI-looking fake name to test anonymization), one Enhanced multi-frame file, a NIfTI-only folder in nnU-Net naming with a `labelsTr/` mask, a standalone label map, and NumPy pairs in `xyz` and `zyx` with sidecars.
Variables (VAR/ANA): no `group` field; case-level numeric study variables with ~50 % missing and one compositional pair; a `numeric-discrete` variable; vendor strings needing recode; one MRI scan; enough healthy cases (≥ 30) for group tests. Never copy values from real metadata into fixtures.

## E2E specs (Playwright, Chromium + Firefox)

`smoke`, `p2-flow` (50 cases / 89 scan rows on the fixtures), `variables` (API-16..18), `tst08-multiuser` (TST-08), `projects-bundle` (IMP-09 hash job, PRJ-08/09 export → import). Ports: `E2E_API_PORT`, `E2E_WEB_PORT`.

## CI gates

Lint + typecheck · TST-01..04 · OpenAPI/TS types up to date · TST-07 · image build.
TST-05/06/08/09/10 run nightly or before a release tag.
