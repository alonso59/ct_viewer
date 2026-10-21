#!/bin/bash
#SBATCH --job-name=ct_viewer_dev
#SBATCH --account=ag_irumls_effland
#SBATCH --partition=intelsr_long
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=ct_viewer_dev-%j.log
#
# CT viewer dev server (backend + Vite) as a SLURM job.
#
#   ./dev_viewer.sh start      submit the job, wait for a node, print how to open it
#   ./dev_viewer.sh stop       cancel the running job
#   ./dev_viewer.sh restart    stop + start
#   ./dev_viewer.sh status     job state, node, health check, URL
#   ./dev_viewer.sh log [-f]   show the job log (-f to follow)
#
# Run these on the login node; they only talk to SLURM. The heavy part (`_run`)
# runs inside the job on a compute node, never on the login node.

set -euo pipefail

REPO=/home/gpinedo_hpc/Documents/ct_viewer
JOB_NAME=ct_viewer_dev
ACCOUNT=ag_irumls_effland
VITE_PORT=5174
API_PORT=8000
cd "$REPO"

log()  { echo "[$(date +%H:%M:%S)] $*"; }
die()  { echo "error: $*" >&2; exit 1; }

# "<jobid> <state> <node> <elapsed> <timelimit>" of our newest job, empty if none.
job_info() {
  squeue -u "$USER" -n "$JOB_NAME" -h -o "%i %T %N %M %l" | sort -n | tail -1
}

job_log() { echo "$REPO/${JOB_NAME}-$1.log"; }

print_access() {
  local node=$1
  cat <<EOF

  Node      : $node
  Target    : $node:$VITE_PORT   (Vite; proxies /api to the backend)

  Open it locally with VS Code port forwarding:
    Ports panel -> "Forward a Port" -> enter  $node:$VITE_PORT
    then open the forwarded http://localhost:<port> in your browser.
  (Opening http://$node:$VITE_PORT directly is blocked by Vite's host check.)
EOF
}

cmd_start() {
  local info
  info=$(job_info)
  if [[ -n $info ]]; then
    log "already have a job: $info"
    cmd_status
    return
  fi
  local jobid
  jobid=$(sbatch --parsable --account="$ACCOUNT" "$REPO/dev_viewer.sh" _run)
  log "submitted job $jobid ($JOB_NAME), waiting for a node..."
  local state node
  while :; do
    read -r _ state node _ _ <<<"$(squeue -j "$jobid" -h -o "%i %T %N %M %l" 2>/dev/null || true)"
    case ${state:-GONE} in
      RUNNING) break ;;
      PENDING|CONFIGURING) printf '.'; sleep 5 ;;
      *) echo; die "job $jobid ended early (state ${state:-GONE}); see $(job_log "$jobid")" ;;
    esac
  done
  echo
  log "job $jobid running on $node"
  print_access "$node"
  echo
  log "startup takes ~1 min (pip + npm); follow it with: $0 log -f"
}

cmd_stop() {
  local info jobid
  info=$(job_info)
  [[ -z $info ]] && { log "no $JOB_NAME job running"; return; }
  jobid=${info%% *}
  log "cancelling job $jobid"
  scancel "$jobid"
  while squeue -j "$jobid" -h 2>/dev/null | grep -q .; do sleep 2; done
  log "stopped"
}

cmd_status() {
  local info
  info=$(job_info)
  [[ -z $info ]] && { log "no $JOB_NAME job running (start with: $0 start)"; return; }
  local jobid state node elapsed limit
  read -r jobid state node elapsed limit <<<"$info"
  echo "  Job       : $jobid"
  echo "  State     : $state   (elapsed $elapsed / limit $limit)"
  echo "  Log       : $(job_log "$jobid")"
  if [[ $state == RUNNING ]]; then
    if curl -fsS -m 5 -H "Host: localhost" "http://$node:$VITE_PORT/api/v1/health" >/dev/null 2>&1; then
      echo "  Health    : OK (frontend + backend answering)"
    else
      echo "  Health    : not answering yet (still starting? check: $0 log)"
    fi
    print_access "$node"
  fi
}

cmd_log() {
  local info jobid file
  info=$(job_info)
  if [[ -n $info ]]; then
    jobid=${info%% *}
    file=$(job_log "$jobid")
  else
    file=$(ls -t "$REPO/${JOB_NAME}"-*.log 2>/dev/null | head -1 || true)
  fi
  [[ -n ${file:-} && -f $file ]] || die "no log file found yet"
  if [[ ${1:-} == -f ]]; then tail -n 50 -f "$file"; else tail -n 100 "$file"; fi
}

# ---- inside the SLURM job --------------------------------------------------
cmd_run() {
  [[ -n ${SLURM_JOB_ID:-} ]] || die "_run is for the SLURM job only; use: $0 start"

  log "job $SLURM_JOB_ID on $(hostname) (${SLURM_CPUS_PER_TASK:-?} cpus)"
  print_access "$(hostname -s)"
  echo

  export VITE_PORT VITE_HOST=0.0.0.0
  export VITE_API_PROXY="http://127.0.0.1:$API_PORT"
  export WORKSPACE_ROOT=../.workspace

  CONDA_BASE=/opt/software/easybuild-INTEL/software/Miniforge3/24.1.2-0
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  if ! conda env list | grep -qE '^\s*rw\s'; then
    log "[setup] creating conda env rw"
    conda create -y -n rw python=3.12
  fi
  conda activate rw

  log "[setup] installing backend[dev]"
  pip install -e './backend[dev]' -q

  if ! python3 udocker.py inspect rw-node >/dev/null 2>&1; then
    log "[setup] creating udocker node container"
    python3 udocker.py pull node:22-slim
    python3 udocker.py create --name=rw-node node:22-slim
  fi

  # npm ci wipes node_modules; only do it when the lockfile changed, so a restart
  # does not delete files another running server still has open (NFS ENOTEMPTY).
  local stamp=frontend/node_modules/.lock.sha256
  local want
  want=$(sha256sum frontend/package-lock.json | cut -d' ' -f1)
  if [[ ! -f $stamp || $(cat "$stamp") != "$want" ]]; then
    log "[setup] npm ci (lockfile changed)"
    python3 udocker.py run --hostenv --volume="$PWD/frontend:/app" --workdir=/app rw-node npm ci
    echo "$want" >"$stamp"
  else
    log "[setup] node_modules up to date, skipping npm ci"
  fi

  # Backend binds to localhost only; the browser reaches it through the Vite proxy.
  log "[run] backend on 127.0.0.1:$API_PORT"
  (cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT") &
  local backend_pid=$!

  log "[run] frontend on 0.0.0.0:$VITE_PORT"
  python3 udocker.py run --hostenv --volume="$PWD/frontend:/app" --workdir=/app rw-node npm run dev &
  local frontend_pid=$!

  trap 'log "[stop] shutting down"; kill $backend_pid $frontend_pid 2>/dev/null; pkill -P $$ 2>/dev/null' EXIT TERM INT
  # End the job as soon as either side dies, so `status` never shows a half-dead server.
  wait -n
  log "[run] a process exited; stopping job"
}

case ${1:-} in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  log)     shift; cmd_log "${1:-}" ;;
  _run)    cmd_run ;;
  *)       sed -n '10,19p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
