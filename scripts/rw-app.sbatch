#!/bin/bash
# Radiology Workbench as a scheduler job, for a cluster without a service node.
#
#   scripts/rw-app.sbatch start        submit the job, wait for a node, print how to open the app
#   scripts/rw-app.sbatch stop         cancel it (compute jobs it submitted keep running)
#   scripts/rw-app.sbatch status       job state, node, port and how to connect
#   scripts/rw-app.sbatch log [-f]     the job log
#   scripts/rw-app.sbatch credential   the session code of the running job
#
# Run these on a login node: they only talk to the scheduler. The app itself runs inside the
# job, never on the login node. Account, partition, wall time, CPUs and memory are settings in
# config/app-job.env of the state folder (scripts/rw-native.py), not in this file.

set -euo pipefail

if [[ -n ${SLURM_JOB_ID:-} && ${1:-} == _run ]]; then
  # Submitted with --export=NONE; without this, steps started later would inherit nothing.
  unset SLURM_EXPORT_ENV
  exec "$2" "$3" --state "$4" --job-dir "$5" run
fi

exec "${RW_PYTHON:-python3}" "$(dirname "$(readlink -f "$0")")/rw-native.py" "$@"
