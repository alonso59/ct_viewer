#!/usr/bin/env bash
# build-portable.sh — Build the portable Radiology WebUI executable (Linux / macOS)
#
# Requirements in the build environment:
#   - Node.js (npm) for the frontend build
#   - Python with all backend requirements + pyinstaller installed
#
# Usage:
#   ./build-portable.sh                      # output → dist/portable/
#   ./build-portable.sh --skip-frontend      # reuse an existing frontend/dist build
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_DIR="$PROJECT_ROOT/backend"
DIST_DIR="$PROJECT_ROOT/dist/portable"
BUILD_DIR="$PROJECT_ROOT/build/pyinstaller"

SKIP_FRONTEND=false
for arg in "$@"; do
  [[ "$arg" == "--skip-frontend" ]] && SKIP_FRONTEND=true
done

# ── Resolve Python interpreter ───────────────────────────────────────────────
# If PYINSTALLER_PYTHON is set, use it explicitly.
# Otherwise try conda base env, then fall back to whatever python3 is in PATH.
if [[ -n "${PYINSTALLER_PYTHON:-}" ]]; then
  PYTHON_BIN="$PYINSTALLER_PYTHON"
elif [[ -d "/Volumes/MAC2/opt/miniconda3/bin" ]]; then
  PYTHON_BIN="/Volumes/MAC2/opt/miniconda3/bin/python"
elif command -v conda &>/dev/null; then
  CONDA_ROOT="$(conda info --base 2>/dev/null)"
  PYTHON_BIN="$CONDA_ROOT/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
echo "  Python: $PYTHON_BIN ($(\"$PYTHON_BIN\" --version 2>&1))"

echo "======================================"
echo " Radiology WebUI — Portable Build"
echo "======================================"
echo ""

# ── 1. Frontend ──────────────────────────────────────────────────────────────
if [[ "$SKIP_FRONTEND" == false ]]; then
  echo "[1/3] Building frontend..."
  cd "$FRONTEND_DIR"
  npm ci
  npm run build
  echo "      Frontend built → frontend/dist/"
else
  echo "[1/3] Skipping frontend build (--skip-frontend)"
  if [[ ! -d "$FRONTEND_DIR/dist" ]]; then
    echo "      ERROR: frontend/dist not found. Run without --skip-frontend first."
    exit 1
  fi
fi

# ── 2. PyInstaller ───────────────────────────────────────────────────────────
echo ""
echo "[2/3] Running PyInstaller..."
cd "$PROJECT_ROOT"

# Locate pyinstaller binary: prefer the one next to the active python interpreter
# so we use the same env that has all backend deps installed.
PYTHON_DIR="$(dirname "$PYTHON_BIN")"
if [[ -x "$PYTHON_DIR/pyinstaller" ]]; then
  PYINSTALLER="$PYTHON_DIR/pyinstaller"
elif command -v pyinstaller &>/dev/null; then
  PYINSTALLER="pyinstaller"
else
  echo "      pyinstaller not found — installing into current Python env..."
  "$PYTHON_BIN" -m pip install pyinstaller
  PYINSTALLER="$PYTHON_DIR/pyinstaller"
fi

echo "      Using: $PYINSTALLER"
"$PYINSTALLER" \
  "$BACKEND_DIR/radiology-webui.spec" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --noconfirm

echo "      Executable built → $DIST_DIR/radiology-webui"

# ── 3. Wrapper scripts ───────────────────────────────────────────────────────
echo ""
echo "[3/3] Writing launcher scripts..."

cat > "$DIST_DIR/start.sh" << 'EOF'
#!/usr/bin/env bash
# Start Radiology WebUI
# Usage: ./start.sh [--data-dir /path/to/dataset] [--port 8000] [--no-browser]
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/radiology-webui" "$@"
EOF
chmod +x "$DIST_DIR/start.sh"

cat > "$DIST_DIR/start-with-data.sh" << 'EOF'
#!/usr/bin/env bash
# Drag a dataset folder onto this script, or edit DATA_DIR below.
DATA_DIR="${1:-}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$DATA_DIR" ]]; then
  echo "Usage: ./start-with-data.sh /path/to/dataset"
  exec "$DIR/radiology-webui"
else
  exec "$DIR/radiology-webui" --data-dir "$DATA_DIR"
fi
EOF
chmod +x "$DIST_DIR/start-with-data.sh"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "======================================"
echo " Build complete!"
echo " Output: $DIST_DIR/"
echo ""
echo " Run:    $DIST_DIR/start.sh"
echo "   or:   $DIST_DIR/start-with-data.sh /path/to/dataset"
echo "======================================"
