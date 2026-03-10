# Radiology WebUI Audit Report (2026-03-05)

## Summary
- Scope: `radioccrcc-webui` only.
- Depth: full runtime audit on this host, with native Docker/Podman checks treated as external due missing engines.
- Skills used:
  1. `clean-code`
  2. `api-security-best-practices`
  3. `web-performance-optimization`
  4. `docker-expert`
  5. `senior-backend` / `senior-frontend` (secondary)
- Release gate verdict: **Not Ready**

## Post-Implementation Update (2026-03-05)
- Closed in code:
  - `AUD-2026-03-05-P1-001` (session-isolated `load_handle` flow).
  - `AUD-2026-03-05-P1-002` (absolute path redaction from API payloads).
  - `AUD-2026-03-05-P1-003` (slice request cancellation/coalescing and stale-preserving behavior).
  - `AUD-2026-03-05-P2-001` (non-root runtime + Dockerfile healthcheck).
  - `AUD-2026-03-05-P2-002` (pinned backend dependencies).
  - `AUD-2026-03-05-P2-003` (bundle splitting + lazy 3D import).
  - `AUD-2026-03-05-P3-001` (memory-first token storage mode).
- Remaining external check:
  - Native Docker/Podman runtime verification (T12) on a machine with engine availability.
- Updated gate interpretation:
  - **In-repo code blockers are resolved; final release sign-off still requires external T12 execution evidence.**

## Environment Truth
- `udocker`: available (`version 1.3.17`).
- `docker`: not available (`command not found`).
- `podman`: not available (`command not found`).
- Milestone tracker status in `AGENTS.md`:
  - M0-M11: completed.
  - M12: blocked for runtime build/test/image size validation.

## Runtime Verification Results

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| T01 | Backend health (`/api/health`) on `:8000` | PASS | `{"status":"ok"}` |
| T02 | Frontend dev server on `:5173` + proxy `/api/health` | PASS | HTML served from Vite + proxied `{"status":"ok"}` |
| T03 | Dataset discovery metadata | PASS | `/api/datasets` returned Dataset220/420/720/820/920 |
| T04 | Patient/series discovery for Dataset820/case_00001 | PASS | `/api/datasets/Dataset820/patients/case_00001/series` returned nifti+voi series |
| T05 | Series load returns shape/spacing/labels | PASS | `/load` returned shape `[512,512,97]`, labels `[1,2,3]` |
| T06 | Slice endpoint returns valid PNG | PASS | `/tmp/audit_auth_axial.png` verified as `512x512 RGB` |
| T07 | Auth disabled mode allows API calls | PASS | `/api/datasets` returned `200` before token enforcement |
| T08 | Auth enabled mode enforces bearer token | PASS | `401` without header, `200` with `Authorization: Bearer test123` |
| T09 | Settings PUT/GET roundtrip | PASS | `PUT /api/settings` then `GET /api/settings` returned persisted payload |
| T10 | Frontend lint | PASS | `npm run lint` returned success (no ESLint errors) |
| T11 | Frontend build | PASS (with warning) | `npm run build` succeeded; bundle warning (`index-*.js 1,568.57 kB`) |
| T12 | Native container runtime checks (`docker/podman`) | BLOCKED (external) | both binaries missing on host |

## Findings (Severity Ordered)

### 1) `AUD-2026-03-05-P1-001`
- `id`: `AUD-2026-03-05-P1-001`
- `severity`: `P1`
- `skill`: `api-security-best-practices`, `clean-code`
- `area`: backend data/session isolation
- `evidence`:
  - Global mutable current series key: [`backend/app/services/volume_cache.py:30`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/services/volume_cache.py#L30)
  - Global current selection overwritten on load: [`backend/app/services/volume_cache.py:81`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/services/volume_cache.py#L81)
  - Slice endpoint reads global current state (no client/session selector): [`backend/app/api/slices.py:61`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/api/slices.py#L61)
- `impact`:
  - Concurrent users/sessions can race each other and read/render the wrong series.
  - In shared deployment this is cross-user data leakage risk.
- `recommendation`:
  - Replace global `current` state with per-session context (token/session-id keyed cache).
  - Return a `load_handle` from `/load`; require it in `/api/slice` and `/api/mesh`.
- `file`: `backend/app/services/volume_cache.py`, `backend/app/api/slices.py`
- `line`: `30`, `81`, `61`
- `milestone`: `M2` (backend slice architecture), follow-up hardening in `M12`

### 2) `AUD-2026-03-05-P1-002`
- `id`: `AUD-2026-03-05-P1-002`
- `severity`: `P1`
- `skill`: `api-security-best-practices`
- `area`: API information disclosure
- `evidence`:
  - Dataset response exposes absolute host paths: [`backend/app/services/discovery.py:68`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/services/discovery.py#L68)
  - Series response exposes absolute image/mask paths: [`backend/app/services/discovery.py:147`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/services/discovery.py#L147), [`backend/app/services/discovery.py:148`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/app/services/discovery.py#L148)
  - Frontend contract currently includes those fields: [`frontend/src/services/api.ts:14`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/services/api.ts#L14), [`frontend/src/services/api.ts:40`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/services/api.ts#L40)
- `impact`:
  - Leaks server filesystem layout to clients.
  - Increases attack surface and operational sensitivity.
- `recommendation`:
  - Remove absolute paths from public responses.
  - Use opaque IDs and server-side resolution only.
  - Keep paths only in server logs/debug endpoints guarded by auth + debug flag.
- `file`: `backend/app/services/discovery.py`, `frontend/src/services/api.ts`
- `line`: `68`, `147`, `148`, `14`, `40`
- `milestone`: `M1`

### 3) `AUD-2026-03-05-P1-003`
- `id`: `AUD-2026-03-05-P1-003`
- `severity`: `P1`
- `skill`: `web-performance-optimization`, `clean-code`
- `area`: slice-fetch smoothness / request lifecycle
- `evidence`:
  - Slice fetches start on each key change with no request cancellation: [`frontend/src/components/viewer/SliceView.tsx:127`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/components/viewer/SliceView.tsx#L127), [`frontend/src/components/viewer/SliceView.tsx:132`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/components/viewer/SliceView.tsx#L132), [`frontend/src/components/viewer/SliceView.tsx:148`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/components/viewer/SliceView.tsx#L148)
  - Current approach prevents stale UI commit but does not abort in-flight network work.
- `impact`:
  - Under rapid scroll, requests accumulate and can cause stutter/jank even when median latency is good.
  - Matches observed “fetching slice” interruptions.
- `recommendation`:
  - Introduce `AbortController` per axis request.
  - Coalesce wheel events (`requestAnimationFrame` or short throttle).
  - Add small client-side slice cache for adjacent indices.
  - Track fetch state by `(axis,index,ww,wl,layers)` and reuse if present.
- `file`: `frontend/src/components/viewer/SliceView.tsx`
- `line`: `127`, `132`, `148`
- `milestone`: `M8` (proposed `M8.1` hardening)

### 4) `AUD-2026-03-05-P2-001`
- `id`: `AUD-2026-03-05-P2-001`
- `severity`: `P2`
- `skill`: `docker-expert`
- `area`: container hardening
- `evidence`:
  - Runtime image runs as root (no `USER` directive): [`Dockerfile:9`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/Dockerfile#L9), [`Dockerfile:26`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/Dockerfile#L26)
  - No Dockerfile `HEALTHCHECK`; health is only in compose file.
- `impact`:
  - Weaker container security baseline for non-compose deployments.
- `recommendation`:
  - Add non-root runtime user (`UID/GID`), drop root.
  - Add Dockerfile-level `HEALTHCHECK`.
  - Consider read-only root FS + tmpfs for writable paths.
- `file`: `Dockerfile`
- `line`: `9`, `26`
- `milestone`: `M12`

### 5) `AUD-2026-03-05-P2-002`
- `id`: `AUD-2026-03-05-P2-002`
- `severity`: `P2`
- `skill`: `clean-code`, `docker-expert`
- `area`: dependency reproducibility / supply-chain drift
- `evidence`:
  - Backend dependencies are unpinned: [`backend/requirements.txt:1`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/requirements.txt#L1)-[`backend/requirements.txt:9`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/backend/requirements.txt#L9)
- `impact`:
  - Builds can change unexpectedly over time.
  - Harder to reproduce and patch securely.
- `recommendation`:
  - Pin exact versions (or constrained ranges) and generate lockfile (`pip-compile` or equivalent).
  - Add scheduled dependency refresh policy.
- `file`: `backend/requirements.txt`
- `line`: `1-9`
- `milestone`: `M0`/`M12` hardening

### 6) `AUD-2026-03-05-P2-003`
- `id`: `AUD-2026-03-05-P2-003`
- `severity`: `P2`
- `skill`: `web-performance-optimization`
- `area`: frontend bundle size / initial load
- `evidence`:
  - Production build warning: `dist/assets/index-*.js 1,568.57 kB (gzip 453.91 kB)`.
  - Vite warns about chunks larger than 500 kB.
- `impact`:
  - Slower cold load and interaction on constrained links/CPUs.
- `recommendation`:
  - Lazy-load `Surface3DView` and three.js stack per route/panel.
  - Split vendor chunks (`manualChunks`) and defer 3D libs until needed.
- `file`: build artifact (`vite build` output)
- `line`: n/a (build-time diagnostic)
- `milestone`: `M9`/`M11`

### 7) `AUD-2026-03-05-P3-001`
- `id`: `AUD-2026-03-05-P3-001`
- `severity`: `P3`
- `skill`: `api-security-best-practices`
- `area`: token storage strategy
- `evidence`:
  - Token persistence in `localStorage`: [`frontend/src/services/api.ts:123`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/services/api.ts#L123), [`frontend/src/services/api.ts:128`](/home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend/src/services/api.ts#L128)
- `impact`:
  - If XSS occurs, token exfiltration risk increases.
- `recommendation`:
  - Prefer short-lived token in memory for local mode.
  - For shared deployments, move to HTTP-only cookie or short-lived JWT + refresh flow.
- `file`: `frontend/src/services/api.ts`
- `line`: `123`, `128`
- `milestone`: `M5`/`M6` hardening

## Release Gate
Status: **Not Ready**

### Blocking Items
1. `P1` session-isolation issue in backend slice/mesh state (`AUD-2026-03-05-P1-001`).
2. `P1` absolute filesystem path exposure in API responses (`AUD-2026-03-05-P1-002`).
3. `P1` slice-fetch lifecycle smoothness gap for rapid navigation (`AUD-2026-03-05-P1-003`).
4. Native container runtime verification remains external due missing `docker`/`podman` on this host.

## Notes
- Slice latency probe on this host (authenticated): median `51.2 ms`, p95 `73.3 ms` over 20 samples.
- Despite good backend timings, frontend request lifecycle still needs cancellation/coalescing to remove visible fetch interruptions during fast scroll.
