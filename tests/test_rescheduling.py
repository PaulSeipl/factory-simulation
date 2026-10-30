from pathlib import Path

import pytest

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import best_dispatch, dispatch, dispatch_planner, ect, least_load, spt
from simulation.sim.des import PlanNotExecutable
from simulation.sim.scenario import Scenario, sample_scenario

DATA = Path(__file__).parents[1] / "data"
PATHS = [
    DATA / "instances" / "toy-3x3.json",
    DATA / "instances" / "toy-dag-3x4.json",
    *sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs")),
]
REPAIR = ReschedulingPolicy()  # repair only


def compiled(path: Path) -> CompiledInstance:
    return compile_instance(load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance))


def by_op(schedule: list[Assignment]) -> list[Assignment]:
    return sorted(schedule, key=lambda a: (a.order_id, a.op_id))


TOY_INSTANCE = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
TOY = compile_instance(TOY_INSTANCE)
# hand-checked feasible plan (tests/test_feasibility.py), makespan 11; every planned start is tight
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]
GAP_PLAN = [a.model_copy(update={"start": 9, "end": 11}) if a.op_id == "c2" else a for a in PLAN]


def disturbed(factor=None, offset=None) -> Scenario:
    factor, offset = factor or {}, offset or {}
    return Scenario(instance=TOY.name, seed=0, sigma=0, factors=[
        {"order_id": o.id, "op_id": op.id, "factor": factor.get(op.id, 1.0), "start_offset": offset.get(op.id, 0)}
        for o in TOY_INSTANCE.orders for op in o.operations
    ])


def times(result) -> dict[str, tuple[int, int]]:
    return {a.op_id: (a.start, a.end) for a in result.schedule}


def makespan(result) -> int:
    return max(a.end for a in result.schedule)


def of_type(result, kind: str) -> list[dict]:
    return [d for d in result.decisions if d["type"] == kind]


# --- repair (left/right shift) ------------------------------------------------------------------


@pytest.mark.parametrize("plan", [PLAN, GAP_PLAN], ids=["tight", "gap"])
def test_repair_without_disturbance_changes_nothing(plan):
    result = execute(TOY, plan, policy=REPAIR)
    assert by_op(result.schedule) == by_op(plan) and result.decisions == []


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_zero_disturbance_with_repair_for_cpsat_plans(path):
    # CP-SAT plans may contain gaps; the repair must not close them without a deviation
    ci = compiled(path)
    plan = solve(ci, time_limit=1, workers=1, hint=best_dispatch(ci)[1]).schedule
    assert by_op(execute(ci, plan, policy=REPAIR).schedule) == by_op(plan)


def test_early_finish_is_used_only_with_repair():
    # a1 takes round(3 * 2/3) = 2: without repair nothing moves (makespan 11), with repair the tight chain does
    assert makespan(execute(TOY, PLAN, disturbed({"a1": 2 / 3}))) == 11
    assert times(execute(TOY, PLAN, disturbed({"a1": 2 / 3}), REPAIR)) == {
        "a1": (0, 2), "a2": (2, 5), "a3": (5, 7), "b1": (2, 4), "b2": (4, 7), "b3": (4, 8), "b4": (8, 10),
        "c1": (5, 7), "c2": (7, 9),
    }


def test_repair_keeps_a_planned_gap():
    assert times(execute(TOY, GAP_PLAN, disturbed({"a1": 2 / 3}), REPAIR))["c2"] == (9, 11)


def test_late_finish_with_repair_shifts_right_and_records_the_changes():
    result = execute(TOY, PLAN, disturbed({"b1": 2.0}), REPAIR)
    assert times(result)["b4"] == (11, 13)
    repairs = of_type(result, "REPAIR")
    assert [d["t"] for d in repairs] == [5, 6] and all(d["makespan_change"] == 1 for d in repairs)


def test_late_start_offset_is_counted_once_with_repair():
    # a2 planned at 3 with offset +2 starts at 5, not at 7 after the repair has moved its planned start to 5
    realized = times(execute(TOY, PLAN, disturbed(offset={"a2": 2}), REPAIR))
    assert realized["a2"] == (5, 8) and realized["a3"] == (8, 10) and realized["c1"] == (8, 10)


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_disturbed_execution_with_offsets_and_repair_is_feasible(path, seed):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    inst = load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)
    sc = sample_scenario(inst, sigma=0.3, seed=seed, q=0.5, max_early=5, max_late=5)
    realized = execute(ci, plan, sc, REPAIR).schedule
    assert {v.constraint for v in check_schedule(ci, realized)} <= {"C2"}  # durations differ by design
    planned = {(a.order_id, a.op_id): a.machine for a in plan}
    assert all(a.machine == planned[a.order_id, a.op_id] for a in realized)


# --- complete rescheduling triggered by thresholds (math/05, section 3) ---------------------


def test_no_disturbance_no_rescheduling():
    result = execute(TOY, PLAN, policy=ReschedulingPolicy(dispatch_planner(spt), max_makespan_change=0))
    assert by_op(result.schedule) == by_op(PLAN) and result.decisions == []


def test_rescheduling_with_a_rule_can_make_the_makespan_worse():
    # b1 takes 4: at t=5 the rule plan projects 13 > 12 of the repaired plan and is accepted (no improvement
    # condition); realized 14, while repair alone realizes 13 (observation in math/05)
    policy = ReschedulingPolicy(dispatch_planner(spt), max_makespan_change=0)
    result = execute(TOY, PLAN, disturbed({"b1": 2.0}), policy)
    assert [(d["t"], d["accepted"], d["makespan_before"], d["makespan_after"]) for d in of_type(result, "REPLAN")] == [
        (5, True, 12, 13), (6, True, 14, 14)]
    assert makespan(result) == 14
    assert makespan(execute(TOY, PLAN, disturbed({"b1": 2.0}), REPAIR)) == 13


def test_change_budget_rejects_plans_with_too_many_new_machine_assignments():
    policy = ReschedulingPolicy(dispatch_planner(spt), max_makespan_change=0, change_budget=0)
    result = execute(TOY, PLAN, disturbed({"b1": 2.0}), policy)
    assert [(d["accepted"], d["changed_assignments"]) for d in of_type(result, "REPLAN")] == [(False, 2), (False, 2)]
    assert makespan(result) == 13


def test_better_plan_from_rescheduling():
    # start from the weak SPT + least-load plan (makespan 15); b1 takes 6 instead of 4. Repair alone: 17.
    # At t=6 the ECT + SPT plan from the snapshot projects 14 instead of 16.
    plan = dispatch(TOY, spt, least_load)
    sc = disturbed({"b1": 1.5})
    assert makespan(execute(TOY, plan, sc, REPAIR)) == 17
    result = execute(TOY, plan, sc, ReschedulingPolicy(dispatch_planner(spt, ect), max_makespan_change=0))
    assert [(d["t"], d["accepted"], d["makespan_before"], d["makespan_after"]) for d in of_type(result, "REPLAN")] == [
        (6, True, 16, 14)]
    assert makespan(result) == 14


def test_infeasible_plan_from_the_planner_raises():
    def broken(ci, snapshot, current):
        return [a.model_copy(update={"start": 0, "end": a.end - a.start}) for a in current]  # everything at 0

    with pytest.raises(PlanNotExecutable, match="planner returned an infeasible plan"):
        execute(TOY, PLAN, disturbed({"b1": 2.0}), ReschedulingPolicy(broken, max_makespan_change=0))


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_disturbed_execution_with_rescheduling_is_feasible(path, seed):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    inst = load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)
    sc = sample_scenario(inst, sigma=0.3, seed=seed, q=0.5, max_early=5, max_late=5)
    policy = ReschedulingPolicy(dispatch_planner(spt, ect), max_makespan_change=2, max_shift=10)
    realized = execute(ci, plan, sc, policy).schedule
    assert {v.constraint for v in check_schedule(ci, realized)} <= {"C2"}
