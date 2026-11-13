#!/bin/bash
# Every experiment run on the IfI Abaki partition (see scripts/README.md).
#   mkdir -p slurm-logs && sbatch scripts/slurm-array.sh              # every configuration
#   sbatch scripts/slurm-array.sh arrivals-rate6 arrivals-rate8      # only these (indices refer to this list)
# The RBG allows 15 running and 30 submitted jobs per user, so 15 array tasks each take every 15th run
# (index = task id + k * task count) instead of one array element per run.
#SBATCH --job-name=experiment
#SBATCH --partition=Abaki
#SBATCH --qos=abaki
#SBATCH --array=0-14
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=1-00:00:00
#SBATCH --output=slurm-logs/%A_%a.out
# shortcut: --mem is a guess; set it from `sacct -j <job> -o JobID,MaxRSS,Elapsed` after the first hindsight run.
# One machine type for the tables: pick it from `sinfo -p Abaki -N -o '%N %c %m %f'`, then add
# `#SBATCH --constraint=<feature>` or `#SBATCH --nodelist=<nodes>`.
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"  # experiments/ and the git dirty check are relative to the repository root
export UV_NO_SYNC=1         # .venv was synced once on the login node; 15 tasks must not sync it at once
n=$(uv run experiment list "$@" | wc -l)
failed=0
for ((i = SLURM_ARRAY_TASK_ID; i < n; i += SLURM_ARRAY_TASK_COUNT)); do
  uv run experiment task --index "$i" "$@" || { echo "run $i failed" >&2; failed=1; }
done
exit "$failed"
