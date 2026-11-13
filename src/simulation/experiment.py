"""Arrival experiments (math/07_order-arrivals.md §6): configuration, one run, parallel runner.

    uv run python -m simulation.experiment experiments/arrivals-rate4.json [...] --out experiments/results

One CSV per configuration (one row per policy and seed, with the configuration hash and the git commit) and, per
run, the plan history as JSON Lines (`<out>/<config>/plans/<policy>-<seed>.jsonl`: the start plan, then every plan
the factory receives as a change set). CP-SAT runs with one thread, a fixed seed and a deterministic limit, so a run
is reproducible; all policies of one seed start from the same instance and scenario.
"""

import argparse
import hashlib
import subprocess
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
    return {"config": config.name, "config_hash": config.digest(), "commit": _commit(), "policy": policy_name,
            "seed": seed, "orders": len(inst.orders), "operations": ci.n_ops,
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


def run(configs: list[ExperimentConfig], out: Path, processes: int | None = None) -> None:
    """Every (configuration, policy, seed) in parallel; one CSV per configuration."""
    tasks = [(c, p, s, out) for c in configs for p in c.policies for s in c.seeds]
    with Pool(processes) as pool:
        rows = pool.starmap(run_one, tasks)
    for c in configs:
        mine = [r for r in rows if r["config"] == c.name]
        keys = list(dict.fromkeys(k for r in mine for k in r))  # columns can differ by policy (e.g. no replans)
        write_csv([{k: r.get(k) for k in keys} for r in mine], out / f"{c.name}.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("experiments/results"))
    parser.add_argument("--processes", type=int, default=None)
    args = parser.parse_args()
    run([read_model(p, ExperimentConfig) for p in args.configs], args.out, args.processes)
