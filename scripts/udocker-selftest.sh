#!/usr/bin/env bash
# REL-07 local simulation: run the built image under udocker as a non-root user without sudo,
# inside a throwaway Linux container, and pass TST-10 there (docs/ops/DEPLOYMENT.md §udocker).
#
#   make image && make fixtures && scripts/udocker-selftest.sh      # = make udocker-selftest
#
# Per execution mode (EXECMODES, default "P1 F3"): install udocker from ./udocker.py +
# ./udocker-1.3.17 (no system installs), `udocker load` the `docker save` tar, `./rw up` (which runs
# scripts/udocker-run.sh), scripts/container_smoke.py (health, SPA, one item viewable), source
# hashes unchanged (R1), `./rw stop`.
# Only Docker is needed on the host; files go in through named volumes + `docker cp` (no bind mounts).
# The outer "server" is python:3.12-slim plus curl (udocker needs curl or pycurl even offline; a
# typical server has it) and a passwd entry for the test user (F3 needs a username, as on a real
# server), built once as rw-udocker-host:py3.12-u10001. The test user has uid 10001, no sudo.
# Env: IMAGE (default radiology-workbench:<pyproject version>), OUTER (outer image, same arch as
# IMAGE), EXECMODES, OUTER_OPTS (extra `docker run` options for the outer container only),
# UDOCKER_TARBALL (udocker engine tarball; downloaded once into build/udocker-selftest/ if unset).
# Internal: scripts/udocker-selftest.sh --inner MODE runs inside the outer container.
set -euo pipefail

if [[ "${1:-}" == --inner ]]; then
  : "${IMAGE:?set by the outer run (-e IMAGE)}"
  mode="$2"; home="$HOME"; app="$home/repo"; data="$home/data/Dataset900"; port=8123
  ok() { echo "ok   [$mode] $*"; }
  [[ "$(id -u)" != 0 ]] || { echo "FAIL must not run as root" >&2; exit 1; }
  ! command -v sudo >/dev/null || { echo "FAIL sudo present" >&2; exit 1; }
  ok "uid $(id -u), no sudo"
  cd "$app"
  export UDOCKER_TARBALL="$home/udocker-tarball.tar.gz" RW_CONTAINER="rw-$mode"
  python3 udocker.py install >/dev/null 2>&1 || python3 udocker.py install
  ok "udocker installed from ./udocker.py into $app/.udocker"
  printf 'DATA_HOST=%s\nPORT=%s\nRW_VERSION=%s\nUDOCKER_EXECMODE=%s\n' \
    "$data" "$port" "${IMAGE#*:}" "$mode" > .env
  python3 udocker.py images | grep -q "${IMAGE}" || ./rw update "$home/rw.tar"
  python3 udocker.py images | grep -q "${IMAGE}" || { echo "FAIL udocker load" >&2; exit 1; }
  ok "./rw update (udocker load) $IMAGE"
  before="$(cd "$data" && find . -type f -print0 | sort -z | xargs -0 sha256sum)"
  t0=$(date +%s)
  RW_WAIT=300 ./rw up || { tail -n 60 .rw/rw.log >&2; exit 1; }
  ok "./rw up healthy after $(( $(date +%s) - t0 )) s"
  t0=$(date +%s)
  ./rw smoke || { tail -n 60 .rw/rw.log >&2; ./rw stop; exit 1; }
  ok "TST-10 smoke in $(( $(date +%s) - t0 )) s"
  ./rw status >/dev/null
  after="$(cd "$data" && find . -type f -print0 | sort -z | xargs -0 sha256sum)"
  ./rw stop
  [[ "$before" == "$after" ]] || { echo "FAIL [$mode] source files changed (R1)" >&2; exit 1; }
  ok "$(printf '%s\n' "$before" | wc -l | tr -d ' ') source files unchanged (R1)"
  ./rw status >/dev/null && { echo "FAIL [$mode] still running after stop" >&2; exit 1; }
  ! grep -qs container_app /proc/[0-9]*/cmdline || { echo "FAIL [$mode] app process left after stop" >&2; exit 1; }
  ok "stopped"
  exit 0
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/backend/pyproject.toml")"
image="${IMAGE:-radiology-workbench:$version}"
outer="${OUTER:-rw-udocker-host:py3.12-u10001}"
modes="${EXECMODES:-P1 F3}"
cache="$repo/build/udocker-selftest"
fixtures="$repo/.fixtures/synthetic/Dataset900"
tarball_url="$(sed -n 's/.*"\(https:.*udocker-englib-[0-9.]*\.tar\.gz\)".*/\1/p' \
  "$repo/udocker-1.3.17/udocker/config.py" | head -n 1)"
[[ -d "$fixtures" ]] || { echo "missing $fixtures (run: make fixtures)" >&2; exit 2; }
docker image inspect "$image" >/dev/null 2>&1 || { echo "missing image $image (run: make image)" >&2; exit 2; }

mkdir -p "$cache"
if [[ -z "${OUTER:-}" ]] && ! docker image inspect "$outer" >/dev/null 2>&1; then
  printf 'FROM python:3.12-slim\nRUN apt-get update && apt-get install -y --no-install-recommends curl \\\n && rm -rf /var/lib/apt/lists/* \\\n && useradd -u 10001 -M -d /home/tester tester\n' \
    | docker build -q -t "$outer" - >/dev/null
fi
tarball="${UDOCKER_TARBALL:-$cache/$(basename "$tarball_url")}"
if [[ ! -s "$tarball" ]]; then  # test-time download of the udocker engines (proot, patchelf...)
  echo "fetching $tarball_url" >&2
  curl -fsSL -o "$tarball.part" "$tarball_url" && mv "$tarball.part" "$tarball"
fi

name="rw-udst-$$"; vol="$name-home"; uid=10001
# shellcheck disable=SC2329  # invoked by the EXIT trap
cleanup() { docker rm -f "$name-seed" >/dev/null 2>&1 || true; docker volume rm -f "$vol" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Stage the files a server checkout needs: launcher, run script, smoke, udocker, version.
stage="$cache/stage"; rm -rf "$stage"; mkdir -p "$stage/repo/scripts" "$stage/repo/backend" "$stage/data"
cp -R "$repo/udocker.py" "$repo/udocker-1.3.17" "$repo/rw" "$repo/.env.example" "$stage/repo/"
cp "$repo/scripts/udocker-run.sh" "$repo/scripts/container_smoke.py" "$repo/scripts/oci_tar_normalize.py" "$repo/scripts/udocker-selftest.sh" "$stage/repo/scripts/"
cp "$repo/backend/pyproject.toml" "$stage/repo/backend/"
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$tarball" "$stage/udocker-tarball.tar.gz"
cp -R "$fixtures" "$stage/data/Dataset900"

docker create --name "$name-seed" -v "$vol:/home/tester" "$outer" >/dev/null
docker cp -q "$stage/." "$name-seed:/home/tester"
echo "saving $image into the test volume" >&2
docker save "$image" | docker run --rm -i -v "$vol:/home/tester" "$outer" sh -c 'cat > /home/tester/rw.tar'
docker run --rm -v "$vol:/home/tester" "$outer" chown -R "$uid:$uid" /home/tester

read -r -a extra <<< "${OUTER_OPTS:-}"
status=0; summary=()
for mode in $modes; do
  echo "== udocker exec mode $mode" >&2
  if docker run --rm --user "$uid:$uid" -e HOME=/home/tester -e IMAGE="$image" \
      ${extra[@]+"${extra[@]}"} -v "$vol:/home/tester" -w /home/tester "$outer" \
      bash /home/tester/repo/scripts/udocker-selftest.sh --inner "$mode"; then
    summary+=("$mode pass")
  else
    summary+=("$mode FAIL"); status=1
  fi
done
printf 'udocker selftest (%s, outer %s%s): %s\n' "$image" "$outer" "${OUTER_OPTS:+ $OUTER_OPTS}" "$(IFS=,; echo "${summary[*]}")"
exit $status
