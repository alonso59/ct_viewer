# Open Milestones Closeout

Evidence date: 2026-08-04. Work was performed on `codex/upgrade`; `main` was not
modified, merged, or force-pushed.

## M12.3

**Exact criterion:** build `radiology-ui:1.0` with Docker or Podman, run it with
the dataset mounted read-only, and verify all application features at
`http://localhost:8000`.

**Status:** PASS. The task is checked in `AGENTS.md`.

**Files changed:** `AGENTS.md`. The synthetic verification dataset and scripts
were kept under ignored `.desktop-build/verification/m12/`; no dataset or patient
data was committed.

**Commands and results:**

```text
docker build --pull --no-cache --provenance=false --progress=plain -t radiology-ui:1.0 .
exit 0

docker run --rm -p 18002:8000 -e DATA_ROOT=/data -e ALLOWED_DATA_ROOTS=/data \
  -v <repo>/.desktop-build/verification/m12/data:/data:ro radiology-ui:1.0
exit 0
```

The smoke run returned `200` for health, read-only inspection, activation,
dataset, patient, series, React root, three PNG slice endpoints, and GLB labels
1, 2, and 3. The loaded synthetic NIfTI volume was `24 x 24 x 24`; all three
segmentation labels were discovered.

```text
axial PNG     7,408 bytes  c169b076b99e686ea8d89ab5e2e07f1ba7383ee2a50657558b0050d16f425df5
coronal PNG   3,073 bytes  09d736977919e3c262d65e838595fd6070fe2e1f8365882825fbb697a4c7e944
sagittal PNG  3,411 bytes  839790b94a73e8504cfff0a555e8aee50a7f85c4c3ee492262ed66c1f6dfb2aa
label 1 GLB  92,288 bytes  699c58d96b1f1337505eaf56b479dd58a7e40879b8d4ad406629d99ad0805df0
label 2 GLB  25,760 bytes  4052ed37a9fbeb45a0638998fa7baeed51e3e5b5d9c2f177dbda94881ca5d255
label 3 GLB   4,196 bytes  3b31a1bbd9a29a344057264af2439bca487e86cbf6c9c566758729162af5b243
```

**Blocker:** none.

## M12.4

**Exact criterion:** export the OCI image, load it into udocker, create the
`radio-ui` container, run it with the dataset mount, and verify the application
through the udocker runtime.

**Status:** PASS. The task is checked in `AGENTS.md`.

**Files changed:** `AGENTS.md`; ignored verification scripts only.

**Commands and results:**

```text
docker save -o radiology-ui_1.0-final.tar radiology-ui:1.0
udocker load -i radiology-ui_1.0-final.tar
udocker create --name=radio-ui-final radiology-ui-final:1.0
udocker run -p 18003:8000 -v <synthetic-data>:/data:ro radio-ui-final
all commands exit 0
```

The final run used udocker `1.3.17` with official execution library `1.2.11`.
Because WSL DrvFS caused a reproducible proot deadlock, udocker itself was hosted
in an ephemeral Linux filesystem while the repository remained read-only. The
same API, PNG, GLB, and React smoke matrix from M12.3 passed on port `18003`.

Generated image archive:

```text
radiology-ui_1.0-final.tar
bytes: 159,394,816
SHA-256: 773c7f45b8c819e78012cc7abff62f8764f96f197d8208d22374076313eeef4c
```

**Blocker:** none.

## M12.5

**Exact criterion:** verify that the final image size is no more than `1.5 GB`.

**Status:** PASS. The task is checked in `AGENTS.md`.

**Files changed:** `AGENTS.md` only.

**Command and result:** `docker image inspect radiology-ui:1.0` returned
`159,379,083` bytes (`152 MiB`), below the `1.5 GB` limit. Docker's shared-size
display reported `669 MB`, also below the limit.

```text
image ID / manifest:
sha256:102146ba102fe067beacaaba36ab581db0f3744bfbda7832369d0b1dc58ccfdb
```

**Blocker:** none.

## M14.8

**Exact criterion:** run backend tests under `conda activate ccrcc`, and run the
frontend test, lint, and production-build commands in udocker.

**Status:** PASS. The task is checked in `AGENTS.md`.

**Files changed:** `backend/requirements.txt`,
`backend/requirements-desktop.txt`, `backend/requirements-desktop.lock`,
`backend/app/services/path_policy.py`, `backend/app/services/review_apply.py`,
`frontend/src/pages/DatasetSelectorPage.test.tsx`, and `AGENTS.md`.

The lock changed only to add the test-client dependency `httpx2==2.9.1` and its
resolved dependencies (`httpcore2` and `truststore`) with hashes. The verification
also fixed two demonstrated Windows portability defects: preservation of the
outside-root exception and POSIX-form recycle metadata.

**Commands and results:**

```text
conda activate ccrcc
python -m pytest backend/tests -q
52 passed, 2 skipped in 3.76s; exit 0

udocker run ... node:22-slim ... npm ci
388 packages installed; exit 0
udocker run ... node:22-slim ... npm test
11 files, 40 tests passed; exit 0
udocker run ... node:22-slim ... npm run lint
exit 0
udocker run ... node:22-slim ... npm run build
1,552 modules transformed; built successfully; exit 0
```

All Node/npm commands executed inside udocker (`Node 22.23.2`, `npm 10.9.8`),
hosted in an ephemeral Linux filesystem to avoid the WSL DrvFS/proot deadlock.
No native or global Node installation was used.

The tests cover read-only inspection; absence of `.webui`, workspace, and cache
mutation; rejection of incomplete/unsupported datasets; classifications; default
and multiple allowed roots; traversal, symlink, and external-reference rejection;
five-entry deduplicated MRU persistence; Cases routing for canonical/converter
datasets; Patients routing for legacy/NIfTI/VOI datasets; and browser transport.

**Blocker:** none.

## M15.8

**Exact criterion:** run the complete Windows x64 release script and a manual
Windows 10/11 regression covering installer, single instance, native Browse ->
Inspect -> Open, existing Cases/Patients/Resume/2D/3D routes, parent-loss cleanup,
and absence of orphaned backends. The committed Windows workflow must pass before
M15 is complete.

**Status:** PARTIAL / OPEN. The committed workflow and static artifact audit pass;
the required manual runtime matrix has not yet been executed. M15.8 remains
unchecked in `AGENTS.md`.

**Files changed:** `.github/workflows/windows-desktop.yml`,
`scripts/build-desktop.ps1`, `backend/desktop-sidecar.spec`, Windows/Python/Rust
toolchain and lock files, `src-tauri/`, desktop backend/frontend bridge tests,
`docs/SRS.md`, and `AGENTS.md`. The PyInstaller spec correction was limited to
resolving `SPECPATH` as the spec directory. The SRS now explicitly preserves the
modern Cases worklist plus `scan_idx` selector and distinguishes it from the
legacy Patients previous/next-series controls. `CaseReviewPage.tsx` and
`ViewerPage.tsx` are unchanged from `origin/main` (matching Git object IDs).

**Windows workflow:**

- Passing run: [Windows Desktop run 30904476399](https://github.com/alonso59/radioccrcc-webui/actions/runs/30904476399)
- Job: `91976220414`, conclusion `success`
- Branch/head: `codex/upgrade` at `03fda21ce69620485c0f44e1bb38273097549f24`
- Artifact: `radiology-desktop-windows-x64`, ID `8891074316`, 382,400,392 bytes
- Artifact ZIP SHA-256: `3f19bd77ed6c346b90b8c6e6cdaf2bf9f4cbed19e40f060f206d1138b0818afe`
- Artifact expiry: 2026-08-18

The official script passed frontend tests (`11` files, `40` tests), lint and Vite
build (`1,552` modules), backend tests (`54 passed`), PyInstaller `6.21.0`, the
packaged sidecar health/auth/shutdown smoke, `cargo fmt --check`, `cargo check`,
`cargo clippy -- -D warnings`, Rust tests (`2 passed`), the Tauri release build,
NSIS packaging, portable ZIP assembly, manifest generation, and checksum audit.

**Generated artifacts and verified SHA-256 values:**

```text
Radiology-Desktop_2.2.0_x64-setup.exe
01384ad14312168f6b281122ae892684f486a60aec295d27729f740fe8e4915d

Radiology-Desktop_2.2.0_x64-portable.zip
bbce9d394a9a1889598095996a68baca5a9952c556790f10e35992f187304832

radiology-backend-x86_64-pc-windows-msvc.exe
7c3cd5a50c34c5e6241618910d831ac7e0322fc0f621fd1a6fb70c583b25631b

Radiology-Desktop.exe (inside portable ZIP)
22e3889efa1f2e733c133cd6014713aa712a5a4bc85057dc86608a6836291480

build-manifest.json
492a033e33f5152b97acf93c342ba692d73cd2e8a2917ac9c6570b3da9509819

toolchain-manifest.json
79d7bcd1707f0895b60c2a369e8c256bb9bba7b4080127ae7c8b8b3f4783ec8c

build.log
339f2917183fa61fdbdfa55638fd776262911cd5b40f7924b77b5feb096b75ef
```

The downloaded artifact ZIP digest matches GitHub. The portable ZIP contains
exactly `Radiology-Desktop.exe` and
`radiology-backend-x86_64-pc-windows-msvc.exe`; both are AMD64 PE files, their
hashes match the manifest, and no Node, Python, Conda, Rust, or source-runtime
files are present.

**Available Windows environment:** Windows 11 Pro `10.0.26200` build `26200`,
x64 OS and process, WebView2 `150.0.4078.105`. Windows 10 is unavailable and is
explicitly untested.

| # | Windows runtime acceptance item | Result |
| -: | --- | --- |
| 1 | Install generated NSIS installer | Pending explicit approval to run unsigned software |
| 2 | Start installed application | Pending item 1 |
| 3 | Sidecar starts automatically | Automated packaged-sidecar smoke passed; installed-app manual pending |
| 4 | Sidecar binds only to `127.0.0.1` | Automated config/Rust coverage passed; manual process/socket check pending |
| 5 | Frontend waits for `/api/health` | Automated frontend/Rust coverage passed; manual pending |
| 6 | Per-launch token works | Packaged-sidecar 401/authenticated-shutdown smoke passed; desktop-host manual pending |
| 7 | Token absent from normal logs | Handshake/build-log static audit passed; desktop-host manual pending |
| 8 | Native folder picker | Automated bridge coverage passed; manual pending |
| 9 | Inspect and activate through M14 | API/browser coverage passed; desktop manual pending |
| 10 | Route to Cases or Patients by kind | Frontend routing tests passed; desktop manual pending |
| 11 | Resume | Frontend coverage passed; desktop manual pending |
| 12 | Representative 2D volume | Browser regression passed; desktop manual pending |
| 13 | Overlay and window/level | Frontend regression passed and browser overlays rendered; desktop manual pending |
| 14 | Representative 3D mesh | Browser WebGL canvas rendered; desktop manual pending |
| 15 | Second launch is single-instance | Rust coverage passed; manual pending |
| 16 | Close terminates sidecar | Packaged-sidecar authenticated shutdown passed; full-app manual pending |
| 17 | Manual sidecar termination failure/watchdog state | Pending |
| 18 | Uninstall and no remaining process | Pending separate uninstall approval after installation tests |
| 19 | Extract and run portable ZIP | Static inventory passed; execution pending explicit approval |
| 20 | Portable needs no development runtimes | Static audit passed; execution pending |
| 21 | Dataset path containing spaces | Pending desktop runtime test |
| 22 | Dataset path containing Unicode | Pending desktop runtime test |
| 23 | Focused browser regression | PASS: manual server-visible path, read-only Inspect/Open, Patients route, three 512x512 PNG views, overlays, and 3D canvas |

**Remaining blockers:** action-time approval is required before launching the
downloaded unsigned installer or portable executable. Even after Windows 11
manual testing, Windows 10 will remain explicitly pending because no Windows 10
host is available. No DICOM, DICOM conversion, new segmentation, renderer,
global redesign, or M16 work was introduced.
