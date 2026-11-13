"""Arrival experiments (math/07_order-arrivals.md §6): configuration, one run, parallel runner.

    uv run experiment list                      # every run (index, configuration, policy, seed)
    uv run experiment run arrivals-rate6 [...]  # by name (experiments/<name>.json) or path; no name: all
    uv run experiment task --index 7            # one run by index (Slurm: index from SLURM_ARRAY_TASK_ID)
    uv run experiment merge                     # row files -> one CSV per configuration

Each run writes its row (`<out>/<config>/rows/<policy>-<seed>.json`, with the configuration hash, the git commit
and the host) and its plan history as JSON Lines (`<out>/<config>/plans/<policy>-<seed>.jsonl`: the start plan,
then every plan the factory receives as a change set); `merge` (also at the end of `run`) writes one CSV per
configuration from the rows whose hash matches the configuration. CP-SAT runs with one thread, a fixed seed and a
deterministic limit, so a run is reproducible; all policies of one seed start from the same instance and scenario.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt, PositiveFloat

from simulation.arrival_generator import ArrivalParams, generate_arrival_instance
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model, write_csv, write_jsonl
from simulation.metrics import run_metrics
from simulation.model.compiled import compile_instance, compile_visible
from simulation.objectives import worker_objective_with_slack
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch_planner, ect, spt
from simulation.sim.scenario import sample_scenario


class PolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    planner: Literal["cpsat", "rule"]  # complete rescheduling: CP-SAT with the worker objective, or SPT + ECT
    # hindsight: start from a plan of the full instance (every arrival known) and never see arrivals as events
    hindsight: bool = False
    max_makespan_change: NonNegativeInt | None = None  # thresholds of math/05 §3
    max_shift: NonNegativeInt | None = None
    period: NonNegativeInt | None = None


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    arrivals: ArrivalParams  # its seed is replaced by each seed of `seeds`
    seeds: tuple[int, ...] = Field(min_length=1)
    sigma: NonNegativeFloat = 0.2  # scenario (math/22)
    q: float = Field(default=0.5, ge=0, le=1)
    max_early: NonNegativeInt = 5
    max_late: NonNegativeInt = 5
    buffer: NonNegativeInt = 60  # cutoff slack of the worker objective (math/04 (O7))
    time_limit: PositiveFloat = 30.0  # per CP-SAT call (wall clock, a safety net)
    deterministic_time: PositiveFloat = 5.0  # per CP-SAT call (work-based: decides the result)
    hindsight_time_limit: PositiveFloat = 600.0  # the start plan of the full instance
    hindsight_deterministic_time: PositiveFloat = 120.0
    policies: dict[str, PolicyConfig] = Field(min_length=1)

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def run_one(config: ExperimentConfig, policy_name: str, seed: int, out: Path) -> dict:
    """One episode; returns its CSV row and writes its plan history."""
    pc = config.policies[policy_name]
    inst = generate_arrival_instance(config.arrivals.model_copy(update={"seed": seed}))
    ci, at = compile_instance(inst), compile_visible(inst)
    objective = worker_objective_with_slack(config.buffer)
    if pc.hindsight:
        start = solve(ci, objective, config.hindsight_time_limit, 1, seed,
                      deterministic_time=config.hindsight_deterministic_time)
    else:
        start = solve(at(0), objective, config.time_limit, 1, seed, deterministic_time=config.deterministic_time)
    if not start.schedule:
        raise RuntimeError(f"{config.name}/{policy_name}/{seed}: no start plan ({start.status})")
    planner = (cpsat_planner(config.time_limit, 1, seed, objective=objective,
                             deterministic_time=config.deterministic_time)
               if pc.planner == "cpsat" else dispatch_planner(spt, ect))
    policy = ReschedulingPolicy(planner=planner, max_makespan_change=pc.max_makespan_change,
                                max_shift=pc.max_shift, period=pc.period)
    scenario = sample_scenario(inst, config.sigma, seed, config.q, config.max_early, config.max_late)
    t0 = time.perf_counter()
    result = execute(ci, start.schedule, scenario, policy, start.breaks, visible=None if pc.hindsight else at,
                     keep_history=True)
    plans = out / config.name / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    write_jsonl(result.history, plans / f"{policy_name}-{seed}.jsonl")
    return {"config": config.name, "config_hash": config.digest(), "commit": _commit(), "host": socket.gethostname(),
            "policy": policy_name, "seed": seed, "orders": len(inst.orders), "operations": ci.n_ops,
            "start_status": start.status, "start_levels": " ".join(map(str, start.levels)),
            "start_bound": start.bound, "wall_time": round(time.perf_counter() - t0, 1),
            "bottleneck_load": bottleneck_load(result.schedule)} | run_metrics(ci, start.schedule, result)


def bottleneck_load(schedule) -> float:
    """Largest share of the realized makespan that one machine is busy (around the clock; machines run at night)."""
    busy: dict[str, int] = {}
    for a in schedule:
        if a.machine is not None:
            busy[a.machine] = busy.get(a.machine, 0) + a.end - a.start
    return round(max(busy.values(), default=0) / max(a.end for a in schedule), 3)


def _commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True)
        return sha.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


CONFIGS = Path("experiments")


def load(names: list[str]) -> list[ExperimentConfig]:
    """Configurations by name (experiments/<name>.json) or path; no names: every file in experiments/."""
    paths = [Path(n) if n.endswith(".json") else CONFIGS / f"{n}.json" for n in names] or sorted(CONFIGS.glob("*.json"))
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"no configuration {path}")
    return [read_model(path, ExperimentConfig) for path in paths]


def tasks(configs: list[ExperimentConfig]) -> list[tuple[ExperimentConfig, str, int]]:
    """Every (configuration, policy, seed) in a fixed order; the index of a run is its position here."""
    return [(c, p, s) for c in configs for p in c.policies for s in c.seeds]


def run_task(config: ExperimentConfig, policy: str, seed: int, out: Path) -> Path:
    """One run; its row goes to its own file, so runs on several machines never write the same file."""
    row = run_one(config, policy, seed, out)
    path = out / config.name / "rows" / f"{policy}-{seed}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return path


def merge(configs: list[ExperimentConfig], out: Path) -> None:
    """One CSV per configuration from its row files, in task order; rows of another configuration hash (the file
    changed since) or missing runs are reported, not merged."""
    for c in configs:
        rows, missing = [], []
        for _, p, s in tasks([c]):
            path = out / c.name / "rows" / f"{p}-{s}.json"
            row = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            if row is None or row["config_hash"] != c.digest():
                missing.append(f"{p}-{s}")
            else:
                rows.append(row)
        if missing:
            note = f"{c.name}: {len(missing)} runs missing or from another configuration: {' '.join(missing)}"
            print(note, file=sys.stderr)  # noqa: T201
        if rows:
            keys = list(dict.fromkeys(k for r in rows for k in r))  # columns can differ by policy (e.g. no replans)
            write_csv([{k: r.get(k) for k in keys} for r in rows], out / f"{c.name}.csv")


def run(configs: list[ExperimentConfig], out: Path, processes: int | None = None) -> None:
    """Every (configuration, policy, seed) in parallel, then merge."""
    with Pool(processes) as pool:
        pool.starmap(run_task, [(c, p, s, out) for c, p, s in tasks(configs)])
    merge(configs, out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="experiment", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in [("list", "show every run with its index"), ("run", "run configurations in parallel"),
                       ("task", "run one run by index"), ("merge", "write the CSVs from the row files")]:
        cmd = sub.add_parser(name, help=text)
        if name == "task":
            cmd.add_argument("--index", type=int, default=None, help="index from `list` (default: SLURM_ARRAY_TASK_ID)")
        cmd.add_argument("configs", nargs="*", help="names in experiments/ or paths (default: all)")
        cmd.add_argument("--out", type=Path, default=Path("experiments/results"))
        if name == "run":
            cmd.add_argument("--processes", type=int, default=None, help="default: number of CPUs")
    args = parser.parse_args(argv)
    configs = load(args.configs)
    if args.command == "list":
        for i, (c, p, s) in enumerate(tasks(configs)):
            print(f"{i:4d}  {c.name:<28} {p:<22} {s}")  # noqa: T201
    elif args.command == "run":
        run(configs, args.out, args.processes)
    elif args.command == "task":
        index = args.index if args.index is not None else int(os.environ.get("SLURM_ARRAY_TASK_ID", -1))
        all_tasks = tasks(configs)
        if not 0 <= index < len(all_tasks):
            raise SystemExit(f"task index {index} outside 0..{len(all_tasks) - 1}")
        c, p, s = all_tasks[index]
        print(run_task(c, p, s, args.out))  # noqa: T201
    else:
        merge(configs, args.out)


if __name__ == "__main__":
    main()
