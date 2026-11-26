"""GA against CP-SAT on the same rescheduling calls: the snapshots of one episode (dental workers, sigma 0.45,
seed 1, GA rescheduling with 10 generations), each solved again by both planners; value per objective level and
time (math/14 section 3b). Run: uv run python -u scripts/ga_vs_cpsat.py [--cpsat-only] > ga_vs_cpsat.jsonl"""
import json
import sys
import time

import simulation.planners.ga as G
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import worker_objective_with_slack
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.sim.scenario import sample_scenario

N_CALLS = 10
GA = [] if "--cpsat-only" in sys.argv else [(100, 10), (100, 30)]  # (population, generations)
CPSAT = [1.0, 5.0, 20.0]  # deterministic time per level (5: the experiments' default)

calls = []
orig = G.solve_ga


class Done(Exception):
    pass


def recording(*a, **k):
    calls.append((a, k))
    if len(calls) >= N_CALLS:
        raise Done
    return orig(*a, **k)


G.solve_ga = recording
inst = generate_carrier_instance(read_model("data/generator/dental-carriers-workers.json", CarrierGeneratorParams))
ci = compile_instance(inst)
obj = worker_objective_with_slack(60)
plan = dispatch_plan(ci, SEQUENCING_RULES["spt"])
pol = ReschedulingPolicy(planner=G.ga_planner(obj, G.GaParams(generations=10, time_limit=None, seed=1)),
                         max_makespan_change=10, max_shift=30, period=120)
try:
    execute(ci, plan.assignments, sample_scenario(inst, 0.45, 1, q=0.5, max_early=5, max_late=5), pol, plan.breaks)
except Done:
    pass
G.solve_ga = orig


def levels(c, assignments, breaks):
    return [lv.evaluate(c, assignments, breaks) for lv in obj.levels]


for i, (a, k) in enumerate(calls):
    c, objective, params, snapshot, current, *rest = a
    budget = rest[0] if rest else k.get("change_budget")
    n_free = c.n_ops - len(snapshot.frozen)
    for pop, gens in GA:
        t0 = time.perf_counter()
        r = orig(c, objective, G.GaParams(population=pop, generations=gens, time_limit=None, seed=1), snapshot,
                 current, budget)
        print(json.dumps({"call": i + 1, "free": n_free, "planner": f"ga {pop}x{gens}",
                          "wall": round(time.perf_counter() - t0, 2),
                          "levels": levels(c, r.plan.assignments, r.plan.breaks)}), flush=True)
    for dt in CPSAT:
        t0 = time.perf_counter()
        try:
            r = solve(c, objective, 120.0, 1, 1, hint=current, snapshot=snapshot, reference=current,
                      change_budget=budget, deterministic_time=dt)
            status, lv = r.status, levels(c, r.schedule, r.breaks) if r.schedule else None
        except RuntimeError as e:  # a level without a solution within the limit
            status, lv = f"failed: {e}", None
        print(json.dumps({"call": i + 1, "free": n_free, "planner": f"cpsat dt{dt:g}", "status": status,
                          "wall": round(time.perf_counter() - t0, 2), "levels": lv}), flush=True)
