"""Runs for notebook 09 (GA): rule, CP-SAT, BRKGA and NSGA-II on two variants of the Fidentis case. Functions at
module level so a process pool can run them (math/14)."""

import os
from pathlib import Path

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule, worker_intervals
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.schedule import Schedule
from simulation.objectives import MAKESPAN, OVERTIME, overtime, start_deviation
from simulation.planners.cpsat import solve
from simulation.planners.ga import GaParams, rule_plans, solve_ga
from simulation.planners.nsga2 import NsgaParams, nsga2

ROOT = Path(__file__).parents[1]
FIDENTIS = read_model(ROOT / "data/generator/fidentis.json", CarrierGeneratorParams)
# fidentis: one mill, two workers (workers ahead of the mill in days needed); balanced: a third worker, so mill and
# workers need about the same number of days and neither is a clear bottleneck
CASES = {"fidentis": {}, "balanced": {"workers": ("A", "B", "C")}}
SETTINGS = {"GA": {}, "GA no-delay": {"delay_max": 0}}
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
