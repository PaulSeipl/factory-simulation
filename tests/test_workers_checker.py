"""Checker for workers, shifts and breaks: C11-C14 (math/04_workers.md, section 3).

Mini instance data/instances/toy-workers.json: printer P, workers A and B, default calendar (t = 0 is Monday 08:00,
break window 12:00-13:00 = t 240-300, shift end with overtime 19:30 = t 690). Hand plan:
  k2 pack [0, 20) by A
  k1 print [0, 60) on P, prefix [0, 15) by B; gegenbetten [60, 150), prefix [60, 90) by A (only A qualified);
  k1 pack [150, 170) by A
  breaks of A and B at 240 (12:00). All due 240 (Monday 12:00): on time.
"""

from pathlib import Path

import pytest
from test_worker_compile import CARRIERS

from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break
from simulation.objectives import TOTAL_TARDINESS

CI = compile_instance(read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-workers.json", Instance))
PLAN = {
    ("k2", "pack"): (None, 0, 20, ("A",)),
    ("k1", "print"): ("P", 0, 60, ("B",)),
    ("k1", "gb"): (None, 60, 150, ("A",)),
    ("k1", "pack"): (None, 150, 170, ("A",)),
}
BREAKS = (Break(worker="A", start=240), Break(worker="B", start=240))


def plan(**changes):
    """The hand plan with entries replaced, e.g. plan(k1_pack=(None, 230, 250, ("A",)))."""
    entries = PLAN | {tuple(k.split("_", 1)): v for k, v in changes.items()}
    return [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e, workers=w)
            for (o, j), (m, s, e, w) in entries.items()]


def constraints(assignments, breaks=BREAKS):
    return sorted({v.constraint for v in check_schedule(CI, assignments, breaks=breaks)})


def test_hand_plan_is_feasible():
    assert check_schedule(CI, plan(), breaks=BREAKS) == []
    assert TOTAL_TARDINESS.evaluate(CI, plan()) == 0


@pytest.mark.parametrize(("changes", "expected"), [
    ({"k1_print": ("P", 0, 60, ())}, "C11"),  # no worker for the prefix
    ({"k1_gb": (None, 60, 150, ("B",))}, "C11"),  # B not qualified
    ({"k1_gb": (None, 60, 150, ("Z",))}, "C11"),  # unknown worker
    ({"k1_pack": ("P", 150, 170, ("A",))}, "C11"),  # machine for an operation without machine
    ({"k1_pack": (None, 150, 175, ("A",))}, "C2"),  # duration of a machine-less operation
    ({"k1_print": (None, 0, 60, ("B",))}, "C1"),  # machine missing
    ({"k2_pack": (None, 70, 90, ("A",))}, "C12"),  # A also on the Gegenbetten prefix [60, 90)
    ({"k1_pack": (None, 680, 700, ("A",))}, "C13"),  # ends 19:40, after shift end + overtime
    ({"k1_pack": (None, 230, 250, ("A",))}, "C14"),  # across A's break [240, 300)
], ids=["count", "qualified", "unknown", "machine", "duration", "no-machine", "overlap", "overtime", "break"])
def test_one_violation_per_change(changes, expected):
    assert constraints(plan(**changes)) == [expected]


def test_night_share():
    # 00:40 on Tuesday; A gets a Tuesday break so that only the shift window is violated
    assert constraints(plan(k1_pack=(None, 1000, 1020, ("A",))), (*BREAKS, Break(worker="A", start=1680))) == ["C13"]


@pytest.mark.parametrize(("breaks", "message"), [
    ((Break(worker="A", start=301), BREAKS[1]), "13:01"),  # after the latest break start
    ((BREAKS[0],), "no break"),  # B worked on Monday without a break
    ((*BREAKS, Break(worker="A", start=260)), "2 breaks"),
    ((*BREAKS, Break(worker="Z", start=240)), "unknown worker"),
], ids=["late", "missing", "twice", "unknown"])
def test_break_violations(breaks, message):
    violations = check_schedule(CI, plan(), breaks=breaks)
    assert [v.constraint for v in violations] == ["C14"] and message in violations[0].message


def test_wrong_number_of_share_lengths():
    rows = [a.model_copy(update={"share_lengths": (15, 1)}) if a.op_id == "print" else a for a in plan()]
    assert constraints(rows) == ["C11"]


def test_realized_share_lengths_replace_the_planned_ones():
    # k2 packaging by A at [80, 100) overlaps A's planned Gegenbetten prefix [60, 90), not a realized one of 15
    rows = plan(k2_pack=(None, 80, 100, ("A",)))
    assert constraints(rows) == ["C12"]
    shorter = [a.model_copy(update={"share_lengths": (15,)}) if a.op_id == "gb" else a for a in rows]
    assert constraints(shorter) == []


def test_share_touching_break_is_allowed():
    assert check_schedule(CI, plan(k1_pack=(None, 220, 240, ("A",))), breaks=BREAKS) == []


def test_worker_free_during_rest():
    # A's Gegenbetten prefix ends at 90; the rest [90, 150) needs nobody, so A can pack k2 then
    assert check_schedule(CI, plan(k2_pack=(None, 90, 110, ("A",))), breaks=BREAKS) == []


# --- oven batch and runs without calendar (tests/test_worker_compile.py, CARRIERS) ------------------------------


def carrier_plan(oven_workers=(("W1", "W1"), ("W1", "W1"))):
    rows = [
        ("L1", "print", "P", 0, 2, ()), ("L2", "print", "P", 2, 4, ()),
        ("L1", "oven", "O", 4, 9, oven_workers[0]), ("L2", "oven", "O", 4, 9, oven_workers[1]),
        ("L1", "mill/setup", "M", 9, 10, ("W1",)), ("L1", "mill", "M", 10, 14, ()),
        ("L1", "mill/removal", "M", 14, 15, ("W1",)),
        ("L2", "mill/setup", "M", 15, 16, ("W2",)), ("L2", "mill", "M", 16, 20, ()),
        ("L2", "mill/removal", "M", 20, 21, ("W2",)),
    ]
    return [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e, workers=w) for o, j, m, s, e, w in rows]


def test_batch_shares_count_once():
    # one oven run with two plates: W1 loads [4, 5) and unloads [8, 9) once, not twice
    assert check_schedule(CARRIERS, carrier_plan()) == []


def test_batch_members_need_the_same_workers():
    assert [v.constraint for v in check_schedule(CARRIERS, carrier_plan((("W1", "W1"), ("W2", "W1"))))] == ["C11"]


def test_without_calendar_shifts_and_breaks_are_not_checked():
    late = [a.model_copy(update={"start": a.start + 2000, "end": a.end + 2000}) for a in carrier_plan()]
    assert check_schedule(CARRIERS, late) == []
