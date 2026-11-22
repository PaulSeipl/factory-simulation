"""Runs for notebook 09 (GA): rule, CP-SAT, BRKGA and NSGA-II on two variants of the Fidentis case. Functions at
module level so a process pool can run them (math/14)."""

import os
from pathlib import Path

from simulation.arrival_generator import ArrivalParams
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.control.nesting import Nesting, average_daily_capacity, default_order_load
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.metrics import run_metrics
from simulation.check.feasibility import check_schedule, worker_intervals
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.schedule import Schedule
from simulation.objectives import MAKESPAN, OVERTIME, overtime, start_deviation, worker_objective_with_slack
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch_planner, ect, spt
from simulation.planners.ga import GaParams, ga_planner, rule_plans, solve_ga
from simulation.planners.nsga2 import NsgaParams, nsga2
from simulation.sim.scenario import sample_scenario

ROOT = Path(__file__).parents[1]
FIDENTIS = read_model(ROOT / "data/generator/fidentis.json", CarrierGeneratorParams)
# fidentis: one mill, two workers (workers ahead of the mill in days needed); balanced: a third worker, so mill and
# workers need about the same number of days and neither is a clear bottleneck
CASES = {"fidentis": {}, "balanced": {"workers": ("A", "B", "C")}}
# GA: all keys; no-delay: delay keys ignored; greedy join: join keys ignored, every s-batch partner joins (math/14)
SETTINGS = {"GA": {}, "GA no-delay": {"delay_max": 0}, "GA greedy join": {"join": False}}
TIME_LIMIT = 60.0  # seconds per GA and CP-SAT run
FRONT_TIME = 120.0  # seconds per NSGA-II run


def instance(case: str, s_batches: bool) -> CompiledInstance:
    update = CASES[case] | ({} if s_batches else {"s_batch_steps": {}})
    return compile_instance(generate_carrier_instance(FIDENTIS.model_copy(update=update)))


def loads(ci: CompiledInstance) -> dict[str, float]:
    """Days a resource needs for its work alone: machines run 24 h a day; workers 510 minutes a working day each,
    five working days a week, given in calendar days."""
    work: dict[str, int] = {}
    for opts in ci.options:
        if opts:
            kind = ci.machine_ids[opts[0][0]].rstrip("0123456789")
            work[kind] = work.get(kind, 0) + min(p for _, p in opts)
    count = {k: sum(m.rstrip("0123456789") == k for m in ci.machine_ids) for k in work}
    days = {k: round(v / (1440 * count[k]), 1) for k, v in work.items()}
    shares = sum(sh.length if sh.kind != "whole" else (min(p for _, p in ci.options[o]) if ci.options[o]
                                                       else ci.fixed_duration[o])
                 for o in range(ci.n_ops) for sh in ci.shares[o])
    days["workers"] = round(shares / (510 * len(ci.worker_ids)) * 7 / 5, 1)
    return days


def metrics(ci: CompiledInstance, assignments, breaks) -> dict:
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in assignments}
    batches: dict[str, list[int]] = {}
    for a in assignments:
        if a.batch:
            batches.setdefault(a.batch, []).append(ci.op_index[a.order_id, a.op_id])
    return {"makespan": MAKESPAN.evaluate(ci, assignments, breaks), "overtime": overtime(ci, assignments),
            "worker_minutes": sum(e - s for ivs in worker_intervals(ci, by_op).values() for s, e, _ in ivs),
            "batches": len(batches),
            "saved": sum((len(ops) - 1) * ci.s_setup[ops[0]] for ops in batches.values()),
            "feasible": check_schedule(ci, assignments, breaks=breaks) == []}


def best_rule(ci: CompiledInstance):
    return min(rule_plans(ci), key=lambda p: MAKESPAN.evaluate(ci, p.assignments, p.breaks))


def rule_run(case: str, s_batches: bool) -> dict:
    ci = instance(case, s_batches)
    plan = best_rule(ci)
    return {"case": case, "s_batches": s_batches, "planner": "best rule"} | metrics(ci, plan.assignments, plan.breaks)


def cpsat_run(case: str, s_batches: bool) -> dict:
    """CP-SAT on all cores, hinted with the best rule plan (math/12)."""
    ci = instance(case, s_batches)
    hint = best_rule(ci).assignments
    result = solve(ci, MAKESPAN, time_limit=TIME_LIMIT, workers=os.cpu_count(), hint=hint)
    if not result.schedule:
        raise RuntimeError(f"CP-SAT found no plan for {case} within {TIME_LIMIT} s ({result.status})")
    return {"case": case, "s_batches": s_batches, "planner": "CP-SAT", "status": result.status,
            "bound": result.bound} | metrics(ci, result.schedule, result.breaks)


def ga_run(case: str, s_batches: bool, setting: str, seed: int) -> dict:
    ci = instance(case, s_batches)
    result = solve_ga(ci, MAKESPAN, GaParams(time_limit=TIME_LIMIT, seed=seed, **SETTINGS[setting]))
    plan = result.plan
    return {"case": case, "s_batches": s_batches, "planner": setting, "seed": seed,
            "generations": result.generations, "evaluations": result.evaluations, "history": list(result.history),
            "plan": Schedule(assignments=plan.assignments, breaks=plan.breaks).model_dump(mode="json")
            } | metrics(ci, plan.assignments, plan.breaks)


def front_run(case: str, kind: str) -> dict:
    """NSGA-II front with s-batches: (makespan, overtime) or (makespan, start deviation from the best rule plan)."""
    ci = instance(case, True)
    second = OVERTIME if kind == "overtime" else start_deviation(best_rule(ci).assignments)
    result = nsga2(ci, [MAKESPAN, second], NsgaParams(time_limit=FRONT_TIME, seed=1))
    return {"case": case, "kind": kind, "front": [list(v) for v, _ in result.front],
            "generations": result.generations, "evaluations": result.evaluations,
            "feasible": all(check_schedule(ci, p.assignments, breaks=p.breaks) == [] for _, p in result.front)}


# --- rescheduling with arrivals (math/14 §5d): release during the run as in notebook 08 (math/33) -------------------

BASE = FIDENTIS.model_copy(update={"release_range": (0, 0)})
MILL = ("mill1",)
ORDER_LOAD, LONGEST = default_order_load(BASE, MILL)
CAPACITY = average_daily_capacity(BASE.calendar, LONGEST, len(MILL))  # minutes of mill work per working day
RATES = (0.6, 1.0)  # orders accepted per working day: below and above the mill's capacity (notebook 08)
WINDOWS = (None, 3)  # release: bind all at the next nesting time, or the norm with a 3-day window and forecast
RESCHED_PLANNERS = ("rule", "CP-SAT", "GA")
RESCHED_SEEDS = range(1, 5)
GA_GENERATIONS = 30  # per rescheduling; a generation limit, so a run is reproducible (time limit only a safety net)
BUFFER = 60  # cutoff slack of the worker objective (math/04 (O7)), as in the experiments
DET_TIME = 5.0  # CP-SAT deterministic seconds per call, as in the experiments


def release_norm(window: int, rate: float) -> dict:
    """The norm of notebook 08: forecast = arrival rate (expected orders per nesting day)."""
    return {"machines": MILL, "capacity_per_day": CAPACITY, "window_days": window, "default_load": ORDER_LOAD,
            "forecast": dict.fromkeys(range(5), rate)}


def resched_run(rate: float, window: int | None, planner: str, seed: int, generations: int,
                history: bool = False) -> dict:
    """One episode: orders accepted over 10 days, bound at the nesting times (all, or under the norm with `window`
    days), keyed disturbances (sigma 0.2); start plan by CP-SAT for every planner of a seed; complete rescheduling by
    `planner` at every nesting time, repair in between. `history`: also the plan history (change sets and plan
    metrics per time point), the realized schedule and the final instance, for the plots of the plan over time."""
    p = ArrivalParams(seed=seed, base=BASE, rates=dict.fromkeys(range(5), rate), window_days=10, backlog=2,
                      due_working_days=10, norm=release_norm(window, rate) if window else None)
    nesting = Nesting(p)
    inst0 = nesting.instance()
    ci0, objective = compile_instance(inst0), worker_objective_with_slack(BUFFER)
    start = solve(ci0, objective, 120.0, 1, seed, deterministic_time=DET_TIME)
    if not start.schedule:
        raise RuntimeError(f"no start plan ({start.status})")
    tool = {"rule": lambda: dispatch_planner(spt, ect),
            "CP-SAT": lambda: cpsat_planner(120.0, 1, seed, objective=objective, deterministic_time=DET_TIME),
            "GA": lambda: ga_planner(objective, GaParams(generations=generations, time_limit=120.0, seed=seed))}[planner]()

    def scenario(inst):
        return sample_scenario(inst, seed=seed, keyed=True, sigma=0.2, q=0.5, max_early=5, max_late=5)

    result = execute(ci0, start.schedule, scenario(inst0), ReschedulingPolicy(planner=tool), start.breaks,
                     nesting=nesting, scenario_for=scenario, keep_history=history)
    final = nesting.instance()
    ci = compile_instance(final)
    return {"rate": rate, "release": f"norm {window} d" if window else "bind all", "planner": planner, "seed": seed,
            "orders": len(final.orders), "objective": objective.evaluate(ci, result.schedule, result.breaks)
            } | run_metrics(ci, start.schedule, result) | ({
                "history": result.history, "instance": final.model_dump(mode="json"),
                "realized": [[a.order_id, a.op_id, a.start, a.end] for a in result.schedule]} if history else {})
