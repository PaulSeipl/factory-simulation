"""Does the join key hurt NSGA-II? Fidentis with s-batches, (makespan, overtime), 4 seeds, join keys used or ignored,
120 s per run, 4 runs in parallel (math/14 §5c, protocol (87)). Run: uv run python notebooks/nsga_join_check.py"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ga_runs import FRONT_TIME, instance  # noqa: E402

from simulation.check.feasibility import check_schedule  # noqa: E402
from simulation.objectives import MAKESPAN, OVERTIME  # noqa: E402
from simulation.planners.nsga2 import NsgaParams, nsga2  # noqa: E402

OUT = Path(__file__).parent / "results/nsga_join_check.json"
SEEDS = range(1, 5)


def one(join: bool, seed: int) -> dict:
    ci = instance("fidentis", True)
    r = nsga2(ci, [MAKESPAN, OVERTIME], NsgaParams(time_limit=FRONT_TIME, seed=seed, join=join))
    return {"join": join, "seed": seed, "front": [list(v) for v, _ in r.front], "generations": r.generations,
            "feasible": all(check_schedule(ci, p.assignments, breaks=p.breaks) == [] for _, p in r.front)}


if __name__ == "__main__":
    jobs = [(j, s) for j in (True, False) for s in SEEDS]
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(one, *zip(*jobs, strict=True)))
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for r in rows:
        print(r["join"], r["seed"], r["generations"], r["feasible"], r["front"])
