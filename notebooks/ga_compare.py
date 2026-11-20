"""GA against rule and CP-SAT on the Fidentis case (10 orders), makespan, 60 s per run (math/14 §5a).

Runs the BRKGA with and without s-batches, with the delay window (default) and without it (delay factor 0), for
several seeds in parallel (one core per run: the GA is single-threaded). Results are stored in
notebooks/results/ga_compare.json with a digest of the Fidentis parameters; RECOMPUTE=1 in the environment reruns.
The rule and CP-SAT values come from notebook 08's stored results (60 s, 12 threads).

    uv run python notebooks/ga_compare.py
"""

import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule, worker_intervals
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.schedule import Schedule
from simulation.objectives import MAKESPAN, overtime
from simulation.planners.ga import GaParams, solve_ga

ROOT = Path(__file__).parents[1]
FIDENTIS = read_model(ROOT / "data/generator/fidentis.json", CarrierGeneratorParams)
OUT = ROOT / "notebooks/results/ga_compare.json"
SETTINGS = {"brkga": {}, "no-delay": {"delay_max": 0}}
DIGEST = hashlib.sha256((FIDENTIS.model_dump_json() + repr(SETTINGS)).encode()).hexdigest()[:12]
TIME_LIMIT = 60.0
SEEDS = range(1, 7)


def instance(variant: str):
    params = FIDENTIS if variant == "with" else FIDENTIS.model_copy(update={"s_batch_steps": {}})
    return compile_instance(generate_carrier_instance(params))


def batch_stats(ci, plan):
    batches = {}
    for a in plan:
        if a.batch:
            batches.setdefault(a.batch, []).append(ci.op_index[a.order_id, a.op_id])
    return len(batches), sum((len(ops) - 1) * ci.s_setup[ops[0]] for ops in batches.values())


def one_run(variant: str, setting: str, seed: int) -> dict:
    ci = instance(variant)
    result = solve_ga(ci, MAKESPAN, GaParams(time_limit=TIME_LIMIT, seed=seed, **SETTINGS[setting]))
    plan = result.plan
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in plan.assignments}
    n_batches, saved = batch_stats(ci, plan.assignments)
    return {
        "variant": variant, "setting": setting, "seed": seed, "makespan": result.value,
        "overtime": overtime(ci, plan.assignments),
        "worker_minutes": sum(e - s for ivs in worker_intervals(ci, by_op).values() for s, e, _ in ivs),
        "batches": n_batches, "saved": saved, "generations": result.generations,
        "evaluations": result.evaluations, "first": result.history[0], "history": list(result.history),
        "feasible": check_schedule(ci, plan.assignments, breaks=plan.breaks) == [],
        "plan": Schedule(assignments=plan.assignments, breaks=plan.breaks).model_dump(mode="json"),
    }


def compute() -> list[dict]:
    jobs = [(v, s, seed) for v in ("without", "with") for s in SETTINGS for seed in SEEDS]
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        return list(pool.map(one_run, *zip(*jobs, strict=True)))


def main() -> None:
    if OUT.exists() and not os.environ.get("RECOMPUTE"):
        stored = json.loads(OUT.read_text(encoding="utf-8"))
        if stored["digest"] == DIGEST and stored["time_limit"] == TIME_LIMIT:
            runs = stored["runs"]
        else:
            sys.exit("stored results are for other parameters: set RECOMPUTE=1")
    else:
        runs = compute()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"digest": DIGEST, "time_limit": TIME_LIMIT, "runs": runs}), encoding="utf-8")
    nb08 = json.loads((ROOT / "notebooks/results/08/s_batches.json").read_text(encoding="utf-8"))["value"]["rows"]
    print(f"{'s-batches':9} {'planner':9} {'best':>6} {'mean':>8} {'worst':>6} {'overtime':>8} {'worker':>6} "
          f"{'batches':>7} {'saved':>5} {'gens':>5} {'first':>6} feasible")
    for variant in ("without", "with"):
        for row in nb08:
            if row[0] == variant:
                print(f"{variant:9} {row[1]:9} {row[2]:6} {'':>8} {'':>6} {row[4]:8} {row[6]:6} {row[7]:7} {row[9]:5}")  # noqa: T201
        for setting in SETTINGS:
            rs = [r for r in runs if r["variant"] == variant and r["setting"] == setting]
            best = min(rs, key=lambda r: r["makespan"])
            print(f"{variant:9} {setting:9} {best['makespan']:6} {mean(r['makespan'] for r in rs):8.0f} "
                  f"{max(r['makespan'] for r in rs):6} {best['overtime']:8} {best['worker_minutes']:6} "
                  f"{best['batches']:7} {best['saved']:5} {round(mean(r['generations'] for r in rs)):5} "
                  f"{best['first']:6} {all(r['feasible'] for r in rs)}")


if __name__ == "__main__":
    main()
