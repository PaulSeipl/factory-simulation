"""CP-SAT with worker shares and machine-less operations, no calendar (math/12_cp-sat.md, math/04_workers.md; plan
docs/superpowers/plans/2026-11-09-workers-phase4-repair-cpsat.md, Task 3).

Instances: toy-workers without its calendar, the carrier instance (oven batch with prefix and suffix, attended mill
runs), a mini instance with two machine-less whole shares, and the one-worker oven case of the forced overstay.
"""

import pytest
from test_des_workers import scenario
from test_dispatching_workers import TOY, by_key, snap_at
from test_forced_overstay import ONE_WORKER, ROWS, SLOW_POLISH
from test_repair_workers import MODELS, PACK, one_worker_with_packaging, oven_snapshot
from test_worker_compile import CARRIERS

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch, fifo, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import sample_scenario


def two_jobs(workers):
    """Two machine-less operations of 10 and 20 minutes, each needing a worker all the time."""
    return compile_instance(Instance.model_validate({
        "schema_version": "0.7", "name": "two-jobs", "machines": ["M"], "workers": list(workers),
        "orders": [{"id": k, "operations": [{"id": "op", "step": "s", "duration": d, "worker": {"whole": True}}]}
                   for k, d in (("A", 10), ("B", 20))]}))


def optimum(ci):
    result = solve(ci, MAKESPAN, time_limit=10, workers=1)
    assert result.status == "OPTIMAL"
    assert check_schedule(ci, result.schedule) == []
    assert by_key(replay(ci, result.schedule).schedule) == by_key(result.schedule)  # zero disturbance
    assert max(a.end for a in result.schedule) == result.objective  # realized makespan = CP-SAT value
    return result


@pytest.mark.parametrize(("workers", "makespan"), [(("W1",), 30), (("W1", "W2"), 20)])
def test_one_worker_does_one_thing_at_a_time(workers, makespan):
    # C12: with one worker the two operations run one after the other (30), with two in parallel (20)
    assert optimum(two_jobs(workers)).objective == makespan


def test_hand_optimum_toy_workers():
    # chain print 60 -> Gegenbetten 90 -> packaging 20 = 170 is a lower bound and reached: the prefixes (15 and 30)
    # and the other packaging fit around it with two workers
    result = optimum(TOY)
    assert result.objective == 170
    gb = next(a for a in result.schedule if a.op_id == "gb")
    assert gb.machine is None and gb.workers == ("A",)  # machine-less, only A qualified (C11)


def test_hand_optimum_carriers():
    # mill runs need 6 each on M; the first can start at 7 at the earliest (print [0, 2), oven [2, 7)): 7 + 12 = 19,
    # reached with L1 oven [2, 7), L2 oven [7, 12) (L1's mill setup and L2's loading at 7 by the two workers)
    assert optimum(CARRIERS).objective == 19


def test_forced_overstay_from_a_snapshot():
    # one worker, polishing [5, 8) at factor 2: at 8 W1 polishes until 9, the oven batch [4, 9) waits for its removal:
    # forced [9, 10) (C7^o), the batch ends at 10, the mill runs follow; the CP-SAT plan passes the checker
    snap = snap_at(ONE_WORKER, ROWS, 8, SLOW_POLISH)
    result = solve(ONE_WORKER, MAKESPAN, time_limit=10, workers=1, snapshot=snap)
    assert result.status == "OPTIMAL" and check_schedule(ONE_WORKER, result.schedule, snap) == []
    got = by_key(result.schedule)
    assert got["L1", "oven"] == got["L2", "oven"] == ("O", 4, 10, ("W1", "W1"))


@pytest.mark.parametrize("busy", [set(), {"C"}, {"C", "D"}])
def test_pending_removal_from_a_hand_snapshot(busy):
    # the oven batch at t = 8 (tests/test_repair_workers.py): removal by W2 or W1 at 9, or by W1 at 10 (forced)
    snap, current = oven_snapshot(busy)
    result = solve(PACK, MAKESPAN, time_limit=10, workers=1, snapshot=snap, hint=current)
    assert result.status == "OPTIMAL" and check_schedule(PACK, result.schedule, snap) == []
    ends = {a.end for a in result.schedule if a.op_id == "oven"}
    assert ends == ({11} if busy == {"C", "D"} else {9})


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("name", MODELS)
def test_plans_from_disturbed_snapshots_are_accepted(name, seed):
    # snapshots of a disturbed DES run of the rule plan at 8 time points; each CP-SAT plan passes the checker
    # against its snapshot and is accepted by the DES
    model = MODELS[name]
    ci = compile_instance(model)
    plan = dispatch(ci, spt)
    sc = sample_scenario(model, sigma=0.4, seed=seed, q=0.5, max_early=5, max_late=5)
    horizon = max(a.end for a in replay(ci, plan, sc).schedule)
    for t in range(1, horizon, max(1, horizon // 8)):
        sim = Simulation(ci, plan, sc)
        sim.run(until=t)
        snap = sim.snapshot()
        result = solve(ci, MAKESPAN, time_limit=5, workers=1, snapshot=snap, hint=sim.current_plan())
        assert result.schedule, result.status
        assert check_schedule(ci, result.schedule, snap) == [], (t, result.status)
        sim.update_plan(result.schedule)


def test_plans_from_snapshots_with_forced_overstays():
    # targeted (tests/test_repair_workers.py): one worker, a packaging released into the oven run, and the hand plan
    # with a slower polishing right before the removal; snapshot at every minute. Every CP-SAT plan passes the
    # checker against its snapshot, and forced overstays (C7^o) occur among them
    model = one_worker_with_packaging()
    ci = compile_instance(model)
    cases = [(ci, dispatch(ci, fifo), sample_scenario(model, sigma=0.4, seed=s, q=1.0)) for s in range(4)]
    cases += [(ONE_WORKER, ROWS, scenario(ONE_WORKER, A_polish=f)) for f in (1.4, 2.0, 3.0)]
    forced = 0
    for case_ci, plan, sc in cases:
        horizon = max(a.end for a in replay(case_ci, plan, sc).schedule)
        for t in range(1, horizon):
            sim = Simulation(case_ci, plan, sc)
            sim.run(until=t)
            snap = sim.snapshot()
            expected = {(f.order_id, f.op_id): f.end for f in snap.frozen}
            result = solve(case_ci, MAKESPAN, time_limit=5, workers=1, snapshot=snap, hint=sim.current_plan())
            assert check_schedule(case_ci, result.schedule, snap) == [], (t, result.status)
            forced += any(a.end > expected[a.order_id, a.op_id] for a in result.schedule
                          if (a.order_id, a.op_id) in expected)
    assert forced > 0


@pytest.mark.parametrize("name", [*MODELS, "one-worker-packaging"])
def test_execute_with_cpsat_rescheduling(name):
    # the planning tool with CP-SAT as planner (trigger: a start deviates by more than 2): every new plan passes
    # update_plan's checker; realized schedules pass up to C2 (durations differ by design)
    model = MODELS.get(name) or one_worker_with_packaging()
    ci = compile_instance(model)
    policy = ReschedulingPolicy(planner=cpsat_planner(time_limit=5), max_shift=2)
    replans = 0
    for seed in range(3):
        sc = sample_scenario(model, sigma=0.4, seed=seed, q=0.5, max_early=5, max_late=5)
        result = execute(ci, dispatch(ci, spt), sc, policy)
        assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}
        replans += sum(d["type"] == "REPLAN" for d in result.decisions)
    assert replans > 0  # CP-SAT plans were handed to the DES
