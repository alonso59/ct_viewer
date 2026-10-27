#!/usr/bin/env bash
# Container smoke under Docker, plus the image gates:
#   image size <= 1.5 GB · IBSI phantom smoke in the image
#   empty ALLOWED_DATA_ROOTS refuses to start · runs as an arbitrary UID
#   health, SPA, import + one item viewable · source files unchanged (R1)
#
#   make fixtures && make image && scripts/container-smoke.sh
#
# udocker (remote): start with scripts/udocker-run.sh, then
#   python3 scripts/container_smoke.py --url http://127.0.0.1:$PORT --root $DATA_HOST
# Env: IMAGE (default radiology-workbench:<backend/pyproject.toml version>), DATA_ROOT (default the synthetic fixtures),
# SMOKE_PORT (default 8099), SMOKE_UID (default 12345).
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/backend/pyproject.toml")"
image="${IMAGE:-radiology-workbench:$version}"
root="${DATA_ROOT:-$repo/.fixtures/synthetic/Dataset900}"
port="${SMOKE_PORT:-8099}"
max_bytes=1500000000
[[ -d "$root" ]] || { echo "missing data root $root (run: make fixtures)" >&2; exit 2; }
root="$(cd "$root" && pwd)"

name="rw-smoke-$$"
uid="${SMOKE_UID:-12345}"
# Named volumes seeded with `docker cp`, not bind mounts: works on any Docker host (remote
# contexts, VMs without host shares). The data path inside the container is /data/<root name>.
croot="/data/$(basename "$root")"
cleanup() {
  docker rm -f "$name" "$name-empty" "$name-seed" >/dev/null 2>&1 || true
  docker volume rm -f "$name-ws" "$name-data" >/dev/null 2>&1 || true
}
trap cleanup EXIT
pass() { echo "ok   $*"; }
fail() { echo "FAIL $*" >&2; exit 1; }

# Uncompressed root filesystem (`docker image inspect .Size` is the compressed content size
# under the containerd image store).
size="$(docker run --rm "$image" du -sxb / | cut -f1)"
[[ "$size" -le "$max_bytes" ]] || fail "image size $size > $max_bytes"
pass "image size $((size / 1000000)) MB uncompressed <= 1500 MB"

docker run --rm "$image" python -m tools.spikes.ibsi_phantom_smoke >/dev/null \
  || fail "IBSI phantom smoke in the image"
pass "IBSI phantom smoke in the image"

docker run -d --name "$name-empty" -e ALLOWED_DATA_ROOTS= "$image" >/dev/null
for _ in $(seq 60); do
  [[ "$(docker inspect -f '{{.State.Running}}' "$name-empty")" == false ]] && break
  sleep 0.5
done
code="$(docker inspect -f '{{.State.Running}} {{.State.ExitCode}}' "$name-empty")"
[[ "$code" == "false "* && "$code" != "false 0" ]] || fail "empty ALLOWED_DATA_ROOTS still running/ok: $code"
logs="$(docker logs "$name-empty" 2>&1)"
[[ "$logs" == *ALLOWED_DATA_ROOTS* ]] || fail "refusal does not name ALLOWED_DATA_ROOTS: $logs"
pass "empty ALLOWED_DATA_ROOTS refuses to start (exit ${code#false })"

docker create --name "$name-seed" -v "$name-data:/data" "$image" >/dev/null
docker cp -q "$root" "$name-seed:$croot"
docker run --rm -u 0 -v "$name-ws:/workspace" "$image" chown "$uid:$uid" /workspace
hashes() {
  docker run --rm -v "$name-data:/data:ro" "$image" \
    sh -c 'cd /data && find . -type f -print0 | sort -z | xargs -0 sha256sum'
}
before="$(hashes)"
docker run -d --name "$name" --user "$uid:$uid" -p "127.0.0.1:$port:8000" \
  -v "$name-ws:/workspace" -v "$name-data:/data:ro" -e ALLOWED_DATA_ROOTS="$croot" \
  "$image" >/dev/null
pass "started as arbitrary uid $uid"
segmentation_args=()
[[ -n "${DATA_ROOT:-}" ]] || segmentation_args+=(--segmentations)
python3 "$repo/scripts/container_smoke.py" --url "http://127.0.0.1:$port" --root "$croot" "${segmentation_args[@]}" \
  || { docker logs --tail 40 "$name" >&2; fail "container_smoke.py"; }

for _ in $(seq 90); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$name")"
  [[ "$health" == starting ]] || break
  sleep 1
done
[[ "$health" == healthy ]] || fail "Docker HEALTHCHECK: $health"
pass "Docker HEALTHCHECK healthy"

after="$(hashes)"
[[ "$before" == "$after" ]] || fail "source files changed (R1)"
pass "$(printf '%s\n' "$before" | wc -l | tr -d ' ') source files unchanged (R1)"
echo "container smoke pass: $image"
