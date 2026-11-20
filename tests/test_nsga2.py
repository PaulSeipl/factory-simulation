"""NSGA-II over the GA's random keys (math/14_genetic-algorithm.md §3a): sorting, crowding, fronts. Small instances."""

import math

import pytest
from test_ga import DAY, INSTANCES, late_pack

from simulation.check.feasibility import check_schedule
from simulation.objectives import MAKESPAN, OVERTIME
from simulation.planners.nsga2 import NsgaParams, crowding_distances, dominates, non_dominated_fronts, nsga2

FAST = NsgaParams(population=10, generations=5, time_limit=None)


def test_dominance_by_hand():
    assert dominates((1, 2), (1, 3)) and dominates((1, 2), (2, 3))
    assert not dominates((1, 2), (1, 2)) and not dominates((1, 3), (2, 2)) and not dominates((2, 2), (1, 3))


def test_fronts_by_hand():
    # (1,5), (2,2), (5,1) trade off; (3,3) is dominated by (2,2) only; (4,4) also by (3,3); (6,6) by all
    values = [(1, 5), (2, 2), (5, 1), (3, 3), (4, 4), (6, 6)]
    assert non_dominated_fronts(values) == [[0, 1, 2], [3], [4], [5]]


def test_crowding_by_hand():
    # front (1,5), (2,2), (5,1): the extremes infinite; the middle (5-1)/(5-1) in each objective = 2
    values = [(1, 5), (2, 2), (5, 1)]
    assert crowding_distances([0, 1, 2], values) == {0: math.inf, 1: 2.0, 2: math.inf}


def test_overtime_trade_off_by_hand():
    # the late pack (tests/test_ga.py): Monday with 30 minutes overtime ends at 600, Tuesday without at 1530
    result = nsga2(late_pack(), [MAKESPAN, OVERTIME], FAST)
    assert [v for v, _ in result.front] == [(600, 30), (DAY + 90, 0)]


def test_front_plans_are_feasible_and_mutually_non_dominated():
    ci = INSTANCES["s-batches"]()
    result = nsga2(ci, [MAKESPAN, OVERTIME], FAST)
    assert result.front and result.generations == FAST.generations
    for values, plan in result.front:
        assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
        assert values == (MAKESPAN.evaluate(ci, plan.assignments), OVERTIME.evaluate(ci, plan.assignments))
    vs = [v for v, _ in result.front]
    assert len(set(vs)) == len(vs) and not any(dominates(a, b) for a in vs for b in vs)


def test_same_seed_same_front():
    ci = INSTANCES["toy-3x3"]()
    a, b = nsga2(ci, [MAKESPAN, OVERTIME], FAST), nsga2(ci, [MAKESPAN, OVERTIME], FAST)
    assert a.front == b.front


@pytest.mark.parametrize(("params", "message"), [
    ({"generations": None, "time_limit": None}, "generation limit, a time limit or both"),
    ({"population": 1}, "at least two"),
])
def test_invalid_params_rejected(params, message):
    with pytest.raises(ValueError, match=message):
        NsgaParams(**params)


def test_start_deviation_by_hand():
    from simulation.model.schedule import Assignment
    from simulation.objectives import start_deviation

    ref = [Assignment(order_id="k", op_id=i, machine="M", start=s, end=s + 1) for i, s in (("a", 0), ("b", 5))]
    moved = [ref[0].model_copy(update={"start": 3, "end": 4}), ref[1].model_copy(update={"start": 1, "end": 2}),
             Assignment(order_id="new", op_id="a", machine="M", start=9, end=10)]  # not in the reference: ignored
    objective = start_deviation(ref)
    assert objective.evaluate(None, ref) == 0 and objective.evaluate(None, moved) == 3 + 4
    with pytest.raises(NotImplementedError, match="offline analysis"):
        objective.cpsat()


def test_stability_front_starts_at_the_reference():
    # makespan against deviation from the encoded SPT/ECT plan: the deviation-0 end of the front is a plan that keeps
    # every start of the reference (the decoded warm start reproduces it here), the other end shortens the makespan
    from simulation.objectives import start_deviation
    from simulation.planners.dispatching import dispatch_plan, ect, spt

    ci = INSTANCES["toy-dag-3x4"]()
    ref = dispatch_plan(ci, spt, ect).assignments
    result = nsga2(ci, [MAKESPAN, start_deviation(ref)], FAST)
    assert all(check_schedule(ci, p.assignments, breaks=p.breaks) == [] for _, p in result.front)
    assert min(v[1] for v, _ in result.front) == 0
