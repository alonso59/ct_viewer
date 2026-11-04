#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cd "$PROJECT_DIR"
"$PROJECT_DIR/start.sh"
exec /home/alonso/.local/bin/claude --model qwen-nninteractive --effort medium "$@"
