"""CP-SAT with workers and the calendar: shifts, overtime, breaks (math/12_cp-sat.md section 7b, math/04_workers.md;
plan docs/superpowers/plans/2026-11-09-workers-phase4-repair-cpsat.md, Task 4).

t = 0 is Monday 08:00; 10:30 is t = 150, 12:00 t = 240, 13:00 t = 300, 15:00 t = 420, 17:30 (shift end) t = 570,
19:30 (shift end + max overtime) t = 690, Tuesday 08:00 t = 1440, 13:00 t = 1740.
"""

import pytest
from test_des_workers import scenario
from test_dispatching_workers import by_key
from test_repair_calendar import END_TO_END, INSTANCES, long_packaging_to_noon
from test_rule_snapshot_calendar import ovens_at

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Break
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot


def jobs(workers, durations, release):
    """Machine-less operations with a whole share each, released at `release`, with the default calendar."""
    return compile_instance(Instance.model_validate({
        "schema_version": "0.6", "name": "jobs", "machines": ["M"], "workers": list(workers), "calendar": {},
        "orders": [{"id": f"J{i}", "release": release, "operations": [
            {"id": "op", "step": "s", "duration": d, "worker": {"whole": True}}]} for i, d in enumerate(durations)]}))


def optimum(ci):
    """The optimal plan; it passes the checker with its breaks and replays unchanged, breaks included."""
    result = solve(ci, MAKESPAN, time_limit=10, workers=1)
    assert result.status == "OPTIMAL"
    assert check_schedule(ci, result.schedule, breaks=result.breaks) == []
    done = replay(ci, result.schedule, breaks=result.breaks)
    assert by_key(done.schedule) == by_key(result.schedule)
    assert set(done.breaks) <= set(result.breaks)  # breaks after the last share are never taken
    assert max(a.end for a in result.schedule) == result.objective
    return result


@pytest.mark.parametrize(("workers", "makespan"), [(("W1",), 390), (("W1", "W2"), 240)])
def test_the_break_separates_the_shares_of_one_worker(workers, makespan):
    # two jobs of 90 from 10:30: one worker [150, 240), break [240, 300), [300, 390); two workers both until 12:00
    result = optimum(jobs(workers, (90, 90), 150))
    assert result.objective == makespan
    if len(workers) == 1:
        assert Break(worker="W1", start=240) in result.breaks


def test_overtime_is_used_within_the_limit():
    # 240 minutes from 15:00 end at 19:00, 90 minutes of overtime (at most 120)
    assert optimum(jobs(("W1",), (240,), 420)).objective == 660


def test_a_share_that_does_not_fit_goes_to_the_next_day_after_the_break():
    # 300 minutes from 15:00 would end at 20:00 (> 19:30): Tuesday 08:00-13:00, the break at 13:00 (the latest
    # start is allowed, C14)
    result = optimum(jobs(("W1",), (300,), 420))
    assert result.objective == 1740
    assert Break(worker="W1", start=1740) in result.breaks


@pytest.mark.parametrize("name", INSTANCES)
def test_zero_disturbance_on_the_calendar_instances(name):
    # also the repair keeps a CP-SAT plan (with overtime) unchanged: it allows the plan's own overtime per day
    ci = INSTANCES[name]
    result = optimum(ci)
    run = execute(ci, result.schedule, policy=ReschedulingPolicy(), breaks=result.breaks)
    assert run.decisions == [] and by_key(run.schedule) == by_key(result.schedule)


def test_pending_removal_postpones_the_break():
    # the snapshot of tests/test_repair_calendar.py: one worker, L1's removal at 13:09 not started at 12:50; no break
    # fits in the window next to it: CP-SAT plans it at 13:10 (C14^f)
    ci = compile_instance(Instance.model_validate(ovens_at(308) | {"workers": ["W1"]}))
    start = dispatch_plan(ci, spt)
    rows = {(a.order_id, a.op_id): a for a in start.assignments}
    frozen = [FrozenOperation(order_id=k, op_id="print", machine="P", start=a.start, end=a.end, running=False)
              for k in ("L1", "L2") for a in [rows[k, "print"]]]
    frozen.append(FrozenOperation(order_id="L1", op_id="oven", machine="O", start=2, end=310, running=True,
                                  workers=("W1", None), share_lengths=(1, 1)))
    snap = Snapshot(instance=ci.name, t=290, frozen=tuple(frozen))
    result = solve(ci, MAKESPAN, time_limit=10, workers=1, snapshot=snap)
    assert check_schedule(ci, result.schedule, snap, result.breaks) == []
    assert Break(worker="W1", start=310) in result.breaks


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("name", END_TO_END)
def test_plans_from_disturbed_calendar_snapshots_are_accepted(name, seed):
    # DES snapshots of a disturbed run of the rule plan at 10 time points (the targeted instances force late breaks
    # and overstays); each CP-SAT plan passes the checker with its breaks against the snapshot and is accepted
    model = Instance.model_validate(END_TO_END[name])
    ci = compile_instance(model)
    start = dispatch_plan(ci, spt)
    sc = sample_scenario(model, sigma=0.6, seed=seed, q=0.4 if name in INSTANCES else 1.0, max_late=30)
    horizon = max(a.end for a in replay(ci, start.assignments, sc, breaks=start.breaks).schedule)
    for t in range(1, horizon, max(1, horizon // 10)):
        sim = Simulation(ci, start.assignments, sc, start.breaks)
        sim.run(until=t)
        snap = sim.snapshot()
        result = solve(ci, MAKESPAN, time_limit=10, workers=1, snapshot=snap, hint=sim.current_plan())
        assert result.schedule, (t, result.status)
        assert check_schedule(ci, result.schedule, snap, result.breaks) == [], t
        sim.update_plan(result.schedule, result.breaks)


@pytest.mark.parametrize("name", END_TO_END)
def test_execute_with_cpsat_rescheduling(name):
    # the planning tool with CP-SAT on calendar instances; realized up to C2 and C14 for breaks realized after 13:00
    model = Instance.model_validate(END_TO_END[name])
    ci = compile_instance(model)
    start = dispatch_plan(ci, spt)
    policy = ReschedulingPolicy(planner=cpsat_planner(time_limit=10), max_shift=30)
    sc = sample_scenario(model, sigma=0.6, seed=0, q=0.4 if name in INSTANCES else 1.0, max_late=30)
    result = execute(ci, start.assignments, sc, policy, start.breaks)
    assert {v.constraint for v in check_schedule(ci, result.schedule, breaks=result.breaks)} <= {"C2", "C14"}


def test_forced_postponement_from_snapshots_around_noon():
    # targeted: A alone, the 120-minute packaging 10:00-12:00 at factor 1.6 runs until 13:12 (312); snapshots every
    # minute from 11:50 to 13:20. While A's break is pending after 13:00, CP-SAT must plan it at the packaging's
    # expected end (C14^f); every plan passes the checker with its breaks and is accepted
    model = Instance.model_validate(long_packaging_to_noon())
    ci = compile_instance(model)
    start = dispatch_plan(ci, spt)
    sc = scenario(ci, k2_pack=1.6)
    late = 0
    for t in range(230, 321):
        sim = Simulation(ci, start.assignments, sc, start.breaks)
        sim.run(until=t)
        snap = sim.snapshot()
        result = solve(ci, MAKESPAN, time_limit=10, workers=1, snapshot=snap, hint=sim.current_plan())
        assert check_schedule(ci, result.schedule, snap, result.breaks) == [], t
        sim.update_plan(result.schedule, result.breaks)
        late += any(b.start > 300 and b not in snap.breaks for b in result.breaks if b.start < 1440)
    assert late > 0
