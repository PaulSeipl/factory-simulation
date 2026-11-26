"""MCTS against rule, GA and CP-SAT at equal wall time (math/15 §5, step M3).

Every run gets one core and BUDGET seconds:
- GA: time limit;
- CP-SAT: one thread, hinted with the best rule plan;
- MCTS: N^it = budget / (decisions x rollout time), measured on the instance before the run, with the budget as
  safety net, so the search commits every decision within it.
Instances: dental example (no workers: makespan only), dental workers, Fidentis and Fidentis balanced (a third worker,
notebook 09), all with makespan; dental workers (the only one with due dates and a calendar) also with the worker
objective with cutoff slack. Results go to
notebooks/results/mcts_compare.json with a digest of the setup; RECOMPUTE=1 in the environment reruns.

    uv run python notebooks/mcts_compare.py
"""

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.objectives import MAKESPAN, overtime, worker_objective_with_slack
from simulation.planners import ga
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.planners.ga import rule_plans
from simulation.planners.mcts import MctsParams, solve_mcts

ROOT = Path(__file__).parents[1]
OUT = ROOT / "notebooks/results/mcts_compare.json"
BUDGET = 60.0  # seconds per run
GA_SEEDS = (1, 2, 3)
# GA variants: all keys; overtime keys 0 (no overtime, as MCTS); also delay_max 0 (non-delay, as MCTS)
GA_VARIANTS = {"GA": {}, "GA no-overtime": {"overtime": False}, "GA no-overtime no-delay": {"overtime": False,
                                                                                           "delay_max": 0}}
# MCTS variants: overtime candidates on (default, M4) and off (non-delay, no overtime, as before M4)
MCTS_VARIANTS = {"MCTS": {}, "MCTS no-overtime": {"overtime": False}}
GENERATOR = ROOT / "data/generator"
CASES = {  # name -> (generator file, parameter update)
    "dental-example": ("dental-carriers-example.json", {}),
    "dental-workers": ("dental-carriers-workers.json", {}),
    "fidentis": ("fidentis.json", {}),
    "balanced": ("fidentis.json", {"workers": ("A", "B", "C")}),
}
OBJECTIVES = {"makespan": MAKESPAN, "worker": worker_objective_with_slack(60)}
DIGEST = hashlib.sha256((repr(CASES) + repr(sorted(OBJECTIVES))
                         + repr((BUDGET, GA_SEEDS, GA_VARIANTS, MCTS_VARIANTS, "resume"))
                         + "".join((GENERATOR / f).read_text() for f, _ in CASES.values())).encode()).hexdigest()[:12]


def instance(case: str) -> CompiledInstance:
    file, update = CASES[case]
    return compile_instance(generate_carrier_instance(
        read_model(GENERATOR / file, CarrierGeneratorParams).model_copy(update=update)))


def pairs() -> list[tuple[str, str]]:
    # the worker objective ranks tardiness first: only dental workers has due dates and a calendar
    return [(c, o) for c in CASES for o in OBJECTIVES if o == "makespan" or c == "dental-workers"]


def iterations_for(ci: CompiledInstance, objective, budget: float, overtime: bool) -> tuple[int, int, float]:
    """N^it that fits the budget: (N^it, decisions, seconds per rollout incl. evaluation), from one SPT decode with
    the overtime candidates MCTS offers. A rollout resumes at the root, so it costs about half a decode (math/15 §5)."""
    sizes: list[int] = []
    option = ci.calendar.max_overtime if overtime and ci.calendar is not None and ci.calendar.max_overtime else None

    def count(eligible, _state):
        sizes.append(len(eligible))
        return next(i for i, c in enumerate(eligible) if len(c) == 4)

    t0 = time.perf_counter()
    plan = dispatch_plan(ci, spt, choose=count, overtime_option=option)
    decode = time.perf_counter() - t0
    t0 = time.perf_counter()
    objective.evaluate(ci, plan.assignments, plan.breaks)
    rollout = decode / 2 + time.perf_counter() - t0  # shortcut: half a decode on average, measured 0.3-0.5 of it
    decisions = sum(n > 1 for n in sizes)
    seeding = 15 * decode  # the rule plans
    return max(1, int((budget - seeding) / (decisions * rollout))), decisions, rollout


def row(case, objective_name, ci, objective, plan_assignments, breaks, **extra) -> dict:
    return {"case": case, "objective": objective_name,
            "value": objective.evaluate(ci, plan_assignments, breaks),
            "makespan": MAKESPAN.evaluate(ci, plan_assignments, breaks), "overtime": overtime(ci, plan_assignments),
            "feasible": check_schedule(ci, plan_assignments, breaks=breaks) == []} | extra


def run(case: str, objective_name: str, method: str, seed: int = 0) -> dict:
    ci, objective = instance(case), OBJECTIVES[objective_name]
    t0 = time.perf_counter()
    if method == "rule":
        plan = min(rule_plans(ci), key=lambda p: objective.evaluate(ci, p.assignments, p.breaks))
        return row(case, objective_name, ci, objective, plan.assignments, plan.breaks, method="best rule",
                   wall=time.perf_counter() - t0)
    if method in GA_VARIANTS:
        setting = dict(GA_VARIANTS[method])
        decode = ga.decode
        if not setting.pop("overtime", True):  # overtime keys forced to 0 for this run only (the pool reuses processes)
            def no_overtime(ci_, genes, delay_max, snapshot=None, join=True):
                n = ci_.n_ops
                return decode(ci_, [*genes[:3 * n], *[0.0] * n, *genes[4 * n:]], delay_max, snapshot, join)
            ga.decode = no_overtime
        try:
            r = ga.solve_ga(ci, objective, ga.GaParams(time_limit=BUDGET, seed=seed, **setting))
        finally:
            ga.decode = decode
        return row(case, objective_name, ci, objective, r.plan.assignments, r.plan.breaks, method=method, seed=seed,
                   generations=r.generations, evaluations=r.evaluations, wall=time.perf_counter() - t0)
    if method == "cpsat":
        hint = min(rule_plans(ci), key=lambda p: objective.evaluate(ci, p.assignments, p.breaks)).assignments
        try:
            r = solve(ci, objective, time_limit=BUDGET, workers=1, hint=hint)
        except RuntimeError as e:  # a lexicographic level without a solution in its time limit
            return {"case": case, "objective": objective_name, "method": "CP-SAT", "status": str(e)}
        if not r.schedule:
            return {"case": case, "objective": objective_name, "method": "CP-SAT", "status": r.status}
        return row(case, objective_name, ci, objective, r.schedule, r.breaks, method="CP-SAT", status=r.status,
                   wall=time.perf_counter() - t0)
    setting = MCTS_VARIANTS[method]
    n_it, decisions, rollout = iterations_for(ci, objective, BUDGET, setting.get("overtime", True))
    r = solve_mcts(ci, objective, MctsParams(iterations=n_it, time_limit=BUDGET, **setting))
    return row(case, objective_name, ci, objective, r.plan.assignments, r.plan.breaks, method=method,
               iterations=n_it, decisions=decisions, rollout_s=round(rollout, 4), committed=r.decisions,
               evaluations=r.evaluations, wall_limited=r.wall_limited, rollout_rule=r.rollout_rule,
               wall=time.perf_counter() - t0)


def tasks() -> list[tuple]:
    out = []
    for case, obj in pairs():
        out += [(case, obj, "rule"), (case, obj, "cpsat")] + [(case, obj, v) for v in MCTS_VARIANTS]
        out += [(case, obj, v, s) for v in GA_VARIANTS for s in GA_SEEDS]
    return out


def main() -> None:
    if OUT.exists() and not os.environ.get("RECOMPUTE"):
        stored = json.loads(OUT.read_text())
        if stored["digest"] == DIGEST:
            rows = stored["rows"]
        else:
            sys.exit(f"{OUT} has digest {stored['digest']}, setup is {DIGEST}: rerun with RECOMPUTE=1")
    else:
        work = tasks()
        with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
            rows = list(pool.map(run, *zip(*[(t + (0,))[:4] for t in work], strict=True)))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"digest": DIGEST, "budget": BUDGET, "rows": rows}, indent=1))
    for r in rows:
        keys = ("case", "objective", "method", "seed", "value", "makespan", "overtime", "feasible", "iterations",
                "committed", "wall_limited", "evaluations", "generations", "status", "wall")
        print({k: (round(r[k], 1) if isinstance(r[k], float) else r[k]) for k in keys if k in r})  # noqa: T201


if __name__ == "__main__":
    main()
