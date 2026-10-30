from functools import cache
from itertools import product
from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible, check_schedule
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import best_dispatch, dispatch, least_load, spt
from simulation.planners.repair import repair
from simulation.sim.des import run
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot, snapshot

DATA = Path(__file__).parents[1] / "data"
TOYS = [DATA / "instances" / "toy-3x3.json", DATA / "instances" / "toy-dag-3x4.json"]


def compiled(path: Path) -> CompiledInstance:
    return compile_instance(load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance))


def linear_extensions(ci: CompiledInstance, done: tuple[int, ...] = ()):
    """All operation orders that respect the precedence graph."""
    if len(done) == ci.n_ops:
        yield done
        return
    for o in range(ci.n_ops):
        if o not in done and all(q in done for q in ci.predecessors[o]):
            yield from linear_extensions(ci, (*done, o))


@cache
def brute_force_makespan(path: Path) -> int:
    """Independent oracle: every assignment x every order, each op started as early as possible.

    Every semi-active schedule arises this way (order the ops by start time), and for a regular
    objective such as the makespan an optimal schedule is semi-active.
    """
    ci = compiled(path)
    orders = list(linear_extensions(ci))
    best = None
    for machines in product(*ci.options):
        for order in orders:
            free, end = [0] * ci.n_machines, [0] * ci.n_ops
            for o in order:
                m, p = machines[o]
                end[o] = max(ci.release[o], free[m], *(end[q] for q in ci.predecessors[o])) + p
                free[m] = end[o]
                if best is not None and end[o] >= best:  # cannot improve: makespan >= end[o]
                    break
            else:
                best = max(end)
    return best


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
@pytest.mark.parametrize("path", TOYS, ids=lambda p: p.stem)
def test_toy_optimum_matches_brute_force(path, warm):
    ci = compiled(path)
    result = solve(ci, time_limit=10, hint=best_dispatch(ci)[1] if warm else None)
    assert result.status == "OPTIMAL"
    assert result.objective == result.bound == brute_force_makespan(path)


@pytest.mark.parametrize("path", TOYS, ids=lambda p: p.stem)
def test_solution_is_feasible_and_objective_agrees(path):
    ci = compiled(path)
    result = solve(ci, time_limit=10)
    assert_feasible(ci, result.schedule)
    assert MAKESPAN.evaluate(ci, result.schedule) == result.objective


def test_mk01_feasible_and_not_worse_than_any_dispatching_rule():
    ci = compiled(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")
    result = solve(ci, time_limit=5)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert_feasible(ci, result.schedule)
    assert result.bound <= result.objective == MAKESPAN.evaluate(ci, result.schedule)
    assert result.objective <= MAKESPAN.evaluate(ci, best_dispatch(ci)[1])


def test_warm_start_on_mk10_not_worse_than_the_best_rule():
    # cold, CP-SAT stays above the best rule (227) within 10 s; with the rule as hint it starts from there
    ci = compiled(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk10.fjs")
    _, hint = best_dispatch(ci)
    result = solve(ci, time_limit=2, hint=hint)
    assert_feasible(ci, result.schedule)
    assert result.objective <= MAKESPAN.evaluate(ci, hint)


def test_without_solution_returns_empty_result():
    # a time limit of 0 seconds stops before any solution is found
    result = solve(compiled(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk10.fjs"), time_limit=0.0)
    assert result.status == "UNKNOWN"
    assert result.schedule == [] and result.objective is None and result.bound is None


# --- from a snapshot (complete rescheduling, math/05) ------------------------------------------

TOY_SNAPSHOT = Snapshot(instance="toy-dag-3x4", t=5, frozen=[
    FrozenOperation(order_id="A", op_id="a1", machine="M1", start=0, end=3, running=False),
    FrozenOperation(order_id="A", op_id="a2", machine="M3", start=3, end=6, running=True),
    FrozenOperation(order_id="B", op_id="b1", machine="M1", start=3, end=6, running=True),  # overrunning
])


def test_optimum_from_a_snapshot():
    # b2, b3 start at 6 at the earliest (b1), so b4 >= 9 + 2 = 11 needs b3 on M4 [6,9) and b4 on M4 [9,11),
    # but a3 (only M4, p 2, from 6) then ends at 13 or later; otherwise b3 on M1 ends at 10 and b4 at 12.
    # Hence 12 is optimal (math/12_cp-sat.md, section 7).
    ci = compiled(TOYS[1])
    result = solve(ci, time_limit=10, workers=1, snapshot=TOY_SNAPSHOT)
    assert result.status == "OPTIMAL" and result.objective == result.bound == 12
    assert check_schedule(ci, result.schedule, TOY_SNAPSHOT) == []


@pytest.mark.parametrize("budget", [0, 2])
def test_change_budget_limits_new_machine_assignments(budget):
    inst = load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")
    ci = compile_instance(inst)
    plan = dispatch(ci, spt, least_load)
    state, _ = run(ci, plan, sample_scenario(inst, 0.3, seed=1), until=12)
    snap = snapshot(ci, plan, state)
    reference = repair(ci, snap, plan)
    result = solve(ci, time_limit=2, workers=1, snapshot=snap, reference=reference, change_budget=budget,
                   hint=reference)
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    changed = sum(a.machine != b.machine for a, b in zip(result.schedule, reference, strict=True)
                  if (a.order_id, a.op_id) not in frozen)
    assert changed <= budget
    assert check_schedule(ci, result.schedule, snap) == []
    assert result.objective <= max(a.end for a in reference)  # the reference is a feasible solution
