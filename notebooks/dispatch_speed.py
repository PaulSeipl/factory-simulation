"""Equality check and timing of dispatch_plan against a saved old copy (math/11_dispatching-rules.md §5).

usage: uv run python notebooks/dispatch_speed.py OLD_DISPATCHING_PY [OLD_CALENDAR_PY] [--timing-only]

Every plan of the current `dispatch_plan` must equal the old one's: every rule combination, `ga.decode` with 20
random chromosomes per instance, and from DES snapshots (disturbed durations). Then a timing table (one decode).
"""

import importlib.util
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_s_batch_format import tiny  # noqa: E402

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance  # noqa: E402
from simulation.io.brandimarte_loader import load_fjs  # noqa: E402
from simulation.io.json_loader import read_model  # noqa: E402
from simulation.model.compiled import compile_instance  # noqa: E402
from simulation.model.instance import Instance  # noqa: E402
from simulation.planners import dispatching as new  # noqa: E402
from simulation.sim.des import Simulation  # noqa: E402
from simulation.sim.scenario import Scenario  # noqa: E402

DATA = ROOT / "data"
BRANDIMARTE = DATA / "benchmarks" / "brandimarte"


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_old(path: str, calendar_path: str | None = None):
    """The old dispatching module; with the old calendar module, its shift_window too (dispatching's only use)."""
    mod = load("simulation.planners.dispatching_old", path)
    if calendar_path is not None:
        mod.shift_window = load("simulation.calendar_old", calendar_path).shift_window
    return mod


def check_shift_window(calendar_path: str) -> int:
    """New calendar.shift_window equal to the old one (result or error) on random calendars and arguments."""
    from simulation import calendar as cal_new
    from simulation.calendar import WeekCalendar
    old = load("simulation.calendar_old", calendar_path).shift_window
    rng, bad = random.Random(3), 0
    for _ in range(200_000):
        start = rng.randrange(0, 720)
        cal = WeekCalendar(origin=rng.randrange(0, 10080), shift_start=start, shift_end=start + rng.randrange(60, 720),
                           break_earliest=0, break_latest=0, break_length=0, max_overtime=0, cutoff=0,
                           working_days=tuple(sorted(rng.sample(range(7), rng.randrange(0, 8)))))
        args = (cal, rng.randrange(-2000, 30000), rng.randrange(0, 800), cal.shift_end + rng.randrange(0, 120))
        bad += outcome(cal_new.shift_window, *args) != outcome(old, *args)
    print(f"shift_window: 200000 random calls, {bad} differences")
    return bad


def generated(name: str):
    return compile_instance(generate_carrier_instance(read_model(DATA / "generator" / name, CarrierGeneratorParams)))


INSTANCES = {
    **{n: (lambda n=n: compile_instance(read_model(DATA / "instances" / f"{n}.json", Instance)))
       for n in ["toy-3x3", "toy-dag-3x4", "toy-workers", "toy-carriers", "toy-workshop"]},
    **{f"mk{i:02d}": (lambda i=i: compile_instance(load_fjs(BRANDIMARTE / f"BrandimarteMk{i}.fjs")))
       for i in range(1, 11)},
    "dental-example": lambda: generated("dental-carriers-example.json"),
    "dental-workers": lambda: generated("dental-carriers-workers.json"),
    "s-batches": lambda: compile_instance(Instance.model_validate(
        tiny(6, orders=12, polish={"setup": 5, "capacity": 12}, pack={"setup": 5}).model_dump(mode="json")
        | {"calendar": {}})),
}


N_KEYS = 4  # priority, machine, delay, overtime: as ga.decode, copied so that edits to planners/ga.py don't matter


def delay_unit(ci, factor):
    return factor * max(max((p for _, p in opts), default=ci.fixed_duration[o]) for o, opts in enumerate(ci.options))


def decode_with(mod, ci, genes, unit, snapshot=None):
    """ga.decode's call of dispatch_plan: random keys -> priorities, machines, delays, overtime allowances."""
    n = ci.n_ops
    seq, mach = genes[:n], genes[n:2 * n]
    max_ot = ci.calendar.max_overtime if ci.calendar is not None else 0
    return mod.dispatch_plan(
        ci, lambda _c, _s, o, _m, _p: (seq[o],),
        lambda _c, _s, o: ci.options[o][int(mach[o] * len(ci.options[o]))][0], snapshot,
        delay=[round(g * unit) for g in genes[2 * n:3 * n]], overtime=[round(g * max_ot) for g in genes[3 * n:]])


def outcome(f, *args):
    try:
        return f(*args)
    except ValueError as e:  # both versions must raise the same error
        return ("ValueError", str(e))


def snapshots(ci, n=3, seed=0):
    rng = random.Random(seed)
    plan = new.dispatch_plan(ci, new.spt, new.ect)
    end = max(a.end for a in plan.assignments)
    out = []
    for i in range(n):
        rows = [{"order_id": k, "op_id": j, "factor": rng.uniform(0.7, 1.6), "start_offset": 0} for k, j in ci.op_keys]
        sim = Simulation(ci, plan.assignments, Scenario(instance=ci.name, seed=i, sigma=0.3, factors=rows), plan.breaks)
        sim.run(until=end * (i + 1) // (n + 1))
        out.append(sim.snapshot())
    return out


def check(old) -> int:
    bad = 0
    for name, make in INSTANCES.items():
        ci = make()
        rng = random.Random(1)
        unit = delay_unit(ci, 0.5)
        cases = 0
        snaps = [None, *snapshots(ci)]
        for snap in snaps:
            for s in new.SEQUENCING_RULES:
                for a in [*new.ASSIGNMENT_RULES, None]:
                    args = (ci, new.SEQUENCING_RULES[s], new.ASSIGNMENT_RULES[a] if a else None, snap)
                    oargs = (ci, old.SEQUENCING_RULES[s], old.ASSIGNMENT_RULES[a] if a else None, snap)
                    cases += 1
                    if outcome(new.dispatch_plan, *args) != outcome(old.dispatch_plan, *oargs):
                        bad += 1
                        print(f"DIFF {name} snap={snap is not None} {s}/{a}")
            for _ in range(20 if snap is None else 5):
                genes = [rng.random() for _ in range(N_KEYS * ci.n_ops)]
                cases += 1
                if outcome(decode_with, new, ci, genes, unit, snap) != outcome(decode_with, old, ci, genes, unit, snap):
                    bad += 1
                    print(f"DIFF {name} snap={snap is not None} decode")
        print(f"{name}: {cases} plans compared")
    return bad


def timing(old):
    insts = {**INSTANCES, "fidentis": lambda: generated("fidentis.json")}
    print("| instance | ops | old ms | new ms | speed-up |\n|---|---|---|---|---|")
    for name, make in insts.items():
        ci = make()
        rng = random.Random(2)
        unit = delay_unit(ci, 0.5)
        chroms = [[rng.random() for _ in range(N_KEYS * ci.n_ops)] for _ in range(5)]
        res = {"old": float("inf"), "new": float("inf")}
        for _ in range(7):  # interleaved rounds, minimum per version: robust against machine noise
            for label, mod in (("old", old), ("new", new)):
                t = time.perf_counter()
                for g in chroms:
                    outcome(decode_with, mod, ci, g, unit)
                res[label] = min(res[label], (time.perf_counter() - t) / len(chroms) * 1000)
        print(f"| {name} | {ci.n_ops} | {res['old']:.1f} | {res['new']:.1f} | {res['old'] / res['new']:.1f}x |")


if __name__ == "__main__":
    # argv: OLD_DISPATCHING_PY [OLD_CALENDAR_PY] [--timing-only]
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    old = load_old(*paths)
    if "--timing-only" not in sys.argv:
        bad = check(old) + (check_shift_window(paths[1]) if len(paths) > 1 else 0)
        print("ALL EQUAL" if bad == 0 else f"{bad} DIFFERENCES")
    timing(old)
