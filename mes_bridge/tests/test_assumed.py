"""Assumed plates and prints before the nesting (slice 7, task 7.1b).

`problem_planned_flow.json`: recorded 2026-11-24 from a scratch MES database in the planned nesting flow: three
nested orders (each on its own print) and two orders that are planned but not nested (urgent, due tomorrow;
relaxed, due in 8 days), whose print and plate steps are keyed per order and whose secondary parts have no plate.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mes_bridge.api import ProblemOut
from mes_bridge.assumed import PLATES_PER_PRINT, assume_plates, assumed_print_id
from mes_bridge.instance import build_instance, epoch_of
from mes_bridge.once import solve

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def problem() -> ProblemOut:
    return ProblemOut.model_validate(json.loads((DATA / "problem_planned_flow.json").read_text(encoding="utf-8")))


def _loose_orders(problem):
    return sorted({p.order_id for p in problem.instance.parts if p.part_type == "SECONDARY" and p.carrier is None})


def test_the_recording_holds_orders_without_a_plate(problem):
    loose = _loose_orders(problem)
    assert len(loose) == 2
    keys = {o.key for o in problem.instance.operations}
    for o in loose:
        assert f"order:{o}:DATA_PREP_SECONDARY" in keys
        assert f"order:{o}:AM_PREP" in keys and f"order:{o}:PART_CLEANING" in keys
    with pytest.raises(ValueError):  # the instance cannot be built without plates
        build_instance(problem, epoch=epoch_of(problem.as_of, ZoneInfo("Europe/Berlin")))


def test_every_order_gets_a_plate_and_the_plates_share_prints_by_due_date(problem):
    out, aliases = assume_plates(problem)
    loose = _loose_orders(problem)
    assert all(p.carrier is not None for p in out.instance.parts if p.part_type == "SECONDARY")
    new = [c for c in out.instance.carriers if c.key not in {c.key for c in problem.instance.carriers}]
    assert len(new) == len(loose)  # one plate per order
    by_due = sorted(loose, key=lambda o: next(x.due_date for x in problem.instance.orders if x.id == o))
    job = assumed_print_id(by_due)  # two orders, up to four plates per print: one print
    assert len(loose) <= PLATES_PER_PRINT and {c.am_job_id for c in new} == {job}
    assert [c.quadrant for c in sorted(new, key=lambda c: c.key)] == ["1", "2"]
    # the urgent order (due first) takes plate 1
    first = next(c for c in new if c.quadrant == "1")
    assert {p.order_id for p in out.instance.parts if p.id in first.part_ids} == {by_due[0]}
    # one print operation for both orders, published under both orders' own keys
    print_op = next(o for o in out.instance.operations if o.key == f"job:{job}:AM_PREP")
    assert print_op.order_ids == by_due and print_op.job_id == job
    assert aliases[f"job:{job}:AM_PREP"] == sorted(f"order:{o}:AM_PREP" for o in loose)


def test_no_key_points_to_a_renamed_operation(problem):
    out, aliases = assume_plates(problem)
    keys = {o.key for o in out.instance.operations}
    old = {k for ks in aliases.values() for k in ks}
    assert not keys & old
    for o in out.instance.operations:
        assert set(o.predecessors) <= keys, o.key
        assert not set(o.predecessors) & old


def test_a_problem_where_everything_is_nested_is_unchanged():
    raw = json.loads((DATA / "problem_printing.json").read_text(encoding="utf-8"))
    p = ProblemOut.model_validate(raw)
    out, aliases = assume_plates(p)
    assert out is p and aliases == {}


def test_the_plan_is_feasible_and_published_under_the_mes_keys(problem):
    epoch = epoch_of(problem.as_of, ZoneInfo("Europe/Berlin"))
    outcome = solve(problem, epoch=epoch, solved_at=problem.as_of + timedelta(seconds=1))
    assert outcome.violations == []
    published = {s.key: s for s in outcome.schedule.steps}
    open_keys = {o.key for o in problem.instance.operations if not o.done}
    assert set(published) <= {o.key for o in problem.instance.operations}  # no assumed key leaks to the MES
    loose = _loose_orders(problem)
    for o in loose:
        for tt in ("DATA_PREP_SECONDARY", "AM_PREP", "PART_CLEANING", "SAWING"):
            assert f"order:{o}:{tt}" in published, (o, tt)
        # the nesting comes before the order's print
        assert published[f"order:{o}:DATA_PREP_SECONDARY"].end <= published[f"order:{o}:AM_PREP"].start
    # the assumed print is one run: both orders' print steps carry the same times
    a, b = (published[f"order:{o}:AM_PREP"] for o in loose)
    assert (a.start, a.end) == (b.start, b.end)
    assert open_keys - set(published) <= {k for k in open_keys if k.endswith(":REWORK")}  # every open step planned


def test_the_same_grouping_gives_the_same_print_on_every_refresh(problem):
    first, _ = assume_plates(problem)
    again, _ = assume_plates(problem.model_copy(update={"as_of": problem.as_of + timedelta(minutes=5)}))
    assert [c.key for c in first.instance.carriers] == [c.key for c in again.instance.carriers]


def test_prints_hold_at_most_four_plates(problem):
    """Five more orders without plates: next fit by due date, a new print after four plates."""
    inst = problem.instance
    template = next(p for p in inst.parts if p.part_type == "SECONDARY" and p.carrier is None)
    order = next(o for o in inst.orders if o.id == template.order_id)
    extra_orders, extra_parts = [], []
    for i in range(5):
        oid = f"00000000-0000-0000-0000-00000000000{i}"
        due = order.due_date + timedelta(days=i) if order.due_date else None
        extra_orders.append(order.model_copy(update={"id": oid, "short_id": f"x{i}", "due_date": due}))
        extra_parts.append(
            template.model_copy(update={"id": f"10000000-0000-0000-0000-00000000000{i}", "order_id": oid})
        )
    p = problem.model_copy(
        update={
            "instance": inst.model_copy(
                update={"orders": [*inst.orders, *extra_orders], "parts": [*inst.parts, *extra_parts]}
            )
        }
    )
    out, _ = assume_plates(ProblemOut.model_validate(p.model_dump()))
    new = [c for c in out.instance.carriers if c.key not in {c.key for c in inst.carriers}]
    sizes = sorted(sum(1 for c in new if c.am_job_id == j) for j in {c.am_job_id for c in new})
    assert sizes == [3, 4]  # seven plates: 4 + 3
    assert all(int(c.quadrant) <= PLATES_PER_PRINT for c in new)


def test_two_started_tasks_on_one_assumed_print_are_refused(problem):
    from mes_bridge.api import ProblemTaskOut
    from mes_bridge.instance import MappingError

    loose = _loose_orders(problem)
    now = datetime.fromisoformat(str(problem.as_of))
    tasks = [
        ProblemTaskOut(
            key=f"order:{o}:AM_PREP",
            task_id=f"20000000-0000-0000-0000-00000000000{i}",
            worker_id=None,
            equipment_id=None,
            started_at=now,
            handoff_at=None,
            finished_at=None,
            expected_attended_end=None,
            expected_end=None,
        )  # fmt: skip
        for i, o in enumerate(loose)
    ]
    p = problem.model_copy(update={"snapshot": problem.snapshot.model_copy(update={"tasks": tasks})})
    with pytest.raises(MappingError, match="two started tasks"):
        assume_plates(p)
