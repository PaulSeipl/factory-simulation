from functools import cache
from itertools import product
from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import best_dispatch

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
