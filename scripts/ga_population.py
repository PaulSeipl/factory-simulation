"""Population size of the rescheduling GA: the same rescheduling calls (snapshots of one episode, dental workers,
sigma 0.45) solved again with other population sizes and generation limits; value per objective level and time
(math/14 section 3b). Run: uv run python -u scripts/ga_population.py > population.jsonl"""
import json
import time

import simulation.planners.ga as G
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import worker_objective_with_slack
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.sim.scenario import sample_scenario

N_CALLS = 10
VARIANTS = [(100, 30), (100, 10), (50, 30), (30, 30), (30, 100), (20, 50)]  # (population, generations)

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

for i, (a, k) in enumerate(calls):
    c, objective, params, *rest = a
    for pop, gens in VARIANTS:
        p = G.GaParams(population=pop, generations=gens, time_limit=None, seed=params.seed)
        t0 = time.perf_counter()
        r = orig(c, objective, p, *rest, **k)
        wall = time.perf_counter() - t0
        levels = [lv.evaluate(c, r.plan.assignments, r.plan.breaks) for lv in objective.levels]
        print(json.dumps({"call": i + 1, "population": pop, "generations": gens, "evaluations": r.evaluations,
                          "wall": round(wall, 2), "over_budget": r.over_budget,
                          "levels": levels}), flush=True)
