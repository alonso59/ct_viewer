@echo off
REM Build the image from this checkout and run it (no make needed). Ctrl-C stops.
REM Override paths/port first if needed: set DATA_DIR=... & set DERIVED_DIR=... & set WORKSPACE_DIR=... & set PORT=...
setlocal
if not defined DATA_DIR (
  echo Set DATA_DIR to your existing DICOM source folder before running this script.
  exit /b 1
)
if not defined DERIVED_DIR set "DERIVED_DIR=%~dp0build\derived"
if not defined WORKSPACE_DIR set "WORKSPACE_DIR=%~dp0.workspace"
if not defined PORT set "PORT=5176"

cd /d "%~dp0"
if not exist "%DERIVED_DIR%" mkdir "%DERIVED_DIR%"
if not exist "%WORKSPACE_DIR%" mkdir "%WORKSPACE_DIR%"

if not exist "%DATA_DIR%\." (
  echo DATA_DIR must point to an existing source folder.
  exit /b 1
)

REM free the name and the port from an earlier run of this script
docker rm -f ct_viewer_local >nul 2>&1

docker build -t ct_viewer:local . || (echo Build failed. & pause & exit /b 1)
echo Open http://localhost:%PORT%
REM data is read-only (:ro); converted datasets go to the writable /derived
docker run --rm --name ct_viewer_local -p %PORT%:8000 ^
  -v "%DATA_DIR%:/data:ro" -v "%DERIVED_DIR%:/derived" -v "%WORKSPACE_DIR%:/workspace" ^
  -e DATA_HOST=/data -e ALLOWED_DATA_ROOTS=/data -e ALLOWED_DERIVED_ROOTS=/derived ^
  ct_viewer:local
if errorlevel 1 pause
