"""Snapshot with workers (math/13_des.md §6) and worker metrics (math/23_metrics.md), by hand."""

from test_des_swap import run
from test_des_workers import by_key, polish_instance, scenario
from test_worker_compile import CARRIERS
from test_workers_checker import BREAKS, CI, carrier_plan, plan

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ExecutionResult
from simulation.metrics import run_metrics
from simulation.model.schedule import Assignment
from simulation.sim.des import Simulation, replay


def frozen_at(ci, rows, t, sc=None, breaks=()):
    sim = Simulation(ci, rows, sc, breaks)
    sim.run(until=t)
    return sim, {(f.order_id, f.op_id): f for f in sim.snapshot().frozen}


def test_running_oven_shows_its_removal_as_not_started():
    # t = 6: oven batch [4, 9) running, loading by W1 done, removal by W1 not started yet
    _, frozen = frozen_at(CARRIERS, carrier_plan(), 6)
    f = frozen["L1", "oven"]
    assert (f.machine, f.start, f.end, f.running, f.workers) == ("O", 4, 9, True, ("W1", None))
    assert frozen["L2", "oven"].workers == ("W1", None)


def test_machine_less_operation_expected_end_from_the_plan():
    # Gegenbetten [60, 150) running at t = 70; its work takes twice as long (factor 2), but the snapshot expects
    # the planned end 150 (no leakage)
    _, frozen = frozen_at(CI, plan(), 70, scenario(CI, k1_gb=2.0), BREAKS)
    f = frozen["k1", "gb"]
    assert (f.machine, f.start, f.end, f.running, f.workers) == (None, 60, 150, True, ("A",))


def test_snapshot_shows_the_actual_worker_after_a_swap():
    _, frozen = frozen_at(CI, plan(k2_pack=(None, 100, 120, ("A",))), 105, scenario(CI, k1_gb=2.0), BREAKS)
    assert frozen["k2", "pack"].workers == ("B",)


def test_c7_keeps_started_shares_and_frees_the_pending_removal():
    sim, _ = frozen_at(CARRIERS, carrier_plan(), 6)
    snap = sim.snapshot()
    current = sim.current_plan()
    assert check_schedule(CARRIERS, current, snap) == []
    other_loader = [a.model_copy(update={"workers": ("W2", "W1")}) if a.op_id == "oven" else a for a in current]
    assert {v.constraint for v in check_schedule(CARRIERS, other_loader, snap)} == {"C7"}
    other_remover = [a.model_copy(update={"workers": ("W1", "W2")}) if a.op_id == "oven" else a for a in current]
    assert check_schedule(CARRIERS, other_remover, snap) == []


def metrics(ci, rows, result):
    return run_metrics(ci, rows, ExecutionResult(result.schedule, result.log, breaks=result.breaks))


def test_overtime_and_overrun_by_hand():
    # k1 packaging [660, 700): 19:00 to 19:40, shift end 17:30 = 570 -> overtime 130, past 19:30 -> 1 overrun
    rows = plan()
    m = metrics(CI, rows, replay(CI, rows, scenario(CI, k1_pack=(2.0, 510)), BREAKS))
    assert (m["overtime"], m["overruns"]) == (130, 1)


def test_break_postponement_and_spread_by_hand():
    # A's break at 12:20 (260), B's at 12:00: postponement 20, spread 20 (one day)
    rows = plan()
    m = metrics(CI, rows, replay(CI, rows, scenario(CI, k1_gb=20 / 3), BREAKS))
    assert (m["break_postponement"], m["break_spread"], m["overtime"]) == (20, 20, 0)


def test_swaps_and_overstay_by_hand():
    rows = plan(k2_pack=(None, 100, 120, ("A",)))
    assert metrics(CI, rows, run(rows, k1_gb=2.0))["swaps"] == 1
    ci = polish_instance(("W1",), polish=3)
    one_worker = [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e, workers=w) for o, j, m, s, e, w in [
        ("L1", "print", "P", 0, 2, ()), ("L2", "print", "P", 2, 4, ()),
        ("L1", "oven", "O", 4, 9, ("W1", "W1")), ("L2", "oven", "O", 4, 9, ("W1", "W1")),
        ("A", "polish", None, 5, 8, ("W1",)),
        ("L1", "mill/setup", "M", 9, 10, ("W1",)), ("L1", "mill", "M", 10, 14, ()),
        ("L1", "mill/removal", "M", 14, 15, ("W1",)),
        ("L2", "mill/setup", "M", 15, 16, ("W1",)), ("L2", "mill", "M", 16, 20, ()),
        ("L2", "mill/removal", "M", 20, 21, ("W1",)),
    ]]
    m = metrics(ci, one_worker, replay(ci, one_worker, scenario(ci, A_polish=2.0)))
    assert (m["overstay"], m["swaps"]) == (3, 0) and "overtime" not in m  # no calendar: no shift metrics


def test_plan_metrics_without_disturbance_are_zero():
    rows = plan()
    m = metrics(CI, rows, replay(CI, rows, breaks=BREAKS))
    assert {k: m[k] for k in ("overtime", "overruns", "break_postponement", "break_spread", "overstay", "swaps")} == \
        dict.fromkeys(("overtime", "overruns", "break_postponement", "break_spread", "overstay", "swaps"), 0)
    assert by_key(replay(CI, rows, breaks=BREAKS).schedule) == by_key(rows)
