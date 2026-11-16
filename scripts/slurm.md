# Guide: experiments on the IfI Slurm cluster (Abaki)

Runs every experiment on the Abaki partition with `scripts/slurm-array.sh`. Read the shared rules in
[README.md](README.md) first (same commit everywhere, one machine type per table, check results once).

## What the RBG page says

Source: https://www.rz.ifi.lmu.de/infos/slurm_de.html (read 2026-11-13).

- Abaki access is requested by email to the RBG with a description of the use. The page asks for a supervisor's
  confirmation only for higher priority, not for access itself.
- Partition `Abaki`, QOS `abaki` (`-p Abaki -q abaki`).
- Limits: 15 running and 30 submitted jobs per user. Default run time 1 day, maximum 5 days.
- Abaki jobs are never suspended. Jobs on the student pool machines are paused when someone logs in there, so
  pool machines are not usable for timing tables (and a pause can trip CP-SAT's 30 s wall-clock limit).

## Laptop

Nothing new: Windows' built-in OpenSSH client (`ssh -V` in PowerShell), Git Bash and `uv` are enough. The RBG
login is reached with `ssh <user>@<login host>` (host name from the RBG).

## Setup (once, on the login node)

```bash
quota -s                                             # uv's Python and the ortools .venv take a few hundred MB
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:PaulSeipl/factory-simulation.git ~/simulation
cd ~/simulation && git checkout <hash> && uv sync --frozen   # uv fetches Python 3.14 itself
sinfo -p Abaki -N -o '%N %c %m %f'                   # node types: pin one in the script
sacctmgr show assoc user=$USER format=MaxSubmit,MaxJobs
sacctmgr show qos abaki
```

- The clone needs read access to the GitHub repository: a read-only deploy key (repository settings → Deploy
  keys) generated on the login node. That key can only read this one repository.
- If the home quota is too small, set `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` to a larger directory before
  `uv sync`.
- After `sinfo`, add `#SBATCH --constraint=<feature>` or `#SBATCH --nodelist=<nodes>` to
  `scripts/slurm-array.sh`, so all runs land on one node type.

## How the array script works

110 runs do not fit into 30 submitted jobs if every array element counts (check with `sacctmgr` above). So the
script submits 15 array tasks, and task t runs the indices t, t+15, t+30, … one after the other with
`uv run experiment task --index i`. The `.venv` is synced once on the login node, and the jobs run with
`UV_NO_SYNC=1`, so 15 tasks never modify the same `.venv` at once.

## Submitting

```bash
cd ~/simulation && mkdir -p slurm-logs
sbatch scripts/slurm-array.sh                        # or with configuration names, as for `experiment`
squeue -u $USER                                      # what is running or waiting
tail -f slurm-logs/<jobid>_0.out                     # output of task 0
```

After the first hindsight run, set `--mem` from `sacct -j <job> -o JobID,MaxRSS,Elapsed`.

## Collecting

The rows land in `~/simulation/experiments/results/<config>/rows/` on the shared home directory. When `squeue` is
empty, run `uv run experiment merge` on the login node. It lists missing runs. Rerun one by index with
`sbatch -p Abaki -q abaki --wrap 'uv run --no-sync experiment task --index 42'` (not `--array=42` on the script:
with one array task the stride is 1, and it would run every index from 42 on).

Then on the laptop, in Git Bash, into a folder of its own:

```bash
mkdir -p results-abaki
ssh <user>@<login host> 'tar -C ~/simulation -cz experiments/results' | tar -xz -C results-abaki
uv run experiment merge --out results-abaki/experiments/results
```
