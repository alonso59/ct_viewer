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
| TST-07 | Source immutability | pytest / E2E hook | SHA-256 of every fixture source file before and after the full E2E suite must match (R1) |
| TST-08 | Multi-user | Playwright (2 contexts) | CUR-11 SSE sync, CUR-12 last-writer-wins |
| TST-09 | Performance | scripted bench | NFR-01..05 on the reference volume |
| TST-10 | Container smoke | script | Image boots under Docker and udocker; health OK; one item viewable |
| TST-11 | Fixtures | `make fixtures` | Synthetic dataset (below) |

## Synthetic fixture dataset (TST-11)

Generated, not committed. It is small (64³–128³ int16 volumes, 3 labels as spheres/ellipsoids) and deterministic (fixed seed).
It contains `metadata.jsonl`, `phase.json`, `voi/voi_catalog.jsonl` and a legacy `.npy` VOI, plus **deliberate defects**:
missing SEG, shape mismatch, ambiguous phase, ambiguous side, duplicate identity, missing file.
Every IMP-08 warning code must be produced by at least one fixture row.

## CI gates

Lint + typecheck · TST-01..04 · OpenAPI/TS types up to date · TST-07 · image build.
TST-05/06/08/09/10 run nightly or before a release tag.
