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

HERE = Path(SPECPATH)                         # backend/
ROOT = HERE.parent                            # radioccrcc-webui/
FRONTEND_DIST = ROOT / "frontend" / "dist"

if not FRONTEND_DIST.is_dir():
    raise SystemExit(
        f"\n[ERROR] Frontend build not found at {FRONTEND_DIST}\n"
        "Run 'npm run build' inside frontend/ first.\n"
    )

a = Analysis(
    [str(HERE / "app" / "__main__.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        # Bundle the compiled frontend as static/
        (str(FRONTEND_DIST), "static"),
    ],
    hiddenimports=[
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "jupyter", "IPython"],
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
