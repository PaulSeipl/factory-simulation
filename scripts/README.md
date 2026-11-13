# Running the experiments off the laptop

Two targets: the home PC (i7-6700K, 4 cores / 8 threads, CachyOS) and the IfI Slurm cluster (Abaki partition).
Both run the same entry point, `uv run experiment task --index i`, and write one row file per run to
`experiments/results/<config>/rows/`.

## 0. Before either target

1. **Commit and push the experiment CLI.** `uv run experiment` (`src/simulation/experiment.py`, `pyproject.toml`)
   only exists in the working tree so far. A clone has no `experiment` command until it is pushed.
2. **Same commit everywhere.** Every row records `commit`. The run index is the position in `experiment list`,
   which takes every JSON file in `experiments/` in sorted order, so adding a configuration shifts the indices.
   Run from a fixed checkout (`git checkout <hash>`) and do not edit `src/` there (`+dirty`).
3. **One machine type per table.** `wall_time` and `planner_time` depend on the hardware. `merge` does not filter
   by `host`, so pull each machine's results into its own folder and merge them separately (section 3).
4. **Check results, not only timings, once per machine.** CP-SAT stops at a deterministic limit, but also at a
   30 s wall-clock limit as a safety net. On a slower CPU or under load the safety net can fire first, and then
   the plans differ, not only the timings. Rerun 2 or 3 seeds that already ran on the laptop (same commit), and
   compare every column except `wall_time`, `planner_time` and `host`.

The repository is cloned over SSH (`git@github.com:...`). Each machine needs read access: a read-only deploy key
(GitHub repository settings → Deploy keys), or agent forwarding from the laptop (`ssh -A`) for the clone.

## 1. Home PC

### Remote access

```bash
sudo pacman -S openssh tailscale tmux
sudo systemctl enable --now sshd tailscaled
sudo tailscale up
```

- **SSH:** key login only. Copy the laptop's public key to `~/.ssh/authorized_keys` on the PC, then set
  `PasswordAuthentication no` in `/etc/ssh/sshd_config.d/10-keys.conf` and `sudo systemctl restart sshd`.
- **From outside:** Tailscale (also installed on the laptop) gives the PC a fixed name in the tailnet. It needs no
  port forwarding and also works behind CGNAT/DS-Lite. Do not open port 22 on the router.
- Laptop `~/.ssh/config`: `Host home` / `HostName <tailscale name>` / `User <user>`.

### Waking it up

A suspended PC is off the network, so neither Tailscale nor SSH can wake it. The magic packet has to come from a
device on the home network that is always on.

1. Wired Ethernet only (no Wake-on-LAN over Wi-Fi).
2. BIOS: enable Wake-on-LAN ("Wake on PCI-E" or similar) and disable ErP/deep sleep.
3. NIC: `nmcli c show` for the connection name, then
   `sudo nmcli c modify <conn> 802-3-ethernet.wake-on-lan magic`. Check with `ethtool <iface>` (`Wake-on: g`).
4. Sender: the router, if it can send a Wake-on-LAN packet from its web interface or app while you are away (check
   the router's documentation). Otherwise any always-on device in the LAN that is in the tailnet, running
   `wakeonlan <mac>`.
5. Fallback without a sender: wake at a fixed time, e.g. `sudo rtcwake -m mem -t $(date -d 'tomorrow 07:30' +%s)`
   before leaving, or a systemd timer with `WakeSystem=true`.

Test locally first: `systemctl suspend`, then wake from the laptop at home. The NVIDIA driver needs its
suspend/resume services (`systemctl status nvidia-suspend nvidia-resume`); if resume hangs, fix that first.

### Suspending when idle

Desktop power settings only act while someone is logged in at the desktop. A PC woken remotely sits at the login
screen, so `scripts/home/idle-suspend.sh` decides instead. Every 5 min it checks for an `experiment` sleep inhibitor,
an SSH connection, or a desktop session. After 6 idle checks in a row (30 min) it suspends.

```bash
sudo install -m755 scripts/home/idle-suspend.sh /usr/local/bin/
sudo cp scripts/home/idle-suspend.{service,timer} /etc/systemd/system/
sudo systemctl enable --now idle-suspend.timer
```

Power: suspend-to-RAM draws a few watts, compared with idling with the GTX 1070 powered. For the runs, use the
`performance` power profile (`powerprofilesctl set performance`, or the CachyOS equivalent). Watch the CPU
temperature on the first long run (`sensors`): it is a 2016 cooler running 4 cores at full load for hours.

### Repository and uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # or: sudo pacman -S uv
git clone git@github.com:PaulSeipl/factory-simulation.git ~/simulation
cd ~/simulation && git checkout <hash> && uv sync --frozen   # uv fetches Python 3.14 itself
```

### Starting runs

```bash
ssh home
tmux new -s exp            # reattach later with: tmux attach -t exp
cd ~/simulation && bash scripts/home-run.sh
```

`scripts/home-run.sh` runs every index from `experiment list`, 4 at a time (one per physical core; set `JOBS` to
change). The runs are wrapped in `systemd-inhibit --what=sleep:idle`, so neither the timer nor the desktop suspends
the PC while they run. Check with `systemd-inhibit --list`. `merge` runs at the end. The CLI does not resume, so
after an interruption, pass only the missing indices: `bash scripts/home-run.sh 10 11 30`.

Estimate: 25 hindsight runs × 50–80 min ≈ 21–33 CPU-hours. On 4 cores that is about 6–9 h for the hindsight runs
alone, longer if the 6700K is slower per core than the laptop.

## 2. IfI Slurm cluster (Abaki)

Facts from the RBG page (https://www.rz.ifi.lmu.de/infos/slurm_de.html, read 2026-11-13):

- Abaki access is requested by email to the RBG with a description of the use. The page asks for a supervisor's
  confirmation only for higher priority.
- Partition `Abaki`, QOS `abaki`.
- Limits: 15 running and 30 submitted jobs per user. Default run time 1 day, maximum 5 days.
- Abaki jobs are never suspended. Jobs on the student pool machines are paused when someone logs in there, so the
  pool machines are not usable for timing tables (and a pause can trip the 30 s wall-clock limit).

Check whether array elements count against the 30-job limit:
`sacctmgr show assoc user=$USER format=MaxSubmit,MaxJobs` and `sacctmgr show qos abaki`. `scripts/slurm-array.sh`
assumes they do. It submits 15 array tasks, and task t runs indices t, t+15, t+30, …. The index is
`SLURM_ARRAY_TASK_ID` plus a multiple of the task count, passed as `--index`.

### Setup (once, on the login node)

```bash
quota -s                                             # uv's Python and the ortools .venv take a few hundred MB
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:PaulSeipl/factory-simulation.git ~/simulation
cd ~/simulation && git checkout <hash> && uv sync --frozen
sinfo -p Abaki -N -o '%N %c %m %f'                   # node types: pin one in the script
```

If the home quota is too small, set `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` to a larger directory before
`uv sync`.

### Submitting

```bash
cd ~/simulation && mkdir -p slurm-logs
sbatch scripts/slurm-array.sh                        # or with configuration names, as for `experiment`
squeue -u $USER
```

Sync the `.venv` once on the login node. The jobs run with `UV_NO_SYNC=1`, so 15 tasks never modify the same
`.venv`. After the first hindsight run, set `--mem` from `sacct -j <job> -o JobID,MaxRSS,Elapsed`.

### Collecting

The rows land in `~/simulation/experiments/results/<config>/rows/` on the shared home directory. When `squeue` is
empty, run `uv run experiment merge` on the login node. It lists missing runs, which can be rerun by index:
`sbatch -p Abaki -q abaki --wrap 'uv run --no-sync experiment task --index 42'` (not `--array=42` on the
script: with one array task the stride is 1, and it would run every index from 42 on).

## 3. Getting results to the laptop

`plans/` is gitignored, so git cannot carry the full results. Pull each machine into its own folder (Windows
OpenSSH and `tar` are enough, no rsync needed):

```bash
mkdir -p results-home
ssh home 'tar -C ~/simulation -cz experiments/results' | tar -xz -C results-home
uv run experiment merge --out results-home/experiments/results
```

Add `--exclude='*/plans'` to the remote `tar` if only the rows and CSVs are needed. Copy the CSVs of the machine
chosen for the tables into `experiments/results/` and commit them with the commit hash of the runs.
