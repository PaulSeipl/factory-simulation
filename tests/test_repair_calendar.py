"""Shift repair with workers and the calendar (math/05_rescheduling-frozen-part.md, math/04_workers.md; plan
docs/superpowers/plans/2026-11-09-workers-phase4-repair-cpsat.md, Task 2).

t = 0 is Monday 08:00; 12:00 is t = 240, 13:00 t = 300, 17:30 t = 570, Tuesday 08:00 t = 1440, 12:00 t = 1680.
"""

import collections
import json
from pathlib import Path

import pytest
from test_dispatching_workers import RULES, by_key
from test_rule_snapshot_calendar import SWEEP, TOY_DATA, ovens_at

from simulation.calendar import day_index, day_start, minute_of_day
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan, dispatch_planner, spt
from simulation.planners.repair import repair_plan
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot

REPAIR = ReschedulingPolicy()
TOY = compile_instance(Instance.model_validate(json.loads(
    (Path(__file__).parents[1] / "data" / "instances" / "toy-workers.json").read_text())))
INSTANCES = {"toy-workers": TOY} | {name: compile_instance(Instance.model_validate(d)) for name, d in SWEEP.items()}


@pytest.mark.parametrize(("s", "a"), RULES)
@pytest.mark.parametrize("name", INSTANCES)
def test_zero_disturbance_repair_changes_nothing(name, s, a):
    ci = INSTANCES[name]
    start = dispatch_plan(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None)
    result = execute(ci, start.assignments, policy=REPAIR, breaks=start.breaks)
    assert result.decisions == []  # every repair returned the current plan and breaks
    assert by_key(result.schedule) == by_key(start.assignments)
    assert sorted(result.breaks, key=lambda b: (b.start, b.worker)) == sorted(start.breaks,
                                                                              key=lambda b: (b.start, b.worker))


# --- by hand on toy-workers: print [0, 60) prefix A [0, 15); Gegenbetten [60, 150) prefix A [60, 90); k2 packaging
# by A tight after it [90, 110); k1 packaging by B [150, 170); breaks of A and B at 12:00 -----------------------

PLAN = [
    Assignment(order_id="k1", op_id="print", machine="P", start=0, end=60, workers=("A",)),
    Assignment(order_id="k1", op_id="gb", machine=None, start=60, end=150, workers=("A",)),
    Assignment(order_id="k2", op_id="pack", machine=None, start=90, end=110, workers=("A",)),
    Assignment(order_id="k1", op_id="pack", machine=None, start=150, end=170, workers=("B",)),
]
BREAKS = (Break(worker="A", start=240), Break(worker="B", start=240))
PRINT_DONE = FrozenOperation(order_id="k1", op_id="print", machine="P", start=0, end=60, running=False,
                             workers=("A",), share_lengths=(15,))


def gb(prefix_until, t):
    """Gegenbetten running since 60, its prefix by A until `prefix_until` (running: at least t + 1)."""
    return FrozenOperation(order_id="k1", op_id="gb", machine=None, start=60, end=max(150, t + 1), running=True,
                           workers=("A",), share_lengths=(prefix_until - 60,))


def repaired(t, frozen, taken=()):
    snap = Snapshot(instance=TOY.name, t=t, frozen=(PRINT_DONE, *frozen), breaks=taken)
    plan = repair_plan(TOY, snap, PLAN, (*[b for b in BREAKS if b not in taken], *taken))
    assert check_schedule(TOY, plan.assignments, snap, plan.breaks) == []
    return by_key(plan.assignments), plan.breaks


def test_share_pushed_into_the_break_resumes_after_it():
    # at 230 A's prefix still runs (until 231): the packaging [231, 251) would cross A's break: 13:00
    got, breaks = repaired(230, [gb(231, 230)])
    assert got["k2", "pack"] == (None, 300, 320, ("A",)) and breaks == BREAKS


def test_overdue_break_moves_to_t():
    # A's prefix ran until 250, so A could not take the break at 12:00 (B took it); at 250 it moves to 250 and the
    # packaging follows it at 310
    got, breaks = repaired(250, [gb(250, 250)], taken=(Break(worker="B", start=240),))
    assert sorted(breaks, key=lambda b: b.worker) == [Break(worker="A", start=250), Break(worker="B", start=240)]
    assert got["k2", "pack"] == (None, 310, 330, ("A",))


def test_share_pushed_past_the_shift_end_goes_to_the_next_morning():
    # at 555 Gegenbetten still runs (expected end 556): B's packaging [556, 576) would end after 17:30 (570, no
    # overtime by the repair): Tuesday 08:00; a break for B on Tuesday is owed then and placed at 12:00
    got, breaks = repaired(555, [gb(90, 555)], taken=BREAKS)
    assert got["k1", "pack"] == (None, 1440, 1460, ("B",))
    assert Break(worker="B", start=1680) in breaks


# --- end to end: execute with repair only and with rule rescheduling -------------------------------------------

def long_packaging_to_noon():
    """toy-workers with A only: k2 packaging of 120 minutes 10:00-12:00, right before A's break; an overrun keeps A
    busy past 13:00 (forced postponement, C14^f)."""
    data = json.loads(json.dumps(TOY_DATA)) | {"workers": ["A"]}
    for order in data["orders"]:
        order.pop("due_date", None)
        order["release"] = 300
    data["orders"][1]["release"] = 120
    data["orders"][1]["operations"][0]["duration"] = 120
    return data


def ovens_one_worker():
    """Oven removals around 11:50 with one worker, who packs right before (forced overstay with the calendar)."""
    data = ovens_at(230) | {"workers": ["W1"]}
    data["orders"].append({"id": "P", "release": 220, "operations": [
        {"id": "pack", "step": "pack", "duration": 10, "worker": {"whole": True}}]})
    return data


END_TO_END = SWEEP | {"long-packaging-to-noon": long_packaging_to_noon(), "ovens-one-worker": ovens_one_worker()}


def test_execute_with_repair_and_rule_rescheduling(monkeypatch):
    # every repaired and rescheduled plan passes update_plan's checker (with its breaks, against the snapshot); the
    # realized schedules pass up to C2 (durations) and C14 for breaks realized after 13:00 (a forced postponement,
    # allowed against the snapshot of its time). Coverage (protocol 2026-11-09 (33)): each case occurs
    import simulation.control.rescheduling as rescheduling

    seen = collections.Counter()

    def counting_repair(ci, snap, plan, breaks=(), **options):
        out = repair_plan(ci, snap, plan, breaks, **options)
        cal, frozen = ci.calendar, {(f.order_id, f.op_id): f for f in snap.frozen}
        old = {(b.worker, day_index(cal, b.start)): b.start for b in breaks}
        taken = {(b.worker, b.start) for b in snap.breaks}
        for b in out.breaks:
            key = (b.worker, day := day_index(cal, b.start))
            if key not in old:
                seen["break added"] += 1
            elif old[key] != b.start and (b.worker, old[key]) not in taken and old[key] <= snap.t:
                seen["due break moved"] += 1
                seen["forced postponement"] += b.start > day_start(cal, day) + cal.break_latest
        before = {(a.order_id, a.op_id): a for a in plan}
        for a in out.assignments:
            f, p = frozen.get((a.order_id, a.op_id)), before[a.order_id, a.op_id]
            if f is not None and f.running and None in f.workers:
                seen["forced overstay"] += a.end > f.end
            elif f is None and a.workers:
                seen["moved to another day"] += day_index(cal, a.start) != day_index(cal, p.start)
        return out

    monkeypatch.setattr(rescheduling, "repair_plan", counting_repair)
    for name, data in END_TO_END.items():
        model = Instance.model_validate(data)
        ci = compile_instance(model)
        start = dispatch_plan(ci, spt)
        for policy in (REPAIR, ReschedulingPolicy(planner=dispatch_planner(spt), max_shift=30)):
            for seed in range(6 if name in SWEEP else 20):  # targeted cases: factors only, so the timing holds
                sc = sample_scenario(model, sigma=0.6, seed=seed, q=0.4 if name in SWEEP else 1.0, max_late=30)
                result = execute(ci, start.assignments, sc, policy, start.breaks)
                late = [b for b in result.breaks if minute_of_day(ci.calendar, b.start) > ci.calendar.break_latest]
                violations = check_schedule(ci, result.schedule, breaks=result.breaks)
                assert {v.constraint for v in violations} <= {"C2", "C14"}, name
                assert len([v for v in violations if v.constraint == "C14"]) == len(late), name
    assert all(seen[k] > 0 for k in ("break added", "due break moved", "forced postponement", "forced overstay",
                                     "moved to another day")), seen


def test_pending_removal_postpones_the_break():
    # C14^f with a pending removal (user 2026-11-09): one worker, L1's oven [2, 310) with its removal at 13:09
    # [309, 310) not started at 12:50 (290); W1's break, due since 12:00, cannot fit [290, 350) next to the removal,
    # so it starts at 13:10 (310), the earliest clear start from max(12:00, t); any other start after 13:00 is C14
    data = ovens_at(308) | {"workers": ["W1"]}
    ci = compile_instance(Instance.model_validate(data))
    start = dispatch_plan(ci, spt)
    rows = {(a.order_id, a.op_id): a for a in start.assignments}
    assert (rows["L1", "oven"].start, rows["L1", "oven"].end) == (2, 310) and rows["L2", "oven"].start >= 310
    assert start.breaks[0] == Break(worker="W1", start=240)  # L2's mill runs the next day: a second break there
    frozen = [FrozenOperation(order_id=k, op_id="print", machine="P", start=a.start, end=a.end, running=False)
              for k in ("L1", "L2") for a in [rows[k, "print"]]]
    frozen.append(FrozenOperation(order_id="L1", op_id="oven", machine="O", start=2, end=310, running=True,
                                  workers=("W1", None), share_lengths=(1, 1)))
    snap = Snapshot(instance=ci.name, t=290, frozen=tuple(frozen))
    plan = repair_plan(ci, snap, start.assignments, start.breaks)
    assert plan.breaks[0] == Break(worker="W1", start=310)
    assert check_schedule(ci, plan.assignments, snap, plan.breaks) == []
    late = check_schedule(ci, plan.assignments, snap, (Break(worker="W1", start=320), *plan.breaks[1:]))
    assert {v.constraint for v in late} == {"C14"} and any("not forced" in v.message for v in late)


# --- option: overtime up to the window (user 2026-11-11) ----------------------------------------------------------

def _late_chain():
    """One worker W1; o0 [16:00, 17:00) then o1 [17:00, 17:30), no overtime planned; o0 starts 25 minutes late
    (16:25, expected end 17:25), seen before o1 is released at its planned start."""
    from test_des_workers import scenario
    from test_worker_objective import chain

    ci = chain(480, (60, 30), 1680)
    return ci, dispatch_plan(ci, spt), scenario(ci, K_o0=(1.0, 25))


@pytest.mark.parametrize(("overtime", "o1_start"), [(False, 1440), (True, 565)])
def test_repair_moves_into_overtime_only_with_the_option(overtime, o1_start):
    # at 16:25 o0 starts (expected end 17:25): o1 (30) would end at 17:55, after the shift end and after the plan's
    # last share that day (17:30): without the option to Tuesday 08:00, with it 17:25-17:55 (overtime 25)
    ci, plan, sc = _late_chain()
    sim = Simulation(ci, plan.assignments, sc, plan.breaks)
    sim.run(until=505)
    snap = sim.snapshot()
    new = repair_plan(ci, snap, plan.assignments, sim.current_breaks(), overtime=overtime)
    assert check_schedule(ci, new.assignments, snap, new.breaks) == []
    assert next(a.start for a in new.assignments if a.op_id == "o1") == o1_start


@pytest.mark.parametrize(("overtime", "o1_start"), [(False, 1440), (True, 565)])
def test_execute_with_the_repair_overtime_option(overtime, o1_start):
    ci, plan, sc = _late_chain()
    result = execute(ci, plan.assignments, sc, ReschedulingPolicy(repair_overtime=overtime), breaks=plan.breaks)
    assert next(a.start for a in result.schedule if a.op_id == "o1") == o1_start
    assert {v.constraint for v in check_schedule(ci, result.schedule, breaks=result.breaks)} <= {"C2"}
