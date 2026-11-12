from functools import cache
from itertools import product
from pathlib import Path

import pytest

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.due_dates import assign_due_dates
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN, TARDY_ORDERS, TOTAL_TARDINESS, lexicographic
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import best_dispatch, dispatch, ect, edd, spt
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"
TOY_INSTANCE = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
TOY_DUE_1 = compile_instance(assign_due_dates(TOY_INSTANCE, (1.0,), 0))  # due A 10, B 11, C 10 (test_due_dates)
TOY_DUE_05 = compile_instance(assign_due_dates(TOY_INSTANCE, (0.5,), 0))  # due A 5, B 7, C 7
# hand-checked feasible plan (tests/test_feasibility.py): order ends A 8, B 11, C 10
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]


def test_due_dates_are_compiled_per_order():
    assert TOY_DUE_1.due_date == (10, 11, 10)
    assert compile_instance(TOY_INSTANCE).due_date == (None, None, None)


def test_tardiness_by_hand():
    assert (TOTAL_TARDINESS.evaluate(TOY_DUE_1, PLAN), TARDY_ORDERS.evaluate(TOY_DUE_1, PLAN)) == (0, 0)
    # (8 - 5) + (11 - 7) + (10 - 7)
    assert (TOTAL_TARDINESS.evaluate(TOY_DUE_05, PLAN), TARDY_ORDERS.evaluate(TOY_DUE_05, PLAN)) == (10, 3)


def test_orders_without_due_date_are_not_penalized():
    data = TOY_INSTANCE.model_dump()
    data["orders"][1]["due_date"] = 9  # only B: ends at 11
    ci = compile_instance(Instance.model_validate(data))
    assert (TOTAL_TARDINESS.evaluate(ci, PLAN), TARDY_ORDERS.evaluate(ci, PLAN)) == (2, 1)


def test_tardiness_needs_due_dates():
    ci = compile_instance(TOY_INSTANCE)
    with pytest.raises(ValueError, match="has no due dates"):
        TOTAL_TARDINESS.evaluate(ci, PLAN)
    with pytest.raises(ValueError, match="has no due dates"):
        solve(ci, TARDY_ORDERS, time_limit=1)


def test_edd_beats_spt_on_one_machine():
    # X (p 3, due 3) and Y (p 1, due 10) on one machine. SPT: Y [0, 1), X [1, 4), X is 1 late. EDD: X first, none late.
    ci = compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "edd", "machines": ["M1"], "orders": [
            {"id": "X", "due_date": 3, "operations": [{"id": "x", "step": "s", "options": {"M1": 3}}]},
            {"id": "Y", "due_date": 10, "operations": [{"id": "y", "step": "s", "options": {"M1": 1}}]},
        ]}))
    assert TOTAL_TARDINESS.evaluate(ci, dispatch(ci, spt, ect)) == 1
    assert TOTAL_TARDINESS.evaluate(ci, dispatch(ci, edd, ect)) == 0


def test_edd_with_ect_on_the_toy_by_hand():
    # due A 10, B 11, C 10. At t=8 a3 (A), c2 (C) and b4 (B) wait; c2 and b4 both on M2: c2 first (due 10 < 11),
    # so b4 runs [10, 13) and B is 2 late; A ends 10 and C ends 10, on time
    schedule = dispatch(TOY_DUE_1, edd, ect)
    assert {a.op_id: (a.machine, a.start, a.end) for a in schedule}["b4"] == ("M2", 10, 13)
    assert (TOTAL_TARDINESS.evaluate(TOY_DUE_1, schedule), TARDY_ORDERS.evaluate(TOY_DUE_1, schedule)) == (2, 1)


def test_edd_without_due_dates_equals_spt():
    ci = compile_instance(TOY_INSTANCE)
    assert dispatch(ci, edd, ect) == dispatch(ci, spt, ect)


def brute_force_tardiness(ci: CompiledInstance) -> dict[str, int | tuple[int, int]]:
    """Independent oracle: every assignment x every operation order, each operation as early as possible
    (semi-active schedules; all objectives here are regular, so one of them is optimal). Returns the minimum of
    each objective; lexicographic ones as tuples (Python compares tuples lexicographically)."""
    def orders(done=()):
        if len(done) == ci.n_ops:
            yield done
            return
        for o in range(ci.n_ops):
            if o not in done and all(q in done for q in ci.predecessors[o]):
                yield from orders((*done, o))

    sequences = list(orders())
    due = ci.due_date
    best: dict = {}
    for machines in product(*ci.options):
        for seq in sequences:
            free, end, order_end = [0] * ci.n_machines, [0] * ci.n_ops, [0] * len(due)
            for o in seq:
                m, p = machines[o]
                end[o] = max(ci.release[o], free[m], *(end[q] for q in ci.predecessors[o])) + p
                free[m] = end[o]
                order_end[ci.op_orders[o][0]] = max(order_end[ci.op_orders[o][0]], end[o])
            tardiness = sum(max(c - d, 0) for c, d in zip(order_end, due, strict=True))
            tardy = sum(c > d for c, d in zip(order_end, due, strict=True))
            values = {"total_tardiness": tardiness, "tardy_orders": tardy,
                      "total_tardiness>makespan": (tardiness, max(end)), "tardy_orders>makespan": (tardy, max(end))}
            for key, value in values.items():
                if key not in best or value < best[key]:
                    best[key] = value
    return best


@cache
def toy_optimum() -> dict[str, int]:  # CompiledInstance is not hashable, so the oracle is cached here
    return brute_force_tardiness(TOY_DUE_05)


@pytest.mark.parametrize("objective", [TOTAL_TARDINESS, TARDY_ORDERS], ids=lambda o: o.name)
def test_cpsat_optimum_matches_brute_force(objective):
    result = solve(TOY_DUE_05, objective, time_limit=10, workers=1)
    assert result.status == "OPTIMAL"
    assert result.objective == result.bound == toy_optimum()[objective.name]
    assert objective.evaluate(TOY_DUE_05, result.schedule) == result.objective


@pytest.mark.parametrize("primary", [TOTAL_TARDINESS, TARDY_ORDERS], ids=lambda o: o.name)
def test_lexicographic_optimum_matches_brute_force(primary):
    objective = lexicographic(primary, MAKESPAN)
    result = solve(TOY_DUE_05, objective, time_limit=10, workers=1)
    assert result.status == "OPTIMAL"
    values = (primary.evaluate(TOY_DUE_05, result.schedule), MAKESPAN.evaluate(TOY_DUE_05, result.schedule))
    assert values == toy_optimum()[objective.name]
    weight = MAKESPAN.spread(TOY_DUE_05) + 1  # H_0 + 1
    assert result.objective == objective.evaluate(TOY_DUE_05, result.schedule) == weight * values[0] + values[1]


def test_lexicographic_value_orders_schedules_like_tuples():
    objective = lexicographic(TARDY_ORDERS, TOTAL_TARDINESS, MAKESPAN)
    schedules = [PLAN] + [dispatch(TOY_DUE_05, rule, ect) for rule in (spt, edd)]
    schedules += [solve(TOY_DUE_05, o, time_limit=5, workers=1).schedule for o in (MAKESPAN, TOTAL_TARDINESS)]

    def as_tuple(s):
        return tuple(o.evaluate(TOY_DUE_05, s) for o in (TARDY_ORDERS, TOTAL_TARDINESS, MAKESPAN))

    for a in schedules:
        for b in schedules:
            lex = objective.evaluate(TOY_DUE_05, a) < objective.evaluate(TOY_DUE_05, b)
            assert lex == (as_tuple(a) < as_tuple(b))


def test_tardiness_first_then_makespan_on_mk01():
    # loose due dates: tardiness alone stops at a makespan of 52 (math/06); with the makespan as second level both
    # are optimal at once
    ci = compile_instance(assign_due_dates(load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs"),
                                           (1.5, 2.0, 2.5), 0))
    result = solve(ci, lexicographic(TOTAL_TARDINESS, MAKESPAN), time_limit=10, workers=1,
                   hint=best_dispatch(ci, TOTAL_TARDINESS)[1])
    assert result.status == "OPTIMAL"
    assert (TOTAL_TARDINESS.evaluate(ci, result.schedule), MAKESPAN.evaluate(ci, result.schedule)) == (0, 40)


@pytest.mark.parametrize("objective", [TOTAL_TARDINESS, TARDY_ORDERS, lexicographic(TOTAL_TARDINESS, MAKESPAN)],
                         ids=lambda o: o.name)
def test_cpsat_value_agrees_with_evaluation_also_when_not_optimal(objective):
    ci = compile_instance(assign_due_dates(load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs"),
                                           (0.5, 1.0, 1.5), 0))
    result = solve(ci, objective, time_limit=0.5, workers=1)
    assert check_schedule(ci, result.schedule) == []
    assert objective.evaluate(ci, result.schedule) == result.objective >= result.bound


def test_rescheduling_with_a_tardiness_objective():
    ci = compile_instance(inst := assign_due_dates(TOY_INSTANCE, (1.0,), 0))
    plan = solve(ci, TOTAL_TARDINESS, time_limit=5, workers=1).schedule
    policy = ReschedulingPolicy(cpsat_planner(time_limit=5, objective=lexicographic(TOTAL_TARDINESS, MAKESPAN)),
                                max_makespan_change=0)
    result = execute(ci, plan, sample_scenario(inst, sigma=0.3, seed=1), policy)
    assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}  # realized durations differ
    assert any(d["type"] == "REPLAN" for d in result.decisions)
