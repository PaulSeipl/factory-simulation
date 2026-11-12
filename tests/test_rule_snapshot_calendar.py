"""The dispatching rule from a snapshot with workers and a calendar (plan
docs/superpowers/plans/2026-11-08-breaks-rescheduling.md, Task 4; math/11_dispatching-rules.md, math/04_workers.md).

On the snapshot's day the rule plans around the worker's actual break: a break taken stays (C7^b), a break not
taken yet starts at the earliest break start, not before t and after the worker's frozen share (C14^f if that ends
after 13:00). A pending removal is booked like the checker's forced end (C7^o): with overtime, before any break.
t = 0 is Monday 08:00; 12:00 is t = 240, 13:00 t = 300, Tuesday 08:00 t = 1440.
"""

import json
from pathlib import Path

import pytest
from test_des_workers import scenario
from test_dispatching_workers import RULES, by_key, carriers

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan, spt
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario

DAY = 1440
TOY_DATA = json.loads((Path(__file__).parents[1] / "data" / "instances" / "toy-workers.json").read_text())


def run_to(ci, plan, breaks, t, sc=None):
    sim = Simulation(ci, plan, sc, breaks)
    sim.run(until=t)
    return sim


def replan(sim, ci):
    """Rule plan from the snapshot; checked against it and handed to the DES."""
    snap = sim.snapshot()
    new = dispatch_plan(ci, spt, snapshot=snap)
    assert check_schedule(ci, new.assignments, snap, new.breaks) == []
    sim.update_plan(new.assignments, new.breaks)
    return new


# --- one worker A: toy-workers without B -------------------------------------------------------------------------

def one_worker_toy():
    data = json.loads(json.dumps(TOY_DATA)) | {"workers": ["A"]}
    return compile_instance(Instance.model_validate(data))


def test_next_share_after_the_break_taken_at_12_20():
    # start plan: k2 packaging [0, 20), print [20, 80) prefix [20, 35), Gegenbetten [80, 170) prefix [80, 110),
    # k1 packaging [170, 190); A's break 12:00. Gegenbetten factor 6: prefix [80, 260), so A breaks at 12:20 (260).
    # At 12:30 the rule plans k1 packaging after A's break [260, 320): 13:20, not 13:00
    ci = one_worker_toy()
    start = dispatch_plan(ci, spt)
    assert start.breaks == (Break(worker="A", start=240),)
    sim = run_to(ci, start.assignments, start.breaks, 270, scenario(ci, k1_gb=6.0))
    assert sim.snapshot().breaks == (Break(worker="A", start=260),)
    new = replan(sim, ci)
    assert by_key(new.assignments)["k1", "pack"] == (None, 320, 340, ("A",))
    assert new.breaks == (Break(worker="A", start=260),)


def test_forced_postponement_after_an_overrunning_prefix():
    # one worker; Gegenbetten factor 8: prefix [80, 320) instead of [80, 110). At 13:10 the prefix still runs; the
    # snapshot shows it until at least t + 1 = 311 (share_lengths), so the break is forced to 311 (C14^f) and the
    # packaging follows the break at 371 (Gegenbetten expected to end at 311)
    ci = one_worker_toy()
    start = dispatch_plan(ci, spt)
    sim = run_to(ci, start.assignments, start.breaks, 310, scenario(ci, k1_gb=8.0))
    gb = next(f for f in sim.snapshot().frozen if f.op_id == "gb")
    assert (gb.end, gb.share_lengths) == (311, (231,))
    new = replan(sim, ci)
    assert new.breaks == (Break(worker="A", start=311),)
    assert by_key(new.assignments)["k1", "pack"] == (None, 371, 391, ("A",))


def two_steps(x_len=100):
    """A alone; X (machine-less, whole, released 11:00) then Y (whole, 20)."""
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "xy", "machines": ["M"], "workers": ["A"], "calendar": {},
        "orders": [{"id": "k", "release": 180, "operations": [
            {"id": "x", "step": "x", "duration": x_len, "worker": {"whole": True}},
            {"id": "y", "step": "y", "duration": 20, "worker": {"whole": True}, "predecessors": ["x"]},
        ]}]}))


# hand start plan: X 11:00-12:40, A's break 12:40 (in the window), Y 13:40-14:00
XY_PLAN = [Assignment(order_id="k", op_id="x", machine=None, start=180, end=280, workers=("A",)),
           Assignment(order_id="k", op_id="y", machine=None, start=340, end=360, workers=("A",))]
XY_BREAKS = (Break(worker="A", start=280),)


def test_break_after_the_frozen_share_and_next_share_after_it():
    # at 11:10 X runs (expected end 12:40), no break yet: the rule puts A's break at 12:40, Y at 13:40
    ci = two_steps()
    assert check_schedule(ci, XY_PLAN, breaks=XY_BREAKS) == []
    new = replan(run_to(ci, XY_PLAN, XY_BREAKS, 190), ci)
    assert new.breaks == (Break(worker="A", start=280),)
    assert by_key(new.assignments)["k", "y"] == (None, 340, 360, ("A",))


def test_forced_postponement_when_the_frozen_share_runs_past_13_00():
    # X takes 1.65 times as long (until 13:45); at 13:10 it runs, expected end 311: the break is postponed to 311
    # (C14^f), Y follows the break at 371
    ci = two_steps()
    sim = run_to(ci, XY_PLAN, XY_BREAKS, 310, scenario(ci, k_x=1.65))
    assert next(f for f in sim.snapshot().frozen if f.op_id == "x").end == 311
    new = replan(sim, ci)
    assert new.breaks == (Break(worker="A", start=311),)
    assert by_key(new.assignments)["k", "y"] == (None, 371, 391, ("A",))


# --- a worker who only starts after the break window owes no break (user 2026-11-09) ------------------------------

def morning_and_afternoon(release=480):
    """A does X (08:00-10:00, only A); B does Y (30 minutes, only B, released 16:00 = t 480 by default)."""
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "late", "machines": ["M"], "workers": ["A", "B"], "calendar": {},
        "orders": [
            {"id": "k", "operations": [{"id": "x", "step": "x", "duration": 120,
                                        "worker": {"whole": True, "qualified": ["A"]}}]},
            {"id": "l", "release": release, "operations": [{"id": "y", "step": "y", "duration": 30,
                                                            "worker": {"whole": True, "qualified": ["B"]}}]},
        ]}))


LATE_PLAN = [Assignment(order_id="k", op_id="x", machine=None, start=0, end=120, workers=("A",)),
             Assignment(order_id="l", op_id="y", machine=None, start=480, end=510, workers=("B",))]


def test_no_break_owed_for_a_share_after_the_window():
    # A worked in the morning: its break is owed; B starts at 16:00 only: none owed
    ci = morning_and_afternoon()
    assert check_schedule(ci, LATE_PLAN, breaks=(Break(worker="A", start=240),)) == []


def test_break_owed_for_a_share_before_the_window():
    ci = morning_and_afternoon(release=0)
    rows = [LATE_PLAN[0], LATE_PLAN[1].model_copy(update={"start": 180, "end": 210})]  # B at 11:00
    violations = check_schedule(ci, rows, breaks=(Break(worker="A", start=240),))
    assert [v.constraint for v in violations] == ["C14"] and "B: no break on day 0" in violations[0].message


def test_a_worker_idle_until_the_afternoon_takes_a_share_without_a_break():
    # snapshot at 15:00: A's break taken at 12:00, B has none (and owes none); the rule plans Y for B at 16:00
    ci = morning_and_afternoon()
    sim = run_to(ci, LATE_PLAN, (Break(worker="A", start=240),), 420)
    assert sim.snapshot().breaks == (Break(worker="A", start=240),)
    new = replan(sim, ci)
    assert by_key(new.assignments)["l", "y"] == (None, 480, 510, ("B",))
    assert new.breaks == (Break(worker="A", start=240),)


# --- pending oven removals with the calendar -----------------------------------------------------------------------

def one_plate(oven):
    """One plate L1: print P 2, oven O `oven` minutes (prefix 1, suffix 1, W1 or W2), mill M 4 (unattended)."""
    data = carriers()
    data["orders"], data["carriers"] = data["orders"][:1], data["carriers"][:1]
    data["carrier_steps"]["oven"]["options"]["O"] = oven
    data["carrier_steps"]["mill"] = {"options": {"M": 4}}
    return compile_instance(Instance.model_validate(data | {"calendar": {}}))


def plate_plan(oven_start, oven_end, mill_start):
    rows = [("print", "P", 0, 2, ()), ("oven", "O", oven_start, oven_end, ("W1", "W1")),
            ("mill", "M", mill_start, mill_start + 4, ())]
    return [Assignment(order_id="L1", op_id=j, machine=m, start=s, end=e, workers=w) for j, m, s, e, w in rows]


def test_removal_after_the_shift_end_keeps_its_end_with_overtime():
    # oven 545: planned [2, 547), removal [546, 547) at 17:06; the loading starts 30 minutes late: oven [32, 577),
    # removal expected 17:36-17:37, after 17:30 but within overtime: the rule keeps the end 577, as the checker does
    ci = one_plate(545)
    plan, breaks = plate_plan(2, 547, 547), (Break(worker="W1", start=240),)
    assert check_schedule(ci, plan, breaks=breaks) == []
    sim = run_to(ci, plan, breaks, 40, scenario(ci, L1_oven=(1.0, 30)))
    assert next(f for f in sim.snapshot().frozen if f.op_id == "oven").end == 577
    new = replan(sim, ci)
    assert by_key(new.assignments)["L1", "oven"][1:3] == (32, 577)


def test_removal_at_12_00_tomorrow_keeps_its_end_and_moves_that_break():
    # oven 1679: [2, 1681), removal Tuesday [12:00, 12:01) by W1, whose Tuesday break is 12:01. At 10 the rule
    # keeps the removal (a qualified worker is free then) and W1's Tuesday break gives way: 12:01
    ci = one_plate(1679)
    plan, breaks = plate_plan(2, 1681, 1681), (Break(worker="W1", start=240), Break(worker="W1", start=DAY + 241))
    assert check_schedule(ci, plan, breaks=breaks) == []
    new = replan(run_to(ci, plan, breaks, 10), ci)
    oven = by_key(new.assignments)["L1", "oven"]
    assert oven[1:3] == (2, 1681)
    remover = oven[3][1]
    assert Break(worker=remover, start=DAY + 241) in new.breaks


# --- sweep ---------------------------------------------------------------------------------------------------------

def noon(data, release=150):
    """The instance with every order released at `release` (10:30): the work lies around the break."""
    data = json.loads(json.dumps(data))
    for order in data["orders"]:
        order["release"] = release
        order.pop("due_date", None)
    return data


def ovens_at(minutes, mill=4, release=0):
    """The carrier instance with the calendar, an oven program of `minutes` and attended mill runs."""
    data = carriers() | {"calendar": {}}
    data["carrier_steps"]["oven"]["options"]["O"] = minutes
    data["carrier_steps"]["mill"]["options"]["M"] = mill
    for order in data["orders"]:
        order["release"] = release
    return data


SWEEP = {
    "toy-noon": noon(TOY_DATA),
    "toy-noon-one-worker": noon(TOY_DATA) | {"workers": ["A"]},
    "ovens-to-noon": ovens_at(230),  # removals around 11:50-12:00
    "ovens-to-shift-end": ovens_at(160, release=380),  # loading 14:20, removals around 17:00-17:30
    "night-mill": ovens_at(5, mill=600),
}


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("name", SWEEP)
def test_every_rule_plan_from_a_disturbed_calendar_snapshot_is_accepted(name, seed):
    model = Instance.model_validate(SWEEP[name])
    ci = compile_instance(model)
    sc = sample_scenario(model, sigma=0.6, seed=seed, q=0.4, max_late=30)
    start = dispatch_plan(ci, spt)
    horizon = max(a.end for a in run_to(ci, start.assignments, start.breaks, 10**6, sc).realized())
    for t in range(1, horizon, max(1, horizon // 12)):
        sim = run_to(ci, start.assignments, start.breaks, t, sc)
        snap = sim.snapshot()
        for seq, asg in RULES:
            new = dispatch_plan(ci, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[asg] if asg else None, snap)
            assert check_schedule(ci, new.assignments, snap, new.breaks) == [], (t, seq, asg)
        sim.update_plan(*dispatch_plan(ci, spt, snapshot=snap))  # the DES accepts it
