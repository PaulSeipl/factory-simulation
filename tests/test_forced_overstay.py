"""Forced overstay (math/04_workers.md (C7^o); plan docs/superpowers/plans/2026-11-08-breaks-rescheduling.md, Task 2).

A running operation whose removal (suffix) has not started may end later than the snapshot expects only if no
qualified worker is free of the frozen part then (a disturbance), and then exactly at the earliest such time.
"""

from test_des_workers import polish_instance
from test_des_workers import scenario as factor_scenario
from test_dispatching_workers import by_key, snap_at
from test_worker_compile import CARRIERS

from simulation.check.feasibility import check_schedule
from simulation.model.schedule import Assignment
from simulation.planners.dispatching import dispatch, spt
from simulation.sim.des import Simulation

ONE_WORKER = polish_instance(("W1",), polish=3)
ROWS = [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e, workers=w) for o, j, m, s, e, w in [
    ("L1", "print", "P", 0, 2, ()), ("L2", "print", "P", 2, 4, ()),
    ("L1", "oven", "O", 4, 9, ("W1", "W1")), ("L2", "oven", "O", 4, 9, ("W1", "W1")),
    ("A", "polish", None, 5, 8, ("W1",)),
    ("L1", "mill/setup", "M", 9, 10, ("W1",)), ("L1", "mill", "M", 10, 14, ()),
    ("L1", "mill/removal", "M", 14, 15, ("W1",)),
    ("L2", "mill/setup", "M", 15, 16, ("W1",)), ("L2", "mill", "M", 16, 20, ()),
    ("L2", "mill/removal", "M", 20, 21, ("W1",)),
]]
SLOW_POLISH = factor_scenario(ONE_WORKER, A_polish=2.0)


def at_8():
    """One worker, polishing [5, 8) takes twice as long. At 8 the polishing runs (expected end max(8, 9) = 9), the
    oven batch [4, 9) runs with its removal [8, 9) pending, and W1 is the only worker."""
    return snap_at(ONE_WORKER, ROWS, 8, SLOW_POLISH)


def with_changes(rows, **ends):
    """rows with the end of (owner, op) changed, e.g. L1_oven=11."""
    return [a.model_copy(update={"end": ends[f"{a.order_id}_{a.op_id}"]}) if f"{a.order_id}_{a.op_id}" in ends
            else a for a in rows]


def c7_messages(ci, rows, snap):
    return [v.message for v in check_schedule(ci, rows, snap) if v.constraint == "C7"]


def test_snapshot_expects_the_pending_removal_after_t():
    frozen = {(f.order_id, f.op_id): f for f in at_8().frozen}
    assert (frozen["A", "polish"].end, frozen["A", "polish"].workers) == (9, ("W1",))
    assert (frozen["L1", "oven"].end, frozen["L1", "oven"].workers) == (9, ("W1", None))


def test_rule_plans_the_forced_overstay_by_hand():
    # W1 is on the polishing until 9: removal [9, 10), the oven batch ends at 10 instead of 9; the mill runs follow
    # one minute later than planned: L1 [10, 16), L2 [16, 22)
    snap = at_8()
    new = dispatch(ONE_WORKER, spt, snapshot=snap)
    assert check_schedule(ONE_WORKER, new, snap) == []
    got = by_key(new)
    assert got["L1", "oven"] == got["L2", "oven"] == ("O", 4, 10, ("W1", "W1"))
    assert (got["L1", "mill/setup"][1:3], got["L1", "mill/removal"][1:3]) == ((10, 11), (15, 16))
    assert (got["L2", "mill/setup"][1:3], got["L2", "mill/removal"][1:3]) == ((16, 17), (21, 22))


def test_des_accepts_the_forced_overstay_and_finishes():
    # realized: the polishing really ends at 11, so the removal runs [11, 12) (OVERSTAY 3 from the due time 8)
    sim = Simulation(ONE_WORKER, ROWS, SLOW_POLISH)
    sim.run(until=8)
    sim.update_plan(dispatch(ONE_WORKER, spt, snapshot=sim.snapshot()))
    sim.run()
    got = by_key(sim.realized())
    assert got["L1", "oven"][1:3] == got["L2", "oven"][1:3] == (4, 12)
    assert [r["minutes"] for r in sim.log if r["type"] == "OVERSTAY"] == [3]


def test_end_kept_although_forced_is_c7():
    snap = at_8()
    rows = with_changes(dispatch(ONE_WORKER, spt, snapshot=snap), L1_oven=9, L2_oven=9)
    assert any("forced end 10" in m for m in c7_messages(ONE_WORKER, rows, snap))


def test_overstay_longer_than_forced_is_c7():
    snap = at_8()
    rows = with_changes(dispatch(ONE_WORKER, spt, snapshot=snap), L1_oven=11, L2_oven=11)
    assert any("forced end 10" in m for m in c7_messages(ONE_WORKER, rows, snap))


def test_end_moved_earlier_is_c7():
    snap = at_8()
    rows = with_changes(dispatch(ONE_WORKER, spt, snapshot=snap), L1_oven=8, L2_oven=8)
    assert c7_messages(ONE_WORKER, rows, snap)


def test_overstay_not_forced_is_c7():
    # carrier rule plan at 3: L1 oven [2, 7) runs, removal [6, 7) pending, W2 is free then: the end stays 7
    plan = dispatch(CARRIERS, spt)
    snap = snap_at(CARRIERS, plan, 3)
    assert next(f for f in snap.frozen if f.order_id == "L1" and f.op_id == "oven").workers == ("W1", None)
    new = dispatch(CARRIERS, spt, snapshot=snap)
    assert by_key(new)["L1", "oven"][2] == 7 and check_schedule(CARRIERS, new, snap) == []
    rows = with_changes(new, L1_oven=8)
    assert c7_messages(CARRIERS, rows, snap)
    assert not any("forced end" in m for m in c7_messages(CARRIERS, rows, snap))


def test_end_moved_after_the_removal_started_is_c7():
    # at 6 the L1 removal [6, 7) has started (W2): the operation is fully frozen
    plan = dispatch(CARRIERS, spt)
    snap = snap_at(CARRIERS, plan, 6)
    assert next(f for f in snap.frozen if f.order_id == "L1" and f.op_id == "oven").workers == ("W1", "W2")
    rows = with_changes(dispatch(CARRIERS, spt, snapshot=snap), L1_oven=8)
    assert c7_messages(CARRIERS, rows, snap)
