#!/usr/bin/env bash
# Run experiments on the home PC, sleep blocked while they run (see scripts/home-pc.md).
#   bash scripts/home-run.sh                          # every run this PC has no row for (continues after a stop)
#   bash scripts/home-run.sh arrivals-rate6 --restart # arguments go to `experiment run` (names, --policy, --seed)
# Start it inside tmux so it survives the SSH connection. JOBS defaults to 4, the physical cores of the
# i7-6700K: a run on a shared hyperthread is slower, which shifts wall_time and can trip CP-SAT's
# wall-clock limit before the deterministic limit, and then the plans differ, not only the timings.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
systemd-inhibit --what=sleep:idle --who=experiment --why="experiment runs" \
  uv run experiment run --processes "${JOBS:-4}" "$@"
