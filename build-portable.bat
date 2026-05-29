@echo off
REM build-portable.bat — Build the portable Radiology WebUI executable (Windows)
REM
REM Requirements:
REM   - Node.js (npm) on PATH
REM   - Python with backend requirements + pyinstaller installed
REM
REM Usage:
REM   build-portable.bat
REM   build-portable.bat --skip-frontend

setlocal enabledelayedexpansion

set PROJECT_ROOT=%~dp0
set PROJECT_ROOT=%PROJECT_ROOT:~0,-1%
set FRONTEND_DIR=%PROJECT_ROOT%\frontend
set BACKEND_DIR=%PROJECT_ROOT%\backend
set DIST_DIR=%PROJECT_ROOT%\dist\portable
set BUILD_DIR=%PROJECT_ROOT%\build\pyinstaller
set SKIP_FRONTEND=0

for %%a in (%*) do (
  if "%%a"=="--skip-frontend" set SKIP_FRONTEND=1
)

echo ======================================
echo  Radiology WebUI — Portable Build
echo ======================================
echo.

REM ── 1. Frontend ──────────────────────────────────────────────────────────
if %SKIP_FRONTEND%==0 (
  echo [1/3] Building frontend...
  cd "%FRONTEND_DIR%"
  call npm ci
  if errorlevel 1 goto :error
  call npm run build
  if errorlevel 1 goto :error
  echo       Frontend built ^-^> frontend\dist\
) else (
  echo [1/3] Skipping frontend build
  if not exist "%FRONTEND_DIR%\dist" (
    echo       ERROR: frontend\dist not found.
    goto :error
  )
)

REM ── 2. PyInstaller ───────────────────────────────────────────────────────
echo.
echo [2/3] Running PyInstaller...
cd "%PROJECT_ROOT%"

pyinstaller --version >nul 2>&1
if errorlevel 1 (
  echo       pyinstaller not found -- installing...
  pip install pyinstaller
)

pyinstaller ^
  "%BACKEND_DIR%\radiology-webui.spec" ^
  --distpath "%DIST_DIR%" ^
  --workpath "%BUILD_DIR%" ^
  --noconfirm
if errorlevel 1 goto :error

echo       Executable built ^-^> %DIST_DIR%\radiology-webui.exe

REM ── 3. Launcher scripts ──────────────────────────────────────────────────
echo.
echo [3/3] Writing launcher scripts...

(
echo @echo off
echo REM Start Radiology WebUI
echo REM Usage: start.bat [--data-dir C:\path\to\dataset] [--port 8000]
echo set DIR=%%~dp0
echo "%%DIR%%radiology-webui.exe" %%*
) > "%DIST_DIR%\start.bat"

(
echo @echo off
echo REM Start with a specific dataset folder
echo REM Edit DATA_DIR or drag a folder onto this script
echo set DATA_DIR=%%1
echo set DIR=%%~dp0
echo if "%%DATA_DIR%%"=="" (
echo   "%%DIR%%radiology-webui.exe"
echo ^) else (
echo   "%%DIR%%radiology-webui.exe" --data-dir "%%DATA_DIR%%"
echo ^)
) > "%DIST_DIR%\start-with-data.bat"

REM ── Done ─────────────────────────────────────────────────────────────────
echo.
echo ======================================
echo  Build complete!
echo  Output: %DIST_DIR%\
echo.
echo  Run:    %DIST_DIR%\start.bat
echo    or:   %DIST_DIR%\start-with-data.bat C:\path\to\dataset
echo ======================================
goto :eof

:error
echo.
echo ERROR: Build failed. See output above.
exit /b 1
