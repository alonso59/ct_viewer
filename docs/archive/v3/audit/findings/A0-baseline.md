# A0 · Baseline

Scope: health of the tree before the A1..A6 audits: unit gates, Playwright ×3 (Chromium + Firefox), bundle size (NFR-07), OCI image and container smoke (NFR-10, TST-10), static R3 check.
Read when: triaging A0, or checking whether a later audit's failure is pre-existing.
Depends: audit/PLAN (G-1..G-7, findings format), NFR, TESTING (TST-*), DEPLOYMENT (OPS-*).

Run 2026-09-25 on `version_3-dev` @ `b388447` (dev Mac, Apple Silicon, colima). Fixtures only. Scratch logs and traces: `$SCRATCH/a0/` (session scratchpad, not committed).

## Results

| Check | Result | Duration | Notes |
|---|---|---|---|
| Fixtures (`.fixtures/synthetic`) | ok, not regenerated | 1.9 s | A fresh `tools.make_fixtures` into scratch is byte-identical (224 files, same `expected.json`). |
| `make check` | **green** | 1 min 57 s | ruff check + format (218 files), eslint, mypy strict (171 + 3 files), tsc: clean. |
| └ pytest | 486 passed, 0 failed, 0 skipped | 95 s | 123 warnings, all third-party (below). |
| └ vitest | 235 passed in 45 files, 0 failed, 0 skipped | 7.7 s | jsdom created 45 times, 55 % of tracked time (A6 input). |
| Playwright run 1 | 40/40 | 105 s | 20 tests in 16 specs × 2 browsers. |
| Playwright run 2 | 39/40 | 117 s | `tst08-multiuser` failed on Chromium (AUD-A0-02). |
| Playwright run 3 | 40/40 | 101 s | TST-07 teardown (fixture hashes, R1) passed in all runs. |
| Frontend build | ok | 1.0 s | `vite build --outDir` scratch (tsc covered by `make check`); "chunks > 500 kB" warning, all lazy. |
| NFR-07 initial JS | **FAIL** 300.3 KiB | — | Budget 300 KiB (AUD-A0-01). |
| `make image` | ok | 18 s | Warm layer cache (deps cached; web, app and IBSI steps re-ran). IBSI phantom smoke PASS. |
| `make container-smoke` | **pass** | 11 s | Size, IBSI, OPS-04 refusal, arbitrary UID, health, SPA + fallback, API 404, import + index, Range 206, HEALTHCHECK, 191 source files unchanged (R1). |
| R3 static check | mismatch | — | udocker launcher lacks the derived and plugins mounts (AUD-A0-03). |

Slowest pytest calls (`--durations=10`): `test_runner::test_cancel_sigterm_then_resume` 5.6 s, `test_jobs::test_shutdown_interrupts_and_rejects` 5.0 s, `test_fixtures::test_fixtures_are_deterministic` 3.5 s, `test_labeling::test_delete_table_hides_it_keeps_events_and_restores` 3.4 s, `test_analytics_api::test_two_groups_welch_and_mann_whitney` 3.3 s; the rest < 3 s.

Warnings worth knowing (not findings): `DeprecationWarning: load_module()` removed in Python 3.15 (raised during imports in `test_radiomics*`, `test_tasks`, `test_lane2_e2e`; frozen importlib, third-party); scikit-image marching cubes sets `ndarray.shape`, deprecated in NumPy 2.5 (65 hits in `test_mesh`), so a future NumPy can break API-25 meshes; PyRadiomics `Mean of empty slice` RuntimeWarnings on tiny ROIs.

## Playwright per spec (pass = all tests of the spec passed; seconds summed)

| Spec | Chromium r1 / r2 / r3 | Firefox r1 / r2 / r3 |
|---|---|---|
| converter | ✓ 4.6 / ✓ 4.1 / ✓ 4.0 | ✓ 4.6 / ✓ 4.3 / ✓ 4.2 |
| ct-tools | ✓ 5.0 / ✓ 5.1 / ✓ 4.8 | ✓ 4.0 / ✓ 4.1 / ✓ 4.0 |
| labeling | ✓ 3.5 / ✓ 3.4 / ✓ 2.9 | ✓ 3.6 / ✓ 3.1 / ✓ 3.5 |
| open-mode | ✓ 3.5 / ✓ 3.6 / ✓ 3.6 | ✓ 3.1 / ✓ 3.1 / ✓ 3.2 |
| p2-flow | ✓ 3.6 / ✓ 3.6 / ✓ 3.6 | ✓ 3.4 / ✓ 3.4 / ✓ 3.6 |
| p7c-exit | ✓ 9.3 / ✓ 9.3 / ✓ 9.3 | ✓ 8.1 / ✓ 8.4 / ✓ 7.9 |
| projects-bundle | ✓ 2.3 / ✓ 2.3 / ✓ 2.4 | ✓ 2.3 / ✓ 1.8 / ✓ 2.1 |
| runner | ✓ 1.8 / ✓ 1.8 / ✓ 1.8 | ✓ 1.8 / ✓ 1.9 / ✓ 2.0 |
| smoke | ✓ 0.4 / ✓ 0.4 / ✓ 0.4 | ✓ 0.4 / ✓ 0.4 / ✓ 0.5 |
| tasks-dicom | ✓ 2.4 / ✓ 3.0 / ✓ 2.4 | ✓ 2.1 / ✓ 2.6 / ✓ 2.2 |
| **tst08-multiuser** | ✓ 5.0 / **✗ 18.3** / ✓ 5.3 | ✓ 4.6 / ✓ 4.3 / ✓ 3.7 |
| variables | ✓ 3.4 / ✓ 3.6 / ✓ 3.3 | ✓ 4.1 / ✓ 3.9 / ✓ 3.9 |
| view-only | ✓ 2.0 / ✓ 2.3 / ✓ 2.0 | ✓ 1.3 / ✓ 1.3 / ✓ 1.3 |
| viewer-fov | ✓ 3.7 / ✓ 3.7 / ✓ 3.6 | ✓ 3.7 / ✓ 3.6 / ✓ 3.6 |

Flaky: `tst08-multiuser` (Chromium, 1 of 3). Trace: `$SCRATCH/a0/e2e-results-run2/tst08-multiuser-live-sync--f2430--wins-between-two-reviewers-chromium/trace.zip`. E2E ran on `E2E_API_PORT=8047 E2E_WEB_PORT=5197` (8021 was taken by another process at the time).

## NFR numbers

- **NFR-07**: initial JS = entry + `modulepreload` set, `gzip -9` per file (the LANE_NOTES method): **307,514 B = 300.3 KiB** (307.5 kB decimal) > 300. Biggest initial chunks (gzip): `shell` 116.4 kB, `index` 89.7 kB, `lib` 57.0 kB, `i18n` 20.9 kB, `viewer` 10.9 kB; initial CSS 25.2 kB. Biggest lazy chunks: `NiivueViewer` 330 kB, `zstd` 242 kB, `DashboardEditor` 229 kB, `blosc` 204 kB, `slices` 157 kB.
- **NFR-10**: 956 MB uncompressed (`du -sxb /` in the image), 268 MB compressed, **linux/arm64** ≤ 1.5 GB. amd64 (the server target) not rebuilt here; DEPLOYMENT records 935 MB.

## Blockers

None. Chromium and Firefox were installed (Playwright 1.63); colima was running; no pulls needed (base images cached). Not covered: amd64 image build, udocker runtime (G-5, ROADMAP Step 4).

## Findings

| ID | Sev | Path | Finding | Evidence | Proposal | Refs | Effort | Decision |
|---|---|---|---|---|---|---|---|---|
| AUD-A0-01 | P1 | — | Initial JS is over the NFR-07 budget, and nothing gates it: the P7c exit claims "NFR-07 green", but each commit is only measured by hand. | Same method on archived trees: `de44d42~1` 305,354 B (298.2 KiB, matching the last LANE_NOTES figure) → `de44d42` 307,381 B (300.2 KiB) → `b388447` 307,514 B (300.3 KiB). The native phase selection frontend crossed the line. | Put the phase-selection UI behind a lazy boundary (or move its strings to `en.lazy.json`); add a script that measures entry + modulepreload and runs as a check; state the unit (KiB) in NFR.md. | NFR-07, FE-05, PHS-01 | S | fixed 2026-09-27 FB8 (proposal; the editor area (dockview) is lazy: 312.1 → 226.9 KiB; `make bundle-size` in `make check`; KiB in NFR-07) |
| AUD-A0-02 | P2 | G3 | Reviewer B can miss a live curation decision. If a `curation.appended` event arrives while B's first `curation/state` fetch is still running, `setQueryData` is skipped (the cache is empty) and `invalidateQueries` joins that already-stale request: TanStack only cancels a running fetch when data exists. B shows the toast but not the new state until some later refetch. This is also the cause of the flaky `tst08-multiuser` test. | `frontend/src/api/hooks.ts:453-457`. Run-2 trace: B `GET curation/state` at 39.272 s, A `POST curation/events` at 39.286 s, then B refetches `/cases` and `/projects` at 39.305 s but never `curation/state` again. The spec comment (`e2e/tst08-multiuser.spec.ts:65-66`) already notes Chromium flakiness. | On that event with an empty cache, `refetchQueries({ cancelRefetch: true })`, or seed the cache from the event; in the spec, wait until B's decisions list has loaded before A clicks. | CUR-11, TST-08 | S | fixed 2026-09-26 FB2 (proposal): SSE handler restarts a first fetch still in flight (`refreshQueries`); behavioural test with a real QueryClient |
| AUD-A0-03 | P0 | G2 | `scripts/udocker-run.sh` does not match compose for P7b mounts. It mounts only the workspace and data folders, and never sets `ALLOWED_DERIVED_ROOTS` (compose defaults it to `DERIVED_HOST`) or `PLUGINS_ROOT`. Under udocker, the derived folder and external manifests are not visible inside the container, so derived-writing tasks (DICOM → project, segmentation) and external plugins cannot work on the remote server. `.env` cannot add volumes. | `scripts/udocker-run.sh:65-79` vs `docker-compose.yml:16-18,25-26`; `.env.example:12-17` documents `DERIVED_HOST` / `PLUGINS_HOST` for both runtimes. Static only (G-5). | Add the `DERIVED_HOST` mirror volume, the `PLUGINS_HOST` → `/plugins` volume and the two env defaults to the script; add a `--dry-run` test that compares its args with compose. | R3, OPS-09, OPS-11, TSK-01 | S | fixed 2026-09-25 e858eab (`udocker-run.sh` mounts derived + plugins, sets `ALLOWED_DERIVED_ROOTS`/`PLUGINS_ROOT`; dry-run checked). Open question closed 2026-09-27 (owner, FB10): the default stays `./derived` → `/derived` for compose and udocker; the external runner is configured on the remote server where the repo is installed (DEPLOYMENT §Docker) |
| AUD-A0-04 | P2 | — | DEPLOYMENT's compose snippet mounts plugins at a mirror path (`${PLUGINS_HOST}:${PLUGINS_HOST}:ro`), while the real compose file and the table in the same doc use `/plugins`. | `docs/ops/DEPLOYMENT.md:60` vs `docker-compose.yml:26` and `DEPLOYMENT.md:81` | Fix the snippet (one fact, one place: point to compose). | R8, TSK-01 | S | fixed 2026-09-25 e858eab with A0-03 |
| AUD-A0-05 | P2 | — | Every E2E run leaves three temp folders (workspace, derived, plugins) that are never removed; `$TMPDIR` holds 236 `rw-e2e-*` folders (170 from today). | `frontend/playwright.config.ts:17-23` (`mkdtempSync`, no cleanup in `e2e/tst07-teardown.ts`) | Remove them in the global teardown unless `E2E_KEEP` is set. | TST-05 | S | fixed 2026-09-27 FB8 (proposal; the global teardown removes the folders the run created unless `E2E_KEEP`) |

Other notes: compose-only keys (`restart`, `user: RUN_AS`, `ports`, image `HEALTHCHECK`) are Docker conveniences the app does not rely on; OPS-04, OPS-02 and R1 held under Docker.
