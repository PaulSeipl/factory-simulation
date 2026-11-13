#!/usr/bin/env bash
# Run experiments on the home PC, sleep blocked while they run (see scripts/README.md).
#   scripts/home-run.sh              # every run from `experiment list`
#   scripts/home-run.sh 10 11 30     # only these indices (e.g. the ones missing after an interruption)
# Start it inside tmux so it survives the SSH connection. JOBS defaults to 4, the physical cores of the
# i7-6700K: a run on a shared hyperthread is slower, which shifts wall_time and can trip CP-SAT's 30 s
# wall-clock limit before the deterministic limit, and then the plans differ, not only the timings.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
export UV_NO_SYNC=1  # parallel `uv run` calls must not sync the same .venv
if (($#)); then printf '%s\n' "$@"; else uv run experiment list | awk '{print $1}'; fi |
  systemd-inhibit --what=sleep:idle --who=experiment --why="experiment runs" \
    xargs -P "${JOBS:-4}" -I{} uv run experiment task --index {}
uv run experiment merge
