"""MES problem -> thesis Instance (task 1.5b), on the recorded responses of `tests/data/`."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mes_bridge.api import ProblemOut
from mes_bridge.instance import MILL, PRINT, MappingError, at, build_instance, epoch_of, span
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.planners.dispatching import dispatch_plan, spt

DATA = Path(__file__).parent / "data"
BERLIN = ZoneInfo("Europe/Berlin")
RECORDINGS = ["problem_mill_prep.json", "problem_printing.json"]


def _raw(name: str = "problem_mill_prep.json") -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _build(raw: dict):
    p = ProblemOut.model_validate(raw)
    return build_instance(p, epoch=epoch_of(p.as_of, BERLIN))


@pytest.mark.parametrize("name", RECORDINGS)
def test_a_recorded_problem_is_a_valid_instance_the_rule_plans_feasibly(name):
    inst = _build(_raw(name))
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, spt)
    assert plan.assignments
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []


def test_plates_are_carriers_the_print_one_run_each_plate_one_mill_run():
    raw = _raw()
    inst = _build(raw)
    (am,) = [j for j in raw["instance"]["jobs"] if j["kind"] == "AM"]
    assert [c.id for c in inst.carriers] == [f"C:{am['id']}:1", f"C:{am['id']}:2"]
    prints = [r for r in inst.runs if r.step == PRINT]
    mills = [r for r in inst.runs if r.step == MILL]
    assert [r.carriers for r in prints] == [(f"C:{am['id']}:1", f"C:{am['id']}:2")]
    assert sorted(r.carriers for r in mills) == [(f"C:{am['id']}:1",), (f"C:{am['id']}:2",)]
    # no job estimate entered: the run takes the MES estimate (AM_PREP's unattended minutes, the mill prep's)
    assert prints[0].duration == 195 and {r.duration for r in mills} == {120}


def test_step_shape_comes_from_the_params():
    steps = _build(_raw()).carrier_steps
    p = steps[PRINT]
    assert (p.runs, p.setup, p.setup_per_carrier, p.removal, p.removal_per_carrier) == ("given", 90, 5, 15, 5)
    assert p.setup_attended and p.removal_attended
    m = steps[MILL]
    assert (m.runs, m.setup, m.setup_per_carrier, m.removal, m.removal_per_carrier) == ("given", 15, 0, 5, 0)
    assert steps["PART_CLEANING"].duration == 25 and steps["PART_CLEANING"].worker.whole
    assert steps["SAND_BLASTING"].duration == 10
    oven = steps["HEAT_TREATMENT"]  # 35 attended, then the 180-minute program without a worker
    assert (oven.duration, oven.worker.rest, oven.batch_capacity) == (215, 180, None)


def test_cleaning_and_blasting_are_s_batches_of_the_mes_linear_form():
    sb = _build(_raw()).s_batch_steps
    assert (sb["PART_CLEANING"].setup, sb["PART_CLEANING"].capacity) == (15, 4)  # 15 + 10 per plate, at most 4
    assert (sb["SAND_BLASTING"].setup, sb["SAND_BLASTING"].capacity) == (5, 4)
    assert "HEAT_TREATMENT" not in sb


def test_order_route_is_one_chain_from_print_to_mill():
    order = _build(_raw()).orders[0]
    ops = {o.id: o for o in order.operations}
    assert [o.id for o in order.operations] == [
        "DATA_PREP_SEC_MILL",
        PRINT,
        "PART_CLEANING",
        "HEAT_TREATMENT",
        "SAND_BLASTING",
        MILL,
    ]
    assert ops[PRINT].predecessors == ("DATA_PREP_SEC_MILL",) and ops[PRINT].role == "form"
    assert ops[MILL].predecessors == ("SAND_BLASTING",) and ops[MILL].role == "separate"
    assert ops["DATA_PREP_SEC_MILL"].duration == 20 and ops["DATA_PREP_SEC_MILL"].worker.whole


def test_arrival_and_calendar():
    inst = _build(_raw())
    # DATA_PREP_SECONDARY finished 07:00 UTC on Monday 2026-11-23 = 08:00 in Berlin
    assert {o.arrival for o in inst.orders} == {480}
    assert all(o.release == o.arrival == o.accepted for o in inst.orders)
    cal = inst.calendar
    assert (cal.origin, cal.shift_start, cal.shift_end, cal.max_overtime) == (0, 420, 960, 0)
    assert (cal.break_earliest, cal.break_latest, cal.break_length) == (720, 720, 60)
    assert cal.working_days == (0, 1, 2, 3, 4)


def test_an_entered_job_estimate_is_the_run_time():
    raw = _raw()
    for j in raw["instance"]["jobs"]:
        if j["kind"] == "AM":
            j["estimated_duration_minutes"] = 330
    assert [r.duration for r in _build(raw).runs if r.step == PRINT] == [330]


def test_rework_is_left_out_until_slice_3():
    raw = _raw()
    clean = next(o for o in raw["instance"]["operations"] if o["task_type"] == "PART_CLEANING")
    rework = dict(clean, key=clean["key"].replace("PART_CLEANING", "REWORK"), task_type="REWORK")
    raw["instance"]["operations"].append(rework)
    assert all(op.id != "REWORK" for o in _build(raw).orders for op in o.operations)


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (date(2026, 11, 25), 2 * 1440 + 720),  # Wednesday: its 12:00 cutoff
        (date(2026, 11, 28), 7 * 1440 + 720),  # Saturday: the next working day's cutoff
        (date(2026, 11, 20), 720),  # overdue: the first cutoff at or after the release (understated, logged)
    ],
)
def test_due_date_is_a_shipping_cutoff(due, expected):
    raw = _raw()
    raw["instance"]["orders"][0]["due_date"] = due.isoformat()
    assert _build(raw).orders[0].due_date == expected


def test_epoch_is_monday_midnight_local_and_instants_round_up_and_clamp():
    sunday_night = datetime(2026, 11, 29, 22, 30, tzinfo=UTC)  # 23:30 Sunday in Berlin
    assert epoch_of(sunday_night, BERLIN) == datetime(2026, 11, 23, tzinfo=BERLIN)
    summer = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    e = epoch_of(summer, BERLIN)
    assert e == datetime(2026, 7, 6, tzinfo=BERLIN) and e.utcoffset() == timedelta(hours=2)
    assert at(e + timedelta(seconds=30), e) == 1
    assert at(e + timedelta(minutes=3), e) == 3
    assert at(e - timedelta(days=2), e) == 0  # a fact from last week starts at the epoch


def test_durations_round_up_and_never_reach_zero():
    assert (span(24.2), span(25.0), span(0.0)) == (25, 25, 1)


def test_a_plate_step_on_a_job_key_is_rejected():
    raw = _raw()
    op = next(o for o in raw["instance"]["operations"] if o["task_type"] == "PART_CLEANING")
    op["key"] = f"job:{raw['instance']['carriers'][0]['am_job_id']}:PART_CLEANING"
    with pytest.raises(MappingError, match="plates are unknown"):
        _build(raw)


def test_carrier_minutes_that_differ_are_rejected():
    raw = _raw()
    next(o for o in raw["instance"]["operations"] if o["task_type"] == "SAND_BLASTING")["attended_minutes"] = 20.0
    with pytest.raises(MappingError, match="minutes differ between carriers"):
        _build(raw)


def test_a_setup_per_part_is_rejected():
    raw = _raw()
    row = next(r for r in raw["instance"]["params"] if r["task_type"] == "AM_PREP")
    row["unit_kind"] = "PART"
    with pytest.raises(MappingError, match="vary per run"):
        _build(raw)


def test_no_workers_is_rejected():
    raw = _raw()
    raw["instance"]["workers"] = []
    with pytest.raises(MappingError, match="no workers"):
        _build(raw)


def test_an_inconsistency_the_mapping_lets_through_fails_the_instance_validation():
    """One plate loses its cleaning: its route breaks, and the Instance (V14) says so."""
    raw = _raw()
    ops = raw["instance"]["operations"]
    drop = next(o for o in ops if o["task_type"] == "PART_CLEANING")
    raw["instance"]["operations"] = [o for o in ops if o is not drop]
    with pytest.raises(ValueError, match="V14"):
        _build(raw)
