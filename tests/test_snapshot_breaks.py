"""Breaks in the snapshot and the break checks of a revised plan (math/04_workers.md (C14), math/05 (C6, C7); plan
docs/superpowers/plans/2026-11-08-breaks-rescheduling.md, Task 1).

toy-workers with its calendar and the hand plan of tests/test_workers_checker.py: t = 0 is Monday 08:00, 12:00 is
t = 240, 13:00 is t = 300; breaks A and B at 12:00.
"""

from test_des_workers import scenario
from test_workers_checker import BREAKS, CI, plan

from simulation.check.feasibility import check_schedule
from simulation.model.schedule import Assignment, Break
from simulation.sim.des import Simulation


def snap_at(rows, t, **factors):
    sim = Simulation(CI, rows, scenario(CI, **factors), BREAKS)
    sim.run(until=t)
    return sim.snapshot()


def frozen_rows(snap):
    return [Assignment(order_id=f.order_id, op_id=f.op_id, machine=f.machine, start=f.start, end=f.end,
                       workers=tuple(w for w in f.workers if w is not None)) for f in snap.frozen]


def constraints(rows, snap, breaks):
    return sorted({v.constraint for v in check_schedule(CI, rows, snap, breaks)})


# --- A's break postponed to 12:20 by a slow Gegenbetten prefix (factor 20/3: A busy until 260) -----------------

SLOW = {"k1_gb": 20 / 3}


def test_snapshot_carries_the_realized_breaks():
    # at 12:30 (270): B broke at 12:00, A at 12:20 after its prefix; Gegenbetten runs, expected end 271
    snap = snap_at(plan(), 270, **SLOW)
    assert snap.breaks == (Break(worker="A", start=260), Break(worker="B", start=240))
    assert next(f for f in snap.frozen if f.op_id == "gb").end == 271


def test_no_break_in_the_snapshot_before_it_starts():
    assert snap_at(plan(), 230, **SLOW).breaks == ()


def revised_at_270():
    """The frozen part at 12:30 plus k1 packaging by B at [300, 320), after B's break [240, 300)."""
    snap = snap_at(plan(), 270, **SLOW)
    rows = [*frozen_rows(snap), Assignment(order_id="k1", op_id="pack", machine=None, start=300, end=320,
                                           workers=("B",))]
    return snap, rows


def test_revised_plan_with_the_realized_breaks_is_feasible():
    snap, rows = revised_at_270()
    assert check_schedule(CI, rows, snap, snap.breaks) == []


def test_started_break_moved_is_c7():
    snap, rows = revised_at_270()
    assert constraints(rows, snap, (Break(worker="A", start=275), Break(worker="B", start=240))) == ["C7"]


def test_new_break_before_t_is_c6():
    # at 12:10 (250): B broke at 12:00, A is still on its prefix; a plan with A's break at 12:05 lies in the past
    snap = snap_at(plan(), 250, **SLOW)
    assert snap.breaks == (Break(worker="B", start=240),)
    rows = [*frozen_rows(snap), Assignment(order_id="k1", op_id="pack", machine=None, start=300, end=320,
                                           workers=("B",))]
    assert constraints(rows, snap, (Break(worker="A", start=245), *snap.breaks)) == ["C6"]
    assert check_schedule(CI, rows, snap, (Break(worker="A", start=260), *snap.breaks)) == []


# --- forced postponement: A's packaging [220, 240) overruns past 13:00 (factor 6.25: until 13:45) ---------------

OVERRUN = {"k1_pack": 6.25}


def at_1310():
    """At 13:10 (310) A's break is still pending; the packaging runs, expected end 311; nothing is left to plan."""
    snap = snap_at(plan(k1_pack=(None, 220, 240, ("A",))), 310, **OVERRUN)
    assert snap.breaks == (Break(worker="B", start=240),)
    assert next(f for f in snap.frozen if f.order_id == "k1" and f.op_id == "pack").end == 311
    return snap, frozen_rows(snap)


def test_forced_postponement_at_the_end_of_the_frozen_share_is_allowed():
    snap, rows = at_1310()
    assert check_schedule(CI, rows, snap, (Break(worker="A", start=311), *snap.breaks)) == []


def test_forced_postponement_later_than_the_share_end_is_c14():
    snap, rows = at_1310()
    violations = check_schedule(CI, rows, snap, (Break(worker="A", start=330), *snap.breaks))
    assert [v.constraint for v in violations] == ["C14"] and "not forced" in violations[0].message


def test_postponement_without_a_frozen_share_covering_13_00_is_c14():
    # hand-built: the same snapshot, but the packaging started at 13:05, so nothing kept A from breaking by 13:00
    snap, _ = at_1310()
    frozen = tuple(f.model_copy(update={"start": 305}) if f.order_id == "k1" and f.op_id == "pack" else f
                   for f in snap.frozen)
    snap = snap.model_copy(update={"frozen": frozen})
    assert constraints(frozen_rows(snap), snap, (Break(worker="A", start=311), *snap.breaks)) == ["C14"]


def test_realized_break_outside_the_window_is_history():
    # the DES took A's break at 13:45 (345); a later snapshot carries it and it is not checked against the window
    sim = Simulation(CI, plan(k1_pack=(None, 220, 240, ("A",))), scenario(CI, **OVERRUN), BREAKS)
    sim.run(until=350)
    snap = sim.snapshot()
    assert Break(worker="A", start=345) in snap.breaks
    assert check_schedule(CI, frozen_rows(snap), snap, snap.breaks) == []


def test_without_a_snapshot_a_late_break_is_still_c14():
    _, rows = at_1310()
    assert "C14" in {v.constraint for v in check_schedule(CI, rows, None, (Break(worker="A", start=311),
                                                                             Break(worker="B", start=240)))}
