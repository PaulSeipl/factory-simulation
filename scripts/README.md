# Running the experiments off the laptop

- [home-pc.md](home-pc.md): the home PC (i7-6700K, CachyOS), reached over Tailscale and SSH, woken with
  Wake-on-LAN, suspending itself when idle. Scripts: `home-run.sh`, `home/idle-suspend.*`. Waking it, with tests:
  [wake-on-lan.md](wake-on-lan.md).
- [slurm.md](slurm.md): the IfI Slurm cluster, Abaki partition. Script: `slurm-array.sh`.

Both run the same entry point, `uv run experiment task --index i`, and write one row file per run to
`experiments/results/<config>/rows/`.

## Shared rules

1. **Commit and push first.** A clone only has what is pushed; check that `uv run experiment list` works there.
2. **Same commit everywhere.** Every row records `commit`. The run index is the position in `experiment list`,
   which takes every JSON file in `experiments/` in sorted order, so adding a configuration shifts the indices.
   Run from a fixed checkout (`git checkout <hash>`) and do not edit `src/` there (`+dirty`).
3. **One machine type per table.** `wall_time` and `planner_time` depend on the hardware. `merge` does not filter
   by `host`, so pull each machine's results into its own folder and merge them separately.
4. **Check results, not only timings, once per machine.** CP-SAT stops at a deterministic limit, but also at a
   30 s wall-clock limit as a safety net. On a slower CPU or under load the safety net can fire first, and then
   the plans differ, not only the timings. Rerun 2 or 3 seeds that already ran on the laptop (same commit), and
   compare every column except `wall_time`, `planner_time` and `host`.
5. **`plans/` is gitignored**, so results travel by `ssh … tar`, not git. Copy the CSVs of the machine chosen for
   the tables into `experiments/results/` and commit them with the commit hash of the runs.
