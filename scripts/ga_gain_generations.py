"""When does the GA still improve during rescheduling? Per call: the generations at which the incumbent improved
(dental workers, GA rescheduling with 30 generations, the first 60 calls per seed; math/14 section 3, protocol (111)).
Run: uv run python -u scripts/ga_gain_generations.py > gains.jsonl"""
import json
import simulation.planners.ga as G
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import worker_objective_with_slack
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.sim.scenario import sample_scenario

calls = []
SEED = [0]


class Done(Exception):
    pass


orig = G.solve_ga
def recording(*a, **k):
    r = orig(*a, **k)
    h = r.history
    gains = [g for g in range(1, len(h)) if h[g] < h[g - 1]]
    calls.append(1)
    print(json.dumps({"seed": SEED[0], "call": len(calls), "generations": r.generations, "gains": gains,
                      "start": h[0], "end": h[-1]}), flush=True)
    if len(calls) >= 60:
        raise Done
    return r
G.solve_ga = recording
inst = generate_carrier_instance(read_model("data/generator/dental-carriers-workers.json", CarrierGeneratorParams))
ci = compile_instance(inst)
obj = worker_objective_with_slack(60)
plan = dispatch_plan(ci, SEQUENCING_RULES["spt"])
for seed in (1, 2):
    pol = ReschedulingPolicy(planner=G.ga_planner(obj, G.GaParams(generations=30, time_limit=None, seed=seed)),
                             max_makespan_change=10, max_shift=30, period=120)
    SEED[0] = seed
    try:
        execute(ci, plan.assignments, sample_scenario(inst, 0.45, seed, q=0.5, max_early=5, max_late=5), pol,
                plan.breaks)
    except Done:
        pass
    calls.clear()
