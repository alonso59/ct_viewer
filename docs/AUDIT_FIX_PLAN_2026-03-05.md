# Radiology WebUI Audit Fix Plan (2026-03-05)

## Objective
Resolve audit findings from `AUDIT_REPORT_2026-03-05.md` and move release gate from **Not Ready** to **Ready**.

## Implementation Status (2026-03-05)

- [x] `AUD-2026-03-05-P1-001` Session-isolated volume state (`load_handle` + handle cache + 410 semantics).
- [x] `AUD-2026-03-05-P1-002` Absolute host paths removed from public API responses.
- [x] `AUD-2026-03-05-P1-003` Smooth slice-fetch lifecycle (`AbortController`, wheel coalescing, stale-preserving cache).
- [x] `AUD-2026-03-05-P2-001` Container hardening (`USER app` + Dockerfile `HEALTHCHECK`).
- [x] `AUD-2026-03-05-P2-002` Backend dependency pinning.
- [x] `AUD-2026-03-05-P2-003` Frontend chunk splitting + lazy 3D panel loading.
- [x] `AUD-2026-03-05-P3-001` Safer frontend token storage default (`memory` mode, optional `local` mode).
- [ ] Native Docker/Podman runtime validation (T12) on a host with engine installed.

Current gate state: **All in-repo fix-plan items implemented; external native container verification still pending.**

## Prioritization

### Immediate (Release-Blocking)

#### 1) Session-isolated volume state (`AUD-2026-03-05-P1-001`)
- Milestone mapping: `M8.1` (new), backend architecture hardening.
- Scope:
  - Replace global `volume_cache.get_current()` dependency with scoped handle model.
  - `POST /load` returns `load_handle` (opaque UUID).
  - `GET /api/slice/...` and `GET /api/mesh/...` require `load_handle`.
  - Cache store keyed by handle with TTL and LRU max size.
- Implementation details:
  1. Add `load_handle: str` to `VolumeInfo`.
  2. Introduce `VolumeCache.get_by_handle(handle)` and remove global `_current_key` access from public API paths.
  3. Update frontend API client and viewer state to keep active `load_handle`.
  4. Add handle-expired response (`410 Gone`) and reload fallback in frontend.
- Acceptance criteria:
  - Two concurrent browser sessions can load different series and navigate independently.
  - No cross-session slice/mesh mix-up under concurrent navigation.

#### 2) Remove absolute host paths from API payloads (`AUD-2026-03-05-P1-002`)
- Milestone mapping: `M1` hardening patch.
- Scope:
  - Remove `path`, `image_path`, `mask_path` from public response models.
  - Keep internal path resolution server-side only.
- Implementation details:
  1. Adjust `DatasetSummary` and `SeriesInfo` Pydantic models.
  2. Refactor discovery service to return internal IDs only.
  3. Ensure load endpoint resolves target from `(dataset_id, patient_id, series_id)` via backend registry.
  4. Update frontend TypeScript interfaces and usages.
- Acceptance criteria:
  - API responses contain no absolute filesystem paths.
  - Existing UI flows (dataset/patient/series selection and load) remain functional.

#### 3) Smooth slice-fetch lifecycle (`AUD-2026-03-05-P1-003`)
- Milestone mapping: `M8.1` frontend performance patch.
- Scope:
  - Eliminate visible fetch interruptions under rapid wheel scroll.
- Implementation details:
  1. Add `AbortController` to `apiClient.getSliceBlob` and cancel obsolete requests per axis.
  2. Add wheel coalescing (`requestAnimationFrame` gate or 30-50ms throttle).
  3. Add small in-memory slice cache (per `requestKey`) for adjacent indices.
  4. Keep stale-while-revalidate rendering but avoid replacing current frame with spinner.
- Acceptance criteria:
  - Rapid scroll shows continuous imagery without blank/loading swaps.
  - End-user perceived smoothness improves while maintaining correctness.

### Next (High Value, Non-Blocking)

#### 4) Container hardening (`AUD-2026-03-05-P2-001`)
- Milestone mapping: `M12`.
- Scope:
  - Add non-root runtime user and Dockerfile-level healthcheck.
- Implementation details:
  1. Create app user/group in runtime stage.
  2. `chown` app directories and run `uvicorn` as non-root.
  3. Add Dockerfile `HEALTHCHECK` hitting `/api/health`.
  4. Validate compose still healthy.
- Acceptance criteria:
  - Container runs as non-root.
  - Healthcheck reports healthy in standalone and compose.

#### 5) Pin backend dependencies (`AUD-2026-03-05-P2-002`)
- Milestone mapping: `M0` hygiene follow-up.
- Scope:
  - Pin backend dependencies and adopt deterministic install.
- Implementation details:
  1. Convert `requirements.txt` to pinned versions (or generate lock from `requirements.in`).
  2. Update Docker build and local install docs accordingly.
  3. Add dependency refresh cadence (monthly or per release).
- Acceptance criteria:
  - Rebuilds are reproducible across environments.
  - Dependency diffs are explicit in version control.

#### 6) Reduce initial JS payload (`AUD-2026-03-05-P2-003`)
- Milestone mapping: `M9/M11`.
- Scope:
  - Split heavy 3D dependencies from default viewer path.
- Implementation details:
  1. Lazy-load `Surface3DView` and related three.js modules.
  2. Configure Rollup `manualChunks` for large vendor groups.
  3. Re-run build and track chunk sizes.
- Acceptance criteria:
  - Main chunk size reduced materially versus current 1.56 MB.
  - No regressions in 3D panel behavior.

### Deferred (Hardening)

#### 7) Token storage strategy upgrade (`AUD-2026-03-05-P3-001`)
- Milestone mapping: post-M12 security hardening.
- Scope:
  - Reduce token exposure from `localStorage`.
- Implementation details:
  1. For local mode, allow in-memory token option.
  2. For shared mode, move to HTTP-only cookie or short-lived token with refresh.
  3. Update auth UX and documentation.
- Acceptance criteria:
  - Equivalent login UX with reduced token exfiltration risk.

## Validation Plan Per Phase

1. Backend isolation/path-redaction phase:
   - Re-run dataset/patient/series/load/slice/mesh API checks.
   - Add concurrent-session smoke test (two independent handles).
2. Frontend smoothness phase:
   - Manual rapid-scroll UX check in all three 2D panels.
   - Confirm no frame disappearance during active scrolling.
3. Deployment hardening phase:
   - Re-run lint/build.
   - Execute native Docker/Podman validation on a machine where engine is available.
   - Confirm image behavior with compose and mounted dataset.

## Exit Criteria
- All `P1` findings closed.
- Runtime checks T01-T11 passing after changes.
- T12 completed on a Docker/Podman-enabled environment, documented with build/run/image-size evidence.
- Release gate updated to **Ready**.
