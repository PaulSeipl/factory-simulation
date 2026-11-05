"""Schedule format with workers and breaks (math/04_workers.md, section 5); structure only, feasibility is the
checker's job."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model, write_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break, Schedule
from simulation.planners.cpsat import solve

DATA = Path(__file__).parents[1] / "data" / "instances"


def test_assignment_without_machine():
    a = Assignment(order_id="k", op_id="pack", machine=None, start=0, end=20, workers=("W1",))
    assert (a.machine, a.workers) == (None, ("W1",))


def test_machine_stays_required():
    with pytest.raises(ValidationError, match="machine"):
        Assignment.model_validate({"order_id": "k", "op_id": "pack", "start": 0, "end": 20})


def test_schedule_with_breaks_roundtrip(tmp_path):
    schedule = Schedule(
        assignments=(Assignment(order_id="k", op_id="print", machine="P", start=0, end=60, workers=("W2",)),),
        breaks=(Break(worker="W1", start=240), Break(worker="W2", start=255)),
    )
    write_model(schedule, tmp_path / "plan.json")
    assert read_model(tmp_path / "plan.json", Schedule) == schedule


def test_negative_break_start_rejected():
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Break(worker="W1", start=-1)


def test_old_schedule_still_feasible():
    ci = compile_instance(read_model(DATA / "toy-3x3.json", Instance))
    plan = solve(ci, time_limit=5, workers=1).schedule
    old = Schedule.model_validate({"assignments": [a.model_dump(exclude={"workers"}) for a in plan]})
    assert old.breaks == () and all(a.workers == () for a in old.assignments)
    assert check_schedule(ci, old.assignments) == []
