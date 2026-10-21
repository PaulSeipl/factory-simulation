import json
from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model, write_jsonl
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import best_dispatch
from simulation.sim.des import PlanNotExecutable, replay

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
def test_replay_of_rule_plan_equals_plan(path):
    ci = compiled(path)
    _, plan = best_dispatch(ci)
    realized = replay(ci, plan).schedule
    assert by_op(realized) == by_op(plan)
    assert_feasible(ci, realized)


@pytest.mark.parametrize("path", [*PATHS[:2], DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs"],
                         ids=lambda p: p.stem)
def test_replay_of_cpsat_plan_equals_plan_and_keeps_its_makespan(path):
    ci = compiled(path)
    result = solve(ci, time_limit=10)
    assert result.status == "OPTIMAL"
    realized = replay(ci, result.schedule).schedule
    assert by_op(realized) == by_op(result.schedule)
    assert max(a.end for a in realized) == result.objective


def test_operation_does_not_start_before_its_planned_start():
    # c2 could start at 8 on M2, but the plan says 12: the DES waits although the machine is free
    late = changed("c2", start=12, end=14)
    realized = {a.op_id: a for a in replay(TOY, late).schedule}
    assert (realized["c2"].start, realized["c2"].end) == (12, 14)


def test_completion_is_processed_before_a_start_at_the_same_time():
    # a1 completes and b1 starts on M1 at t=3; otherwise the DES would see M1 busy and raise
    log = replay(TOY, PLAN).log
    at_3 = [(e["type"], e["op_id"]) for e in log if e["t"] == 3]
    assert at_3.index(("COMPLETE", "a1")) < at_3.index(("START", "b1"))


# --- plans that cannot be executed ----------------------------------------------------------


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        pytest.param(changed("b1", start=2, end=4), r"machine busy with \('A', 'a1'\)", id="machine-overlap"),
        pytest.param(changed("b4", start=8, end=10), r"predecessors not finished: \[\('B', 'b3'\)\]",
                     id="before-predecessor"),
        pytest.param(changed("c1", start=1, end=3), r"before release 4", id="before-release"),
        pytest.param(changed("c2", machine="M3"), r"not eligible", id="ineligible-machine"),
        pytest.param(PLAN[:-1], r"missing from the plan: \[\('C', 'c2'\)\]", id="missing-op"),
        pytest.param([*PLAN, PLAN[0]], r"planned more than once", id="duplicate-op"),
    ],
)
def test_plan_that_cannot_run_as_planned_is_rejected(plan, message):
    with pytest.raises(PlanNotExecutable, match=message):
        replay(TOY, plan)


def test_durations_come_from_the_instance_not_from_the_plan():
    # the plan claims b3 takes 2 on M1, the instance says 4: the DES realizes 4, so realized != plan
    realized = {a.op_id: a for a in replay(TOY, changed("b3", end=7)).schedule}
    assert (realized["b3"].start, realized["b3"].end) == (5, 9)


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
