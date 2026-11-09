"""Dispatching rules with worker shares and machine-less operations, no calendar yet (math/11_dispatching-rules.md,
math/04_workers.md section 5; plan phase 3 tasks 2 and 3).

Instances: toy-workers without its calendar (print with prefix, Gegenbetten with prefix and rest for A only,
packaging as whole shares) and the carrier instance (oven batch with prefix and suffix, attended mill runs).
"""

import json
from pathlib import Path

import pytest
from test_des_workers import scenario as factor_scenario
from test_worker_compile import CARRIERS, carriers

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Break
from simulation.objectives import TOTAL_TARDINESS
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch, dispatch_plan, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import sample_scenario

_data = json.loads((Path(__file__).parents[1] / "data" / "instances" / "toy-workers.json").read_text())
TOY_MODEL = Instance.model_validate(_data)  # with its calendar
_data.pop("calendar")
TOY = compile_instance(Instance.model_validate(_data))
RULES = [(s, a) for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None]]


def by_key(plan):
    return {(a.order_id, a.op_id): (a.machine, a.start, a.end, a.workers) for a in plan}


def test_hand_plan_toy_workers():
    # t=0: k2 packaging (SPT 20 < 60) by A (tie in load, lower index); print at 0 too, its prefix [0, 15) finds A
    # busy, so B; Gegenbetten at 60, prefix only A (qualified); k1 packaging at 150: A load 50, B load 15 -> B
    assert by_key(dispatch(TOY, spt)) == {
        ("k2", "pack"): (None, 0, 20, ("A",)),
        ("k1", "print"): ("P", 0, 60, ("B",)),
        ("k1", "gb"): (None, 60, 150, ("A",)),
        ("k1", "pack"): (None, 150, 170, ("B",)),
    }


def test_hand_plan_oven_batch_and_runs():
    # prints [0, 2), [2, 4); L1 oven alone at 2 (L2 not ready): load W1 [2, 3), unload [6, 7) by W2 (load 0 < 1);
    # at 7 L2 oven (SPT 5 < run 6): W1 [7, 8) (tie, index), W2 [11, 12) (load 1 < 2); L1 mill setup at 7: W1 busy,
    # W2 free in the gap [7, 8) before its unload at 11; removal [12, 13) W1 (load 2 < 3); L2 run from 13: setup W1
    # (tie 3, index), removal [18, 19) W2 (load 3 < 4)
    assert by_key(dispatch(CARRIERS, spt)) == {
        ("L1", "print"): ("P", 0, 2, ()), ("L2", "print"): ("P", 2, 4, ()),
        ("L1", "oven"): ("O", 2, 7, ("W1", "W2")), ("L2", "oven"): ("O", 7, 12, ("W1", "W2")),
        ("L1", "mill/setup"): ("M", 7, 8, ("W2",)), ("L1", "mill"): ("M", 8, 12, ()),
        ("L1", "mill/removal"): ("M", 12, 13, ("W1",)),
        ("L2", "mill/setup"): ("M", 13, 14, ("W1",)), ("L2", "mill"): ("M", 14, 18, ()),
        ("L2", "mill/removal"): ("M", 18, 19, ("W2",)),
    }


def test_batch_shares_planned_once():
    # a second printer: both plates ready at 2 share one oven run [2, 7) with one loading and one unloading (W1:
    # load 0, then 1 vs W2 0 -> W2), both members carry the same workers
    data = carriers()
    data["machines"].append("P2")
    data["carrier_steps"]["print"]["options"]["P2"] = 2
    ci = compile_instance(Instance.model_validate(data))
    plan = by_key(dispatch(ci, spt))
    assert plan["L1", "oven"] == plan["L2", "oven"] == ("O", 2, 7, ("W1", "W2"))
    assert check_schedule(ci, list(dispatch(ci, spt))) == []


INSTANCES = {"toy-workers": TOY, "carriers": CARRIERS}


@pytest.mark.parametrize(("seq", "asg"), RULES, ids=[f"{s}/{a or 'joint'}" for s, a in RULES])
@pytest.mark.parametrize("name", INSTANCES)
def test_every_rule_plan_is_feasible_and_replays(name, seq, asg):
    ci = INSTANCES[name]
    plan = dispatch(ci, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[asg] if asg else None)
    assert check_schedule(ci, plan) == []
    assert by_key(replay(ci, plan).schedule) == by_key(plan)  # zero disturbance: realized = plan


# --- with the calendar (phase 3 task 3): t = 0 is Monday 08:00, 12:00 is t = 240, Tuesday 08:00 is t = 1440 -----

DAY = 1440


def one_pack(release: int, due: int | None = None, duration: int = 60):
    order = {"id": "k", "release": release,
             "operations": [{"id": "pack", "step": "pack", "duration": duration, "worker": {"whole": True}}]}
    return compile_instance(Instance.model_validate({
        "schema_version": "0.6", "name": "cal", "machines": ["M"], "workers": ["A"], "calendar": {},
        "orders": [order | ({"due_date": due} if due is not None else {})]}))


def test_share_is_pushed_past_the_break_and_is_one_day_late():
    # Friday 11:30 + 60 would cross 12:00: after the break 13:00 to 14:00; due Friday 12:00 -> 1 missed cutoff
    friday = 4 * DAY
    ci = one_pack(friday + 210, due=friday + 240)
    plan = dispatch(ci, spt)
    assert by_key(plan) == {("k", "pack"): (None, friday + 300, friday + 360, ("A",))}
    assert dispatch_plan(ci, spt).breaks == (Break(worker="A", start=friday + 240),)
    assert TOTAL_TARDINESS.evaluate(ci, plan) == 1


def test_friday_evening_moves_to_monday_morning():
    # released Friday 17:00, 60 minutes do not fit before 17:30 (no overtime in the rule): Monday 08:00, on time
    ci = one_pack(4 * DAY + 540, due=7 * DAY + 240)
    plan = dispatch(ci, spt)
    assert by_key(plan) == {("k", "pack"): (None, 7 * DAY, 7 * DAY + 60, ("A",))}
    assert TOTAL_TARDINESS.evaluate(ci, plan) == 0


def test_share_longer_than_a_shift_part_cannot_be_planned():
    with pytest.raises(ValueError, match="longer than"):
        dispatch(one_pack(0, duration=300), spt)  # 08:00-12:00 is 240, 13:00-17:30 is 270


def test_shares_that_never_fit_the_shifts_together_raise():
    # oven program of 14 hours: loading at 08:00-17:29 ends the program at 22:00-07:29, outside every shift
    data = carriers() | {"calendar": {}}
    data["carrier_steps"]["oven"]["options"]["O"] = 840
    with pytest.raises(ValueError, match="never lie within the shifts"):
        dispatch(compile_instance(Instance.model_validate(data)), spt)


def night_carriers():
    """The carrier instance with the calendar and a 600-minute mill program: the run ends after the shift."""
    data = carriers() | {"calendar": {}}
    data["carrier_steps"]["mill"]["options"]["M"] = 600
    return compile_instance(Instance.model_validate(data))


def test_removal_after_a_night_run_waits_for_the_morning():
    # as without calendar until 7 (oven batches, L1 setup [7, 8) by W2); L1 mill [8, 608) ends 18:08: removal
    # Tuesday 08:00 by W1 (load 2 < 3), M blocked until 1441; L2 setup [1441, 1442) W1 (tie 3, index), mill until
    # 2042 (Tuesday 18:02), removal Wednesday 08:00 by W2 (3 < 4)
    ci = night_carriers()
    plan = by_key(dispatch(ci, spt))
    assert plan["L1", "mill/setup"] == ("M", 7, 8, ("W2",))
    assert plan["L1", "mill"] == ("M", 8, 608, ())
    assert plan["L1", "mill/removal"] == ("M", DAY, DAY + 1, ("W1",))
    assert plan["L2", "mill/setup"] == ("M", DAY + 1, DAY + 2, ("W1",))
    assert plan["L2", "mill/removal"] == ("M", 2 * DAY, 2 * DAY + 1, ("W2",))
    assert dispatch_plan(ci, spt).breaks == tuple(
        Break(worker=w, start=d * DAY + 240) for w, d in (("W1", 0), ("W1", 1), ("W2", 0), ("W2", 2)))


CALENDAR_INSTANCES = {"toy-workers": compile_instance(TOY_MODEL), "night-carriers": night_carriers()}


@pytest.mark.parametrize(("seq", "asg"), RULES, ids=[f"{s}/{a or 'joint'}" for s, a in RULES])
@pytest.mark.parametrize("name", CALENDAR_INSTANCES)
def test_every_rule_plan_with_calendar_is_feasible_and_replays(name, seq, asg):
    ci = CALENDAR_INSTANCES[name]
    plan, breaks = dispatch_plan(ci, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[asg] if asg else None)
    assert check_schedule(ci, plan, breaks=breaks) == []
    result = replay(ci, plan, breaks=breaks)
    assert by_key(result.schedule) == by_key(plan) and result.breaks == breaks


def test_no_breaks_without_calendar():
    assert dispatch_plan(TOY, spt).breaks == ()


# --- from a snapshot (phase 3 task 4, no calendar) ---------------------------------------------------------------


def snap_at(ci, plan, t, scenario=None):
    sim = Simulation(ci, plan, scenario)
    sim.run(until=t)
    return sim.snapshot()


def test_pending_oven_removal_gets_a_worker_and_the_run_continues():
    # carrier rule plan (test_hand_plan_oven_batch_and_runs), snapshot at t = 9: L1 run setup [7, 8) done by W2,
    # mill [8, 12) running, its removal not started; L2 oven [7, 12) running, loaded by W1, removal pending.
    # Booked: W1 [2, 3), [7, 8); W2 [6, 7), [7, 8): load 2 each -> L2 removal [11, 12) W1 (tie, index);
    # L1 removal [12, 13) W2 (2 < 3); L2 run setup [13, 14) W1 (tie 3), removal [18, 19) W2 (3 < 4)
    plan = dispatch(CARRIERS, spt)
    snap = snap_at(CARRIERS, plan, 9)
    new = dispatch(CARRIERS, spt, snapshot=snap)
    assert check_schedule(CARRIERS, new, snap) == []
    got = by_key(new)
    assert got["L2", "oven"] == ("O", 7, 12, ("W1", "W1"))
    assert got["L1", "oven"] == ("O", 2, 7, ("W1", "W2"))  # finished: kept
    assert got["L1", "mill/removal"] == ("M", 12, 13, ("W2",))
    assert got["L2", "mill/setup"] == ("M", 13, 14, ("W1",))
    assert got["L2", "mill/removal"] == ("M", 18, 19, ("W2",))


def test_frozen_machine_less_share_occupies_its_worker():
    # toy rule plan, Gegenbetten takes twice as long; snapshot at 70: Gegenbetten [60, 150) by A running (expected
    # end 150), k1 packaging at 150: A load 20 + 30 = 50, B 15 -> B
    plan = dispatch(TOY, spt)
    snap = snap_at(TOY, plan, 70, factor_scenario(TOY, k1_gb=2.0))
    assert next(f for f in snap.frozen if f.op_id == "gb").running
    new = dispatch(TOY, spt, snapshot=snap)
    assert check_schedule(TOY, new, snap) == []
    assert by_key(new)[("k1", "gb")] == (None, 60, 150, ("A",))
    assert by_key(new)[("k1", "pack")] == (None, 150, 170, ("B",))



@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("name", INSTANCES)
def test_every_rule_plan_from_a_disturbed_snapshot_is_feasible(name, seed):
    ci = INSTANCES[name]
    model = Instance.model_validate(_data if name == "toy-workers" else carriers())
    scenario = sample_scenario(model, sigma=0.5, seed=seed)
    plan = dispatch(ci, spt)
    horizon = max(a.end for a in plan)
    for t in range(1, horizon, max(1, horizon // 10)):
        snap = snap_at(ci, plan, t, scenario)
        for seq, asg in RULES:
            new = dispatch(ci, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[asg] if asg else None, snap)
            assert check_schedule(ci, new, snap) == [], (t, seq, asg)


