"""Breaks between planner, planning tool and DES (plan docs/superpowers/plans/2026-11-08-breaks-rescheduling.md,
Task 3): planners return a Plan (assignments, breaks), `Simulation.update_plan(plan, breaks)` keeps the taken breaks
and replaces the pending ones, `execute` runs with the start plan's breaks and reports the realized ones.

toy-workers with its calendar and the hand plan of tests/test_workers_checker.py (12:00 is t = 240, 13:00 t = 300);
Gegenbetten slowed to factor 20/3 keeps A on its prefix until 12:20 (260).
"""

import pytest
from test_des_workers import scenario
from test_snapshot_breaks import frozen_rows
from test_worker_compile import CARRIERS
from test_workers_checker import BREAKS, CI, plan

from simulation.control.rescheduling import execute
from simulation.model.schedule import Assignment, Break, Plan
from simulation.planners.dispatching import dispatch, dispatch_planner, spt
from simulation.sim.des import PlanNotExecutable, Simulation

SLOW = scenario(CI, k1_gb=20 / 3)
A_260, B_240 = Break(worker="A", start=260), Break(worker="B", start=240)


def sim_at(t):
    sim = Simulation(CI, plan(), SLOW, BREAKS)
    sim.run(until=t)
    return sim


def revised(snap):
    """The frozen part plus k1 packaging by B at [300, 320), after B's break."""
    return [*frozen_rows(snap), Assignment(order_id="k1", op_id="pack", machine=None, start=300, end=320,
                                           workers=("B",))]


def test_execute_runs_with_the_breaks_and_reports_the_realized_ones():
    result = execute(CI, plan(), SLOW, breaks=BREAKS)
    assert result.breaks == (A_260, B_240)  # A postponed to 12:20 by its prefix, B at 12:00


def test_current_breaks_show_taken_breaks_with_their_realized_start():
    assert sim_at(250).current_breaks() == (Break(worker="A", start=240), B_240)  # A's break due, not taken yet
    assert sim_at(270).current_breaks() == (A_260, B_240)


def test_update_plan_replaces_a_pending_break_and_keeps_a_taken_one():
    # at 12:10: B took its break, A's is due but A is busy; the new plan sets A's break to 12:20
    sim = sim_at(250)
    snap = sim.snapshot()
    sim.update_plan(revised(snap), (A_260, B_240))
    assert sim.current_breaks() == (B_240, A_260)  # taken first, then the new pending ones
    sim.run()
    assert sim.realized_breaks() == (B_240, A_260)
    # planned at 13:00, but Gegenbetten really ends at 320 (prefix until 260, rest 60): packaging by B at 320
    assert next(a for a in sim.realized() if a.order_id == "k1" and a.op_id == "pack").start == 320


def test_update_plan_rejects_a_moved_taken_break():
    sim = sim_at(270)
    with pytest.raises(PlanNotExecutable, match="C7"):
        sim.update_plan(revised(sim.snapshot()), (Break(worker="A", start=275), B_240))


def test_update_plan_without_breaks_keeps_the_current_ones():
    sim = sim_at(270)
    sim.update_plan(revised(sim.snapshot()))
    assert sim.current_breaks() == (A_260, B_240)


def test_dispatch_planner_returns_a_plan_with_its_breaks():
    sim = Simulation(CARRIERS, dispatch(CARRIERS, spt))
    sim.run(until=3)
    result = dispatch_planner(spt)(CARRIERS, sim.snapshot(), sim.current_plan())
    assert isinstance(result, Plan) and result.breaks == ()  # no calendar: no breaks
    assert result.assignments == dispatch(CARRIERS, spt, snapshot=sim.snapshot())
