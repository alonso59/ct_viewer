# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Radiology WebUI
#
# Build from the project root:
#   cd radioccrcc-webui
#   pyinstaller backend/radiology-webui.spec --distpath dist/portable --workpath build/pyinstaller
#
# The frontend must be built first (npm run build → frontend/dist/)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

HERE = Path(SPECPATH)                         # backend/
ROOT = HERE.parent                            # radioccrcc-webui/
FRONTEND_DIST = ROOT / "frontend" / "dist"

if not FRONTEND_DIST.is_dir():
    raise SystemExit(
        f"\n[ERROR] Frontend build not found at {FRONTEND_DIST}\n"
        "Run 'npm run build' inside frontend/ first.\n"
    )

# Collect ALL binaries, data files, and submodule names for packages that
# contain compiled C/Cython extensions.  Plain hiddenimports entries are not
# enough — PyInstaller only follows Python imports; it does NOT copy .so/.pyd
# extension binaries unless collect_all (or collect_dynamic_libs) is used.
_skimage_datas,   _skimage_bins,   _skimage_hidden   = collect_all('skimage')
_trimesh_datas,   _trimesh_bins,   _trimesh_hidden   = collect_all('trimesh')
_scipy_sp_datas,  _scipy_sp_bins,  _scipy_sp_hidden  = collect_all('scipy.sparse')
# scipy.sparse.csgraph has Cython extensions used by trimesh.split()
_scipy_cg_datas,  _scipy_cg_bins,  _scipy_cg_hidden  = collect_all('scipy.sparse.csgraph')
# scipy.spatial is needed by trimesh geometry helpers
_scipy_st_datas,  _scipy_st_bins,  _scipy_st_hidden  = collect_all('scipy.spatial')

a = Analysis(
    [str(HERE / "app" / "__main__.py")],
    pathex=[str(HERE)],
    binaries=(
        _skimage_bins + _trimesh_bins + _scipy_sp_bins + _scipy_cg_bins + _scipy_st_bins
    ),
    datas=[
        # Bundle the compiled frontend as static/
        (str(FRONTEND_DIST), "static"),
    ] + _skimage_datas + _trimesh_datas + _scipy_sp_datas + _scipy_cg_datas + _scipy_st_datas,
    hiddenimports=(
        _skimage_hidden + _trimesh_hidden + _scipy_sp_hidden + _scipy_cg_hidden + _scipy_st_hidden +
    [  # ── explicit extras ──────────────────────────────────────────────────
        # uvicorn dynamic loaders
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.off",
        "uvicorn.lifespan.on",
        # FastAPI / Starlette
        "fastapi",
        "fastapi.routing",
        "starlette",
        "starlette.routing",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.responses",
        "starlette.staticfiles",
        # Pydantic v2
        "pydantic",
        "pydantic.deprecated.class_validators",
        # Science stack
        "nibabel",
        "nibabel.loadsave",
        "nibabel.nifti1",
        "nibabel.nifti2",
        "numpy",
        "numpy.core",
        "skimage",
        "skimage.measure",
        "skimage.measure._marching_cubes_lewiner",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        # 3D mesh
        "trimesh",
        "trimesh.exchange",
        "trimesh.exchange.export",
        "trimesh.exchange.gltf",
        # multipart
        "multipart",
        "python_multipart",
        # App modules (ensure all sub-packages are included)
        "app.api.cases",
        "app.api.curation",
        "app.api.dataset_browser",
        "app.api.datasets",
        "app.api.mesh",
        "app.api.review",
        "app.api.settings",
        "app.api.slices",
        "app.api.workspace",
        "app.middleware.auth",
        "app.models.curation",
        "app.models.database",
        "app.models.dataset",
        "app.models.dataset_browser",
        "app.models.review",
        "app.models.settings",
        "app.models.workspace",
        "app.services.byte_lru",
        "app.services.curation_store",
        "app.services.database",
        "app.services.dataset_browser",
        "app.services.discovery",
        "app.services.mask_loader",
        "app.services.mesh_cache",
        "app.services.mesh_generator",
        "app.services.nifti_loader",
        "app.services.numpy_loader",
        "app.services.path_resolver",
        "app.services.review_apply",
        "app.services.runtime_cache",
        "app.services.settings_store",
        "app.services.slice_cache",
        "app.services.slice_renderer",
        "app.services.state_dir",
        "app.services.volume_cache",
        "app.services.workspace",
        "app.services.workspace_store",
    ]),
    hookspath=[],
    # Note: collect_all already pulled in the scientific-stack modules above.
    hooksconfig={},
    runtime_hooks=[],
    # unittest is kept (not excluded) because scipy.sparse.csgraph imports numpy.testing
    # at load time, which in turn imports unittest.  Excluding it causes a
    # ModuleNotFoundError when trimesh calls csgraph.connected_components().
    excludes=["tkinter", "test", "jupyter", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="radiology-webui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,        # keep console visible so the user sees the server URL
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
