import copy
import json
from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible, check_schedule
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model, write_jsonl
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import best_dispatch
from simulation.sim.des import PlanNotExecutable, Simulation, replay
from simulation.sim.scenario import Scenario, sample_scenario

DATA = Path(__file__).parents[1] / "data"
PATHS = [
    DATA / "instances" / "toy-3x3.json",
    DATA / "instances" / "toy-dag-3x4.json",
    *sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs")),
]


def compiled(path: Path) -> CompiledInstance:
    return compile_instance(load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance))


def by_op(schedule: list[Assignment]) -> list[Assignment]:
    return sorted(schedule, key=lambda a: (a.order_id, a.op_id))


TOY = compiled(DATA / "instances" / "toy-dag-3x4.json")
# hand-checked feasible plan (tests/test_feasibility.py); a1 ends at 3 and b1 starts at 3 on M1
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]


def changed(op_id: str, **update) -> list[Assignment]:
    return [a.model_copy(update=update) if a.op_id == op_id else a for a in PLAN]


# --- zero-disturbance: realized schedule = plan ------------------------------------------


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_replay_of_rule_plan_equals_plan_and_keeps_its_makespan(path):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    realized = replay(ci, plan).schedule
    assert by_op(realized) == by_op(plan)
    assert MAKESPAN.evaluate(ci, realized) == MAKESPAN.evaluate(ci, plan)
    assert_feasible(ci, realized)


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_replay_of_cpsat_plan_equals_plan_and_keeps_its_makespan(path):
    # any CP-SAT solution (optimal or not): its objective value is the makespan the DES must realize
    ci = compiled(path)
    result = solve(ci, time_limit=1, hint=best_dispatch(ci)[1])
    assert result.status in ("OPTIMAL", "FEASIBLE")
    realized = replay(ci, result.schedule).schedule
    assert by_op(realized) == by_op(result.schedule)
    assert MAKESPAN.evaluate(ci, realized) == result.objective


def test_operation_does_not_start_before_its_planned_start():
    # c2 could start at 8 on M2, but the plan says 12: the DES waits although the machine is free
    late = changed("c2", start=12, end=14)
    realized = {a.op_id: a for a in replay(TOY, late).schedule}
    assert (realized["c2"].start, realized["c2"].end) == (12, 14)


def test_completion_is_processed_before_a_start_at_the_same_time():
    # a1 completes and b1 starts on M1 at t=3; otherwise b1 would wait for M1 and start late
    log = replay(TOY, PLAN).log
    at_3 = [(e["type"], e["op_id"]) for e in log if e["t"] == 3]
    assert at_3.index(("COMPLETE", "a1")) < at_3.index(("START", "b1"))


# --- plans that cannot be executed ----------------------------------------------------------


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        pytest.param(changed("b1", start=2, end=4), r"\[C5\].*overlap on M1", id="machine-overlap"),
        pytest.param(changed("b4", start=8, end=10), r"\[C3\].*b4.*before predecessor .*b3", id="before-predecessor"),
        pytest.param(changed("c1", start=1, end=3), r"\[C4\].*before release 4", id="before-release"),
        pytest.param(changed("c2", machine="M3"), r"\[C1\].*eligible", id="ineligible-machine"),
        pytest.param(PLAN[:-1], r"\[C1\].*c2.*not assigned", id="missing-op"),
        pytest.param([*PLAN, PLAN[0]], r"\[C1\].*assigned more than once", id="duplicate-op"),
        pytest.param(changed("b3", end=7), r"\[C2\].*b3", id="wrong-duration"),
    ],
)
def test_infeasible_plan_is_rejected_before_it_runs(plan, message):
    # waiting would otherwise silently repair the plan, so replay validates it with the checker first
    with pytest.raises(PlanNotExecutable, match=message):
        replay(TOY, plan)


# --- execution under disturbances ------------------------------------------------------------


def scenario(**factor_of_op) -> Scenario:
    inst = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
    return Scenario(instance=inst.name, seed=0, sigma=0, factors=[
        {"order_id": o.id, "op_id": op.id, "factor": factor_of_op.get(op.id, 1.0)}
        for o in inst.orders for op in o.operations
    ])


def test_longer_operation_shifts_its_successors_and_keeps_the_machine_order():
    # math/13_des.md, section 5: b1 takes 4 instead of 2; c2 could run at 8 on M2 but waits for b2 (planned first)
    realized = {a.op_id: (a.machine, a.start, a.end) for a in replay(TOY, PLAN, scenario(b1=2.0)).schedule}
    assert realized == {
        "a1": ("M1", 0, 3), "a2": ("M3", 3, 6), "a3": ("M4", 6, 8),
        "b1": ("M1", 3, 7), "b2": ("M2", 7, 10), "b3": ("M1", 7, 11), "b4": ("M4", 11, 13),
        "c1": ("M3", 6, 8), "c2": ("M2", 10, 12),
    }


def test_shorter_operation_does_not_pull_the_next_one_forward():
    # a1 takes round(1.5) = 2 instead of 3; b1 on M1 still starts at its planned 3
    realized = {a.op_id: (a.start, a.end) for a in replay(TOY, PLAN, scenario(a1=0.5)).schedule}
    assert realized["a1"] == (0, 2) and realized["b1"] == (3, 5)


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_sigma_zero_scenario_equals_replay_without_scenario(path):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    inst = load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)
    assert replay(ci, plan, sample_scenario(inst, sigma=0.0, seed=1)).schedule == replay(ci, plan).schedule


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_disturbed_execution_is_feasible_and_keeps_machine_order_and_planned_starts(path, seed):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    inst = load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)
    realized = replay(ci, plan, sample_scenario(inst, sigma=0.3, seed=seed)).schedule
    # realized durations differ from p, so C2 does not hold by design; all other constraints must
    assert {v.constraint for v in check_schedule(ci, realized)} <= {"C2"}
    planned = {(a.order_id, a.op_id): a for a in plan}
    for a in realized:
        p = planned[a.order_id, a.op_id]
        assert a.machine == p.machine and a.start >= p.start

    def machine_orders(schedule):
        return {m: [(a.order_id, a.op_id) for a in sorted(schedule, key=lambda a: a.start) if a.machine == m]
                for m in ci.machine_ids}

    assert machine_orders(realized) == machine_orders(plan)


# --- event log ---------------------------------------------------------------------------------


def test_log_has_one_start_and_one_completion_per_operation_in_time_order(tmp_path):
    log = replay(TOY, PLAN).log
    assert sorted((e["type"], e["op_id"]) for e in log) == sorted(
        (kind, a.op_id) for a in PLAN for kind in ("START", "COMPLETE")
    )
    assert [e["t"] for e in log] == sorted(e["t"] for e in log)
    write_jsonl(log, tmp_path / "events.jsonl")
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == log


# --- start offsets (no planning tool) --------------------------------------------------------


def disturbed(factor=None, offset=None) -> Scenario:
    inst = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
    factor, offset = factor or {}, offset or {}
    return Scenario(instance=inst.name, seed=0, sigma=0, factors=[
        {"order_id": o.id, "op_id": op.id, "factor": factor.get(op.id, 1.0), "start_offset": offset.get(op.id, 0)}
        for o in inst.orders for op in o.operations
    ])


GAP_PLAN = changed("c2", start=9, end=11)  # c2 could start at 8: a gap in the plan


def realized_times(plan, sc=None):
    return {a.op_id: (a.start, a.end) for a in replay(TOY, plan, sc).schedule}


def test_early_start_offset_starts_as_soon_as_possible():
    # c2 planned at 9 with offset -1: released at 8, c1 and b2 are done at 8, so it starts at 8
    assert realized_times(GAP_PLAN, disturbed(offset={"c2": -1}))["c2"] == (8, 10)


def test_early_start_offset_cannot_skip_a_predecessor():
    # b2 planned at 5 with offset -3: released at 2, but its predecessor b1 ends at 5
    assert realized_times(PLAN, disturbed(offset={"b2": -3}))["b2"] == (5, 8)


def test_late_start_offset_delays_the_operation_and_its_successors():
    realized = realized_times(PLAN, disturbed(offset={"a2": 2}))
    assert realized["a2"] == (5, 8) and realized["a3"] == (8, 10) and realized["c1"] == (8, 10)


def test_simulation_state_can_be_copied_mid_run():
    sim = Simulation(TOY, PLAN, disturbed({"b1": 2.0}))
    sim.run(until=5)
    clone = copy.deepcopy(sim)
    sim.run()
    clone.run()
    assert sim.realized() == clone.realized()


def test_plan_update_must_respect_the_frozen_part():
    sim = Simulation(TOY, PLAN)
    sim.run(until=4)  # a1 finished, a2 and b1 running
    moved = [a.model_copy(update={"start": 2, "end": 4}) if a.op_id == "b1" else a for a in sim.current_plan()]
    with pytest.raises(PlanNotExecutable, match=r"\[C7\]"):
        sim.update_plan(moved)
