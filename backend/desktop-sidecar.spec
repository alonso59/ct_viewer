from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).parent.parent
backend_root = project_root / "backend"
hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("multipart")
    + collect_submodules("python_multipart")
    + collect_submodules("trimesh.exchange")
)

analysis = Analysis(
    [str(backend_root / "app" / "desktop_sidecar.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "notebook"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="radiology-backend-x86_64-pc-windows-msvc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
)
