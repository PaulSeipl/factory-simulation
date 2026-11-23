"""MES problem -> thesis Instance (task 1.5b), on the recorded responses of `tests/data/`."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mes_bridge.api import ProblemOut
from mes_bridge.instance import MILL, MILL_BLANK, MILL_FLIPPED, PRINT, MappingError, at, build_instance, epoch_of, span
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.planners.dispatching import dispatch_plan, spt

DATA = Path(__file__).parent / "data"
BERLIN = ZoneInfo("Europe/Berlin")
RECORDINGS = ["problem_mill_prep.json", "problem_printing.json", "problem_blank.json"]


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
    assert [c.id for c in inst.carriers if c.id.startswith("C:")] == [f"C:{am['id']}:1", f"C:{am['id']}:2"]
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


def test_order_route_covers_both_lanes_from_the_arrival_to_the_packaging():
    order = _build(_raw()).orders[0]
    ops = {o.id: o for o in order.operations}
    assert set(ops) == {
        "DATA_PREP_SEC_MILL",
        PRINT,
        "PART_CLEANING",
        "HEAT_TREATMENT",
        "SAND_BLASTING",
        MILL,
        "REWORK_CHECKOUT",
        "SAWING",
        "SUPPORT_REMOVAL",
        "GRIND_CLEAN",
        "STEAM_CLEAN",
        "POLISH",
        "INSPECTION",
        "DOCUMENTATION",
        "PACKAGING_SHIPPING",
        "DATA_PREP_PRIMARY",
        MILL_BLANK,
        "GEGENBETTEN",
        MILL_FLIPPED,
        "PART_REMOVAL_FROM_BLANK",
        "PRIMARY_POLISHING",
        "FINISHING_PRIMARY",
    }
    assert ops[PRINT].predecessors == ("DATA_PREP_SEC_MILL",) and ops[PRINT].role == "form"
    assert ops[MILL].predecessors == ("SAND_BLASTING",) and ops[MILL].role is None
    assert ops["SAWING"].predecessors == ("REWORK_CHECKOUT",) and ops["SAWING"].role == "separate"
    assert ops["SUPPORT_REMOVAL"].predecessors == ("SAWING",) and ops["SUPPORT_REMOVAL"].scope == "order"
    # the primary lane on its blank, and the cross-lane joins
    assert ops[MILL_BLANK].role == "form" and ops[MILL_BLANK].carries == "primary"
    assert ops["PART_REMOVAL_FROM_BLANK"].role == "separate"
    assert set(ops["REWORK_CHECKOUT"].predecessors) == {MILL, "PRIMARY_POLISHING"}
    assert set(ops["INSPECTION"].predecessors) == {"FINISHING_PRIMARY", "POLISH"}
    assert ops["DATA_PREP_SEC_MILL"].duration == 20 and ops["DATA_PREP_SEC_MILL"].worker.whole


def test_a_recorded_formed_blank_holds_both_orders_primary_parts():
    raw = _raw("problem_blank.json")
    inst = _build(raw)
    (blank,) = [c for c in inst.carriers if c.id.startswith("B:")]
    jobs = {p["mill_job_id"] for p in raw["instance"]["parts"] if p["part_type"] == "PRIMARY"}
    assert blank.id == f"B:{jobs.pop()}" and {o for o, _ in blank.parts} == {o["id"] for o in raw["instance"]["orders"]}
    assert [r.carriers for r in inst.runs if r.step == MILL_BLANK] == [(blank.id,)]


def test_before_data_prep_each_order_has_one_assumed_blank_milled_in_its_own_run():
    raw = _raw()
    inst = _build(raw)
    blanks = [c for c in inst.carriers if c.id.startswith("B:")]
    assert sorted(c.id for c in blanks) == sorted(f"B:{o['id']}" for o in raw["instance"]["orders"])
    for c in blanks:
        assert {o for o, _ in c.parts} == {c.id.removeprefix("B:")}
    mill = inst.carrier_steps[MILL_BLANK]
    assert (mill.runs, mill.setup, mill.removal, mill.setup_attended, mill.removal_attended) == (
        "given",
        15,
        10,
        True,
        True,
    )
    flip = inst.carrier_steps[MILL_FLIPPED]
    assert (flip.runs, flip.setup, flip.removal) == ("given", 15, 0)
    runs = {r.id: r for r in inst.runs}
    for c in blanks:
        # mill job 120 per part + the removal's per-part 2 min folded into the run (shortcut, logged)
        assert runs[f"MB:{c.id}"].duration == 120 * len(c.parts) + 2 * len(c.parts)
        assert runs[f"MF:{c.id}"].duration == 120 * len(c.parts)


def test_gegenbetten_cures_unattended_after_its_work():
    inst = _build(_raw())
    g = inst.carrier_steps["GEGENBETTEN"]
    assert g.runs == "per_carrier" and g.worker.rest == 15 and g.estimator.base == 5 + 15 and not g.options


def test_after_data_prep_the_mill_jobs_blank_replaces_the_assumed_one():
    raw = _raw()
    job = "11111111-1111-1111-1111-111111111111"
    for p in raw["instance"]["parts"]:
        if p["part_type"] == "PRIMARY":
            p["mill_job_id"] = job  # both orders' primary parts on one blank
    for o in raw["instance"]["operations"]:
        if o["task_type"] in (
            "MILL_PREP_PRIMARY",
            "REMOVE_MOUNT",
            "GEGENBETTEN",
            "PREP_MILL_FLIPPED",
            "PART_REMOVAL_FROM_BLANK",
        ):
            o["key"] = f"job:{job}:{o['task_type']}"
    ops = raw["instance"]["operations"]
    seen, kept = set(), []
    for o in ops:  # the job node is shared: one per task type
        if o["key"] in seen:
            continue
        seen.add(o["key"])
        kept.append(o)
    for o in kept:
        o["predecessors"] = sorted(
            {
                d
                if not d.startswith("order:")
                or d.rsplit(":", 1)[1]
                not in (
                    "MILL_PREP_PRIMARY",
                    "REMOVE_MOUNT",
                    "GEGENBETTEN",
                    "PREP_MILL_FLIPPED",
                    "PART_REMOVAL_FROM_BLANK",
                )
                else f"job:{job}:{d.rsplit(':', 1)[1]}"
                for d in o["predecessors"]
            }
        )
        if o["key"].startswith(f"job:{job}"):
            o["order_ids"] = sorted(x["id"] for x in raw["instance"]["orders"])
    raw["instance"]["operations"] = kept
    inst = _build(raw)
    (blank,) = [c for c in inst.carriers if c.id.startswith("B:")]
    assert blank.id == f"B:{job}" and len(blank.parts) == 2
    assert [r.carriers for r in inst.runs if r.step == MILL_BLANK] == [(blank.id,)]
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, spt)
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []


def test_qm_and_sawing_are_runs_per_plate_whose_part_times_add_up_to_the_mes_minutes():
    raw = _raw()
    inst = _build(raw)
    qm, saw = inst.carrier_steps["REWORK_CHECKOUT"], inst.carrier_steps["SAWING"]
    assert (qm.runs, saw.runs) == ("per_carrier", "per_carrier")
    assert set(qm.options) == {m["id"] for m in raw["instance"]["machines"] if m["equipment_type"] == "MILL"}
    assert not saw.options and saw.worker.whole  # sawing needs no machine
    minutes = {o["key"]: o["attended_minutes"] for o in raw["instance"]["operations"]}
    times = {p.id: p.times for o in inst.orders for p in o.parts}
    for c in raw["instance"]["carriers"]:
        for tt in ("REWORK_CHECKOUT", "SAWING"):
            total = inst.carrier_steps[tt].estimator.base + sum(times[str(p)][tt] for p in c["part_ids"])
            assert total == minutes[f"carrier:{c['key']}:{tt}"], (c["key"], tt)
    ci = compile_instance(inst)
    assert {k[1] for k in ci.op_keys if k[0].startswith("C:")} >= {"REWORK_CHECKOUT", "SAWING"}


def test_a_per_carrier_step_below_one_minute_per_part_is_rejected():
    raw = _raw()
    qm = next(o for o in raw["instance"]["operations"] if o["task_type"] == "REWORK_CHECKOUT")
    qm["attended_minutes"] = 0.0
    c = next(c for c in raw["instance"]["carriers"] if qm["key"].startswith(f"carrier:{c['key']}:"))
    c["part_ids"] = c["part_ids"] * 2  # 1 minute for 2 parts
    with pytest.raises(MappingError, match="below one minute per part"):
        _build(raw)


def test_arrival_and_calendar():
    inst = _build(_raw())
    # DATA_PREP_SECONDARY finished 07:00 UTC on Monday 2026-11-23 = 08:00 in Berlin
    assert {o.arrival for o in inst.orders} == {480}
    assert all(o.release == o.arrival == o.accepted for o in inst.orders)
    cal = inst.calendar
    assert (cal.origin, cal.shift_start, cal.shift_end, cal.max_overtime) == (0, 420, 960, 0)
    assert (cal.break_earliest, cal.break_latest, cal.break_length) == (720, 720, 60)
    assert cal.working_days == (0, 1, 2, 3, 4)


def test_the_calendar_takes_the_mes_break_settings():
    raw = _raw()
    raw["instance"]["calendar"] |= {"break_earliest": "11:30:00", "break_latest": "12:30:00", "break_minutes": 45}
    cal = _build(raw).calendar
    assert (cal.break_earliest, cal.break_latest, cal.break_length) == (690, 750, 45)
    assert cal.shift_end == cal.shift_start + raw["instance"]["workers"][0]["daily_minutes"] + 45


def test_an_entered_job_estimate_is_the_run_time():
    raw = _raw()
    for j in raw["instance"]["jobs"]:
        if j["kind"] == "AM":
            j["estimated_duration_minutes"] = 330
    assert [r.duration for r in _build(raw).runs if r.step == PRINT] == [330]


def _with_rework(raw: dict) -> tuple[dict, str]:
    """Plate 1 in a rework round as the MES exports it: its QM done (suppressed), REWORK open on the mill."""
    ops = raw["instance"]["operations"]
    qm = next(o for o in ops if o["task_type"] == "REWORK_CHECKOUT")
    plate = qm["key"].removeprefix("carrier:").rsplit(":", 1)[0]
    qm["done"] = True
    mill = [m["id"] for m in raw["instance"]["machines"] if m["equipment_type"] == "MILL"]
    ops.append(
        dict(
            qm,
            key=f"carrier:{plate}:REWORK",
            task_type="REWORK",
            done=False,
            machine_options=mill,
            attended_minutes=30.0,
            unattended_minutes=60.0,
            predecessors=[],
        )
    )
    return raw, plate


def test_a_rework_round_plans_rework_then_a_recheck_before_sawing():
    raw, plate = _with_rework(_raw())
    inst = _build(raw)
    order = next(o for o in inst.orders if any(op.id == "REWORK" for op in o.operations))
    ops = {o.id: o for o in order.operations}
    assert ops["REWORK"].predecessors == ("REWORK_CHECKOUT",)
    assert ops["RECHECK"].predecessors == ("REWORK",)
    assert ops["SAWING"].predecessors == ("RECHECK",) and ops["SAWING"].role == "separate"
    assert "RECHECK" in ops["FINISHING_PRIMARY"].predecessors
    (run,) = [r for r in inst.runs if r.step == "REWORK"]
    rw = inst.carrier_steps["REWORK"]
    assert run.carriers == (f"C:{plate}",) and (rw.runs, rw.setup) == ("given", 20)
    assert run.duration == 30 + 60 - 20  # the per-telescope attended minutes folded into the run (shortcut)
    compile_instance(inst)


def test_the_recheck_has_no_mes_key_and_rework_maps_to_its_run():
    raw, plate = _with_rework(_raw())
    p = ProblemOut.model_validate(raw)
    ci = compile_instance(build_instance(p, epoch=epoch_of(p.as_of, BERLIN)))
    from mes_bridge.state import id_map

    ids = id_map(p, ci)
    assert ids.ops[f"carrier:{plate}:REWORK"] == ((f"RW:{plate}", "setup"), (f"RW:{plate}", "REWORK"))
    mapped = {k for ks in ids.ops.values() for k in ks}
    assert any(k[1] == "RECHECK" for k in ci.op_keys) and not any(k[1] == "RECHECK" for k in mapped)


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
