#!/usr/bin/env bash
# Run the image under udocker from the same .env as docker-compose.yml (OPS-09, ADR-0007).
# This script is the single source of the udocker run command; keep it equivalent to compose.
#
#   scripts/udocker-run.sh [--env-file FILE] [--dry-run]
#
# Once per server (udocker cannot build; see docs/ops/DEPLOYMENT.md):
#   udocker load -i rw-3.0.0.tar          # the container `rw` is created on first run
#
# Env overrides (not from .env): UDOCKER (command, default `udocker` or ./udocker.py),
# RW_CONTAINER (container name, default rw).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo/.env"
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) env_file="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -f "$env_file" ]] || { echo "missing $env_file (copy .env.example)" >&2; exit 2; }
env_dir="$(cd "$(dirname "$env_file")" && pwd)"

# Parse KEY=VALUE lines like compose: `#` comments, optional quotes, no interpolation, no eval.
# Bash 3.2 compatible (no associative arrays): parallel arrays keys/vals, last value wins.
keys=(); vals=()
lookup() { local i; for ((i = ${#keys[@]} - 1; i >= 0; i--)); do
  [[ "${keys[i]}" == "$1" ]] && { printf '%s' "${vals[i]}"; return 0; }; done; return 1; }
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" || "$line" == \#* ]] && continue
  line="${line#export }"
  [[ "$line" == *=* ]] || { echo "bad line in $env_file: $line" >&2; exit 2; }
  key="${line%%=*}"; key="${key%"${key##*[![:space:]]}"}"
  val="${line#*=}"; val="${val#"${val%%[![:space:]]*}"}"
  if [[ "$val" =~ ^\"(.*)\"[[:space:]]*(#.*)?$ || "$val" =~ ^\'(.*)\'[[:space:]]*(#.*)?$ ]]; then
    val="${BASH_REMATCH[1]}"
  else
    val="${val%%[[:space:]]#*}"; val="${val%"${val##*[![:space:]]}"}"
  fi
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "bad key in $env_file: $key" >&2; exit 2; }
  keys+=("$key"); vals+=("$val")
done < "$env_file"
get() { local v; v="$(lookup "$1")" || v=""; printf '%s' "${v:-${2:-}}"; }

data_host="$(get DATA_HOST)"
[[ "$data_host" == /* ]] || { echo "DATA_HOST must be an absolute path in $env_file" >&2; exit 2; }
workspace_host="$(get WORKSPACE_HOST ./workspace)"
[[ "$workspace_host" == /* ]] || workspace_host="$env_dir/${workspace_host#./}"  # compose: relative to .env dir
port="$(get PORT 8000)"
version="$(get RW_VERSION 3.0.0)"
execmode="$(get UDOCKER_EXECMODE)"
name="${RW_CONTAINER:-rw}"
image="radiology-workbench:$version"

# Same overrides as compose `environment:`; HOST differs because udocker shares the host network.
host="$(get HOST 127.0.0.1)"
fixed=(
  "CONTAINER_MODE=1"
  "HOST=$host"
  "PORT=$port"
  "WORKSPACE_ROOT=/workspace"
  "ALLOWED_DATA_ROOTS=$(get ALLOWED_DATA_ROOTS "$data_host")"
  "PUBLIC_BASE_URL=$(get PUBLIC_BASE_URL "http://localhost:$port")"
)
fixed_keys=" CONTAINER_MODE HOST PORT WORKSPACE_ROOT ALLOWED_DATA_ROOTS PUBLIC_BASE_URL "

if [[ -n "${UDOCKER:-}" ]]; then read -r -a ud <<< "$UDOCKER"
elif command -v udocker >/dev/null; then ud=(udocker)
else ud=(python3 "$repo/udocker.py"); fi

args=(run --volume="$workspace_host:/workspace" --volume="$data_host:$data_host")
# Every other .env key reaches the container, like compose `env_file:` (last duplicate wins).
seen=" "
for ((i = ${#keys[@]} - 1; i >= 0; i--)); do
  k="${keys[i]}"
  [[ "$fixed_keys$seen" == *" $k "* ]] && continue
  seen+="$k "; args+=(--env="$k=${vals[i]}")
done
for kv in "${fixed[@]}"; do args+=(--env="$kv"); done
args+=("$name")

if [[ $dry_run -eq 1 ]]; then
  printf '%q ' "${ud[@]}" "${args[@]}"; echo
  exit 0
fi

mkdir -p "$workspace_host"
[[ -w "$workspace_host" ]] || { echo "workspace not writable: $workspace_host (OPS-06)" >&2; exit 2; }
if ! "${ud[@]}" inspect "$name" >/dev/null 2>&1; then
  "${ud[@]}" create --name="$name" "$image"
fi
[[ -z "$execmode" ]] || "${ud[@]}" setup --execmode="$execmode" "$name"
echo "Radiology Workbench on http://$host:$port (forward the port with VS Code)" >&2
exec "${ud[@]}" "${args[@]}"
