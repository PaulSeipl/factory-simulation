"""DES and repair for s-batches (math/08, s-batch spec §7 step 4), on the hand batch of test_s_batch_checker:
polishings of O1 and O2 as batch b1 [6, 61) = 5 + 25 + 25 by worker A, then pack O1 [61,71), O2 [71,81)."""

import pytest
from test_s_batch_checker import CI, plan
from test_s_batch_format import tiny

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Calendar
from simulation.model.schedule import Break
from simulation.planners.cpsat import cpsat_planner
from simulation.planners.dispatching import dispatch_planner, ect, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import Scenario


def scenario(ci, factor=None, offset=None) -> Scenario:
    factor, offset = factor or {}, offset or {}
    return Scenario(instance=ci.name, seed=0, sigma=0, factors=[
        {"order_id": k, "op_id": j, "factor": factor.get(f"{k}/{j}", 1.0), "start_offset": offset.get(f"{k}/{j}", 0)}
        for k, j in ci.op_keys])


def rows(schedule):
    return {(a.order_id, a.op_id): (a.start, a.end, a.batch) for a in schedule}


def test_zero_disturbance_replays_the_batch_unchanged():
    realized = replay(CI, plan()).schedule
    assert rows(realized) == rows(plan())
    assert check_schedule(CI, realized) == []


def test_realized_length_by_hand():
    # setup with the factor of the first member (O1): round(5 * 2) = 10; O1 round(25 * 2) = 50, O2 round(25 * 1) = 25
    # -> both polishings [6, 91); packs follow on A: [91, 101), [101, 111)
    realized = replay(CI, plan(), scenario(CI, factor={"O1/polish": 2.0})).schedule
    r = rows(realized)
    assert r["O1", "polish"] == r["O2", "polish"] == (6, 91, "b1")
    assert (r["O1", "pack"], r["O2", "pack"]) == ((91, 101, None), (101, 111, None))
    assert {v.constraint for v in check_schedule(CI, realized)} <= {"C2"}  # realized durations deviate


def test_a_late_member_delays_the_whole_batch():
    r = rows(replay(CI, plan(), scenario(CI, offset={"O2/polish": 3})).schedule)
    assert r["O1", "polish"] == r["O2", "polish"] == (9, 64, "b1")


def test_the_batch_waits_for_its_members():
    # a longer print (factor 2: [0,10), saw [10,11)): the setup starts only once both members are ready
    r = rows(replay(CI, plan(), scenario(CI, factor={"R1/print": 2.0})).schedule)
    assert r["O1", "polish"] == r["O2", "polish"] == (11, 66, "b1")


def test_snapshot_mid_batch_carries_the_batch_and_its_length():
    sim = Simulation(CI, plan())
    sim.run(until=20)
    frozen = {(f.order_id, f.op_id): f for f in sim.snapshot().frozen}
    for k in ("O1", "O2"):
        f = frozen[k, "polish"]
        assert (f.start, f.end, f.running, f.batch, f.share_lengths) == (6, 61, True, "b1", (55,))


@pytest.mark.parametrize("planner", [None, dispatch_planner(spt, ect), cpsat_planner(time_limit=5)],
                         ids=["repair", "rule", "cpsat"])
def test_replanning_during_a_batch_keeps_it(planner):
    # disturbed, repaired at every time point; with the rule also rescheduled every 10 minutes, the first time at 10
    # while the batch runs [6, 73): its members stay frozen as one batch and the plans pass the checker (a replan
    # before 6 would dissolve the batch: the rule forms none until step 5)
    disturbed = scenario(CI, factor={"O1/polish": 1.4, "O2/pack": 0.5}, offset={"O1/pack": 2})
    result = execute(CI, plan(), disturbed, ReschedulingPolicy(planner=planner, period=10 if planner else None))
    r = rows(result.schedule)
    assert r["O1", "polish"][:2] == r["O2", "polish"][:2] and r["O1", "polish"][2] == r["O2", "polish"][2] == "b1"
    # setup with the factor of the first member (O1): round(5 * 1.4) = 7; round(25 * 1.4) = 35, O2 25
    assert r["O1", "polish"][:2] == (6, 6 + 7 + 35 + 25)
    assert {v.constraint for v in check_schedule(CI, result.schedule)} <= {"C2"}


def test_a_batch_on_a_machine_replays_unchanged():
    ci = compile_instance(tiny(3, polish_machines=2, polish={"setup": 5}))
    on = plan(**{"O1/polish": ("polish1", 6, 61, ("A",), "b1"), "O2/polish": ("polish1", 6, 61, ("A",), "b1")})
    assert rows(replay(ci, on).schedule) == rows(on)


def test_the_shift_holds_the_whole_batch():
    # default calendar, t = 0 is Monday 08:00, shift end + overtime at t = 690. A print of 639 makes both members
    # ready at 640: one member (30) would still fit, the batch (55) does not, so it waits for Tuesday 08:00 (1440)
    ci = compile_instance(tiny(3, polish={"setup": 5}).model_copy(update={"calendar": Calendar()}))
    breaks = [Break(worker="A", start=240)]
    assert check_schedule(ci, plan(), breaks=breaks) == []
    realized = replay(ci, plan(), scenario(ci, factor={"R1/print": 639 / 5}), breaks).schedule
    assert rows(realized)["O1", "polish"] == rows(realized)["O2", "polish"] == (1440, 1495, "b1")
