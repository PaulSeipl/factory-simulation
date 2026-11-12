"""Objective levels of the worker model (spec §5; math/04_workers.md section 4, math/06_due-dates.md (O3); plan
docs/superpowers/plans/2026-11-09-workers-phase4-repair-cpsat.md, Task 5): level 1 tardiness + theta_O * overtime,
level 2 break postponement + spread, level 3 makespan.

t = 0 is Monday 08:00; 12:00 is t = 240 (Monday's cutoff), 15:00 t = 420, 19:00 t = 660, Tuesday 08:00 t = 1440,
Tuesday 12:00 t = 1680 (cutoff), Wednesday 12:00 t = 3120.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from test_cpsat_calendar import jobs
from test_dispatching_workers import RULES, TOY_MODEL

from simulation.calendar import DAY
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break, Plan
from simulation.objectives import (
    ACTIVE_MAKESPAN,
    BREAK_PENALTY,
    MAKESPAN,
    TOTAL_TARDINESS,
    cutoff_slack,
    level_weights,
    overtime,
    tardiness_and_overtime,
    worker_objective,
    worker_objective_with_slack,
)
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario


def chain(release, durations, due):
    """One worker, one order with machine-less operations in sequence (whole shares), the default calendar."""
    ops = [{"id": f"o{i}", "step": "s", "duration": d, "worker": {"whole": True},
            **({"predecessors": [f"o{i - 1}"]} if i else {})} for i, d in enumerate(durations)]
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "chain", "machines": ["M"], "workers": ["W1"], "calendar": {},
        "orders": [{"id": "K", "release": release, "due_date": due, "operations": ops}]}))


def optimum(ci, objective):
    result = solve(ci, objective, time_limit=10, workers=1)
    assert result.status == "OPTIMAL"
    assert check_schedule(ci, result.schedule, breaks=result.breaks) == []
    assert result.objective == objective.evaluate(ci, result.schedule, result.breaks)  # CP-SAT value = evaluated
    return result


@pytest.mark.parametrize(("theta", "late", "minutes"), [(Fraction(1, 60), 1, 0), (Fraction(1, 120), 0, 90)])
def test_overtime_only_when_it_is_worth_a_day(theta, late, minutes):
    # A (240) from Monday 15:00, then B (240), due Tuesday 12:00. With 90 minutes of overtime A ends at 19:00 and B
    # runs Tuesday 08:00-12:00: on time. Without, A runs Tuesday 08:00-12:00 and B after the break: one day late.
    # 1 day = 60 minutes of overtime is worth less than 90 (late); 1 day = 120 minutes is worth more (overtime)
    ci = chain(420, (240, 240), 1680)
    result = optimum(ci, worker_objective(theta))
    assert (TOTAL_TARDINESS.evaluate(ci, result.schedule), overtime(ci, result.schedule)) == (late, minutes)


def test_level_1_value_is_scaled_by_the_denominator():
    ci = chain(420, (240, 240), 1680)
    level = tardiness_and_overtime(Fraction(1, 120))
    assert optimum(ci, level).objective == 90  # 120 * 0 days + 1 * 90 minutes
    with pytest.raises(ValueError, match=">= 0"):
        tardiness_and_overtime(-1)


def test_breaks_come_before_the_makespan():
    # a job of 100 from 10:30, due far away: level 2 puts the break at 12:00 and the job at 13:00-14:40 (makespan 400);
    # the makespan alone runs it 10:30-12:10 with the break at 12:10
    ci = chain(150, (100,), 3120)
    lex = optimum(ci, worker_objective(Fraction(1, 60)))
    assert [(a.start, a.end) for a in lex.schedule] == [(300, 400)] and Break(worker="W1", start=240) in lex.breaks
    alone = optimum(ci, MAKESPAN)
    assert alone.objective == 250


def test_break_penalty_by_hand():
    # A at 12:20 and B at 12:00 on Monday, both at 12:00 on Tuesday: postponement 20, spread 20 (as M7)
    ci = jobs(("A", "B"), (10,), 0)
    breaks = (Break(worker="A", start=260), Break(worker="B", start=240),
              Break(worker="A", start=1680), Break(worker="B", start=1680))
    assert BREAK_PENALTY.evaluate(ci, [], breaks) == 40


def test_overtime_by_hand():
    # one share ending at 19:00 on Monday: 90 minutes after 17:30
    ci = jobs(("W1",), (240,), 420)
    plan = [Assignment(order_id="J0", op_id="op", machine=None, start=420, end=660, workers=("W1",))]
    assert overtime(ci, plan) == 90


@pytest.mark.parametrize("theta", [Fraction(1, 60), Fraction(1, 120), 0])
def test_lexicographic_order_on_rule_plans_and_the_optimum(theta):
    # on the trade-off instance: for the optimum and the 15 rule plans, the weighted value orders the plans exactly
    # as the level tuples do (the weights exceed the spreads), and the optimum has the smallest value
    ci = chain(420, (240, 240), 1680)
    objective = worker_objective(theta)
    levels = (tardiness_and_overtime(theta), BREAK_PENALTY, MAKESPAN)
    plans = [dispatch_plan(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None) for s, a in RULES]
    best = optimum(ci, objective)
    plans.append(Plan(best.schedule, best.breaks))
    keyed = [(tuple(f.evaluate(ci, p.assignments, p.breaks) for f in levels),
              objective.evaluate(ci, p.assignments, p.breaks)) for p in plans]
    assert sorted(keyed, key=lambda k: k[0]) == sorted(keyed, key=lambda k: k[1])
    assert min(v for _, v in keyed) == best.objective


def test_worker_objective_on_toy_workers_and_from_snapshots():
    # toy-workers with its calendar (due dates at Monday's cutoff): optimum 170 on time; then plans from disturbed
    # DES snapshots with the worker objective: OPTIMAL, value = evaluated value, accepted with their breaks
    ci = compile_instance(TOY_MODEL)
    objective = worker_objective(Fraction(1, 60))
    assert MAKESPAN.evaluate(ci, optimum(ci, objective).schedule) == 170
    start = dispatch_plan(ci, SEQUENCING_RULES["spt"])
    for seed in range(3):
        sc = sample_scenario(TOY_MODEL, sigma=0.6, seed=seed, q=0.4, max_late=30)
        for t in range(10, 400, 40):
            sim = Simulation(ci, start.assignments, sc, start.breaks)
            sim.run(until=t)
            snap = sim.snapshot()
            result = solve(ci, objective, time_limit=10, workers=1, snapshot=snap, hint=sim.current_plan())
            assert result.status == "OPTIMAL" and check_schedule(ci, result.schedule, snap, result.breaks) == []
            assert result.objective == objective.evaluate(ci, result.schedule, result.breaks)
            sim.update_plan(result.schedule, result.breaks)


OVERTIME_PLAN = [  # A Monday 15:00-19:00 (90 minutes of overtime), B Tuesday 08:00-12:00: on time
    Assignment(order_id="K", op_id="o0", machine=None, start=420, end=660, workers=("W1",)),
    Assignment(order_id="K", op_id="o1", machine=None, start=1440, end=1680, workers=("W1",)),
]
LATE_PLAN = [  # A Tuesday 08:00-12:00, break, B 13:00-17:00: one cutoff (Tuesday 12:00) missed
    Assignment(order_id="K", op_id="o0", machine=None, start=1440, end=1680, workers=("W1",)),
    Assignment(order_id="K", op_id="o1", machine=None, start=1740, end=1980, workers=("W1",)),
]
NOON = (Break(worker="W1", start=240), Break(worker="W1", start=1680))


def test_the_two_candidates_by_hand():
    # without the solver: both plans are feasible; level 1 is 90 * theta_O for the overtime plan, 1 for the late one
    ci = chain(420, (240, 240), 1680)
    for plan in (OVERTIME_PLAN, LATE_PLAN):
        assert check_schedule(ci, plan, breaks=NOON) == []
    assert (TOTAL_TARDINESS.evaluate(ci, OVERTIME_PLAN), overtime(ci, OVERTIME_PLAN)) == (0, 90)
    assert (TOTAL_TARDINESS.evaluate(ci, LATE_PLAN), overtime(ci, LATE_PLAN)) == (1, 0)
    level = tardiness_and_overtime(Fraction(1, 60))  # scaled by 60: 60 * T + 1 * ot
    assert (level.evaluate(ci, OVERTIME_PLAN), level.evaluate(ci, LATE_PLAN)) == (90, 60)


@pytest.mark.parametrize(("theta", "uses_overtime"), [
    (Fraction(1, 89), False),  # 90/89 > 1: a day late is cheaper
    (Fraction(1, 90), True),   # tie at level 1 (both 1); levels 2 equal (breaks at 12:00); level 3: 1680 < 1980
    (Fraction(1, 91), True),   # 90/91 < 1: overtime is cheaper
])
def test_threshold_at_one_ninetieth(theta, uses_overtime):
    ci = chain(420, (240, 240), 1680)
    assert (overtime(ci, optimum(ci, worker_objective(theta)).schedule) == 90) is uses_overtime


# --- level 3: the activity clock (user 2026-11-10: shifts, and outside them every operation in progress) ----------

def evening(ops):
    """One worker W1 and printer P, the default calendar (shift until 17:30 = 570); `ops` of one order K."""
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "evening", "machines": ["P"], "workers": ["W1"], "calendar": {},
        "orders": [{"id": "K", "release": 540, "due_date": 3120, "operations": ops}]}))


PRINT = {"id": "print", "step": "print", "options": {"P": 300}, "worker": {"prefix": 15}}
PACK = {"id": "pack", "step": "pack", "duration": 60, "worker": {"whole": True}, "predecessors": ["print"]}
REST = {"id": "dry", "step": "dry", "duration": 600, "worker": {"prefix": 30}}


def test_a_print_until_22_00_counts():
    # loaded at 17:00, printing until 22:00: 570 (Monday's shift) + 270 (17:30-22:00) = 840, as real time
    ci = evening([PRINT])
    plan = [Assignment(order_id="K", op_id="print", machine="P", start=540, end=840, workers=("W1",))]
    assert ACTIVE_MAKESPAN.evaluate(ci, plan) == 840


def test_the_dead_night_does_not_count():
    # then packaging Tuesday 08:00-09:00: real makespan 1500, the clock 570 + 270 + 60 = 900 (22:00-08:00 is dead)
    ci = evening([PRINT, PACK])
    plan = [Assignment(order_id="K", op_id="print", machine="P", start=540, end=840, workers=("W1",)),
            Assignment(order_id="K", op_id="pack", machine=None, start=1440, end=1500, workers=("W1",))]
    assert (MAKESPAN.evaluate(ci, plan), ACTIVE_MAKESPAN.evaluate(ci, plan)) == (1500, 900)
    result = optimum(ci, ACTIVE_MAKESPAN)
    assert result.objective == 900 and [(a.start, a.end) for a in result.schedule] == [(540, 840), (1440, 1500)]


def test_unattended_rest_counts():
    # prefix 17:00-17:30, rest until 03:00 (1140): 570 + 570 = 1140
    ci = evening([REST])
    plan = [Assignment(order_id="K", op_id="dry", machine=None, start=540, end=1140, workers=("W1",))]
    assert ACTIVE_MAKESPAN.evaluate(ci, plan) == 1140


def test_levels_one_after_another():
    # the sequential solve: per level the solver's value equals the level's evaluation; the combined value is the
    # weighted sum of (O3) with the weights `level_weights`
    ci = chain(420, (240, 240), 1680)
    objective = worker_objective(Fraction(1, 120))
    result = optimum(ci, objective)
    values = [f.evaluate(ci, result.schedule, result.breaks) for f in objective.levels]
    assert list(result.levels) == values
    assert result.objective == sum(w * v for w, v in zip(level_weights(ci, objective.levels), values, strict=True))


def test_later_level_survives_a_wrong_presolve_infeasible():
    # toy-workshop, snapshot at 589 from a disturbed run (protocol 2026-11-11 (40)): with OR-Tools 9.15 the bound
    # "level 1 <= 87" at exactly the level-1 optimum is INFEASIBLE with presolve and feasible without; solve retries
    # that level without presolve
    import json

    from simulation.io.json_loader import read_model
    from simulation.sim.snapshot import Snapshot

    root = Path(__file__).parent
    ci = compile_instance(read_model(root.parent / "data" / "instances" / "toy-workshop.json", Instance))
    snap = Snapshot.model_validate_json((root / "fixtures" / "workshop-presolve-snapshot.json").read_text())
    plan = [Assignment(**a) for a in json.loads((root / "fixtures" / "workshop-presolve-plan.json").read_text())]
    result = solve(ci, worker_objective(Fraction(1, 60)), time_limit=5, workers=1, snapshot=snap, hint=plan)
    assert result.levels[0] == 87
    assert check_schedule(ci, result.schedule, snap, result.breaks) == []


# --- cutoff slack (math/04_workers.md (O7), user 2026-11-11) ------------------------------------------------------

def two_orders():
    """One worker W1: A (90) ready Monday 16:30, B (150) ready Tuesday 08:00, both due Tuesday 12:00 (t = 1680)."""
    def order(k, release, duration):
        return {"id": k, "release": release, "due_date": 1680, "operations": [
            {"id": "op", "step": "s", "duration": duration, "worker": {"whole": True}}]}
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "two-orders", "machines": ["M"], "workers": ["W1"], "calendar": {},
        "orders": [order("A", 510, 90), order("B", 1440, 150)]}))


@pytest.mark.parametrize(("end", "shortfall"), [(1600, 0), (1660, 40), (1680, 60), (240, 0), (3090, 30)])
def test_cutoff_slack_by_hand(end, shortfall):
    # one order due Tuesday 12:00, buffer 60: ends 10:40 (0), 11:40 (40), 12:00 (60), Monday 11:55 (ships Tuesday:
    # 0), Wednesday 11:30 (one day late, ships Wednesday 12:00: 30)
    ci = compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "one", "machines": ["M"], "workers": ["W1"], "calendar": {},
        "orders": [{"id": "K", "due_date": 1680, "operations": [
            {"id": "op", "step": "s", "duration": 10, "worker": {"whole": True}}]}]}))
    plan = [Assignment(order_id="K", op_id="op", machine=None, start=end - 10, end=end, workers=("W1",))]
    assert cutoff_slack(60).evaluate(ci, plan) == shortfall
    with pytest.raises(ValueError, match="buffer"):
        cutoff_slack(DAY)


@pytest.mark.parametrize(("objective", "a_end", "minutes"), [
    (worker_objective(Fraction(1, 60)), 1680, 0),  # Tuesday: on time, no overtime, A ends at the cutoff
    (worker_objective_with_slack(60), 600, 30),  # Monday 16:30-18:00: 30 minutes overtime, 90 minutes slack
])
def test_cutoff_slack_buys_overtime_before_a_full_cutoff(objective, a_end, minutes):
    ci = two_orders()
    result = optimum(ci, objective)
    ends = {a.order_id: a.end for a in result.schedule}
    assert TOTAL_TARDINESS.evaluate(ci, result.schedule) == 0
    assert (ends["A"], overtime(ci, result.schedule)) == (a_end, minutes)
    if objective.name.startswith("total_tardiness"):
        assert result.levels[:3] == (0, 0, 30)  # tardiness, cutoff slack, overtime


def test_cutoff_slack_needs_a_calendar():
    plan = [Assignment(order_id="J0", op_id="op", machine=None, start=0, end=10, workers=("W1",))]
    ci = compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "nocal", "machines": ["M"], "workers": ["W1"],
        "orders": [{"id": "J0", "due_date": 20, "operations": [
            {"id": "op", "step": "s", "duration": 10, "worker": {"whole": True}}]}]}))
    with pytest.raises(ValueError, match="calendar"):
        cutoff_slack(60).evaluate(ci, plan)


def test_worker_objective_with_slack_on_toy_workshop():
    # toy-workshop: the model's horizon ends past a weekend, so the first cutoff after it lies days later (the term
    # variable's domain must reach C_k - c + buffer for C_k = 0); levels: on time, shortfall 20, overtime 30
    from simulation.io.json_loader import read_model

    path = Path(__file__).parents[1] / "data" / "instances" / "toy-workshop.json"
    ci = compile_instance(read_model(path, Instance))
    objective = worker_objective_with_slack(60)
    result = solve(ci, objective, time_limit=60, workers=1, deterministic_time=20)
    assert result.status == "OPTIMAL" and result.levels[:3] == (0, 20, 30)
    assert result.objective == objective.evaluate(ci, result.schedule, result.breaks)
    assert check_schedule(ci, result.schedule, breaks=result.breaks) == []
