"""Early-finish trigger (math/05_rescheduling-frozen-part.md section 3, user 2026-11-11).

One machine M1: a1 [0, 10), b1 planned with a gap [20, 30), due 15 (15 minutes late). a1 takes half as long and
ends at 5. The repair keeps b1 at 20 (it has a gap: an earlier blocker does not move it), so no deviation trigger
fires. The early-finish trigger does: a1 ended 5 minutes before its planned end while the plan is still late, and
CP-SAT moves b1 to 5 (on time).
"""

import pytest
from test_des_workers import scenario

from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.objectives import TOTAL_TARDINESS
from simulation.planners.cpsat import cpsat_planner


def instance(due_b):
    return compile_instance(Instance.model_validate({
        "schema_version": "0.6", "name": "early", "machines": ["M1"],
        "orders": [{"id": "A", "operations": [{"id": "a1", "step": "s", "options": {"M1": 10}}]},
                   {"id": "B", "due_date": due_b, "operations": [{"id": "b1", "step": "s", "options": {"M1": 10}}]}]}))


PLAN = [Assignment(order_id="A", op_id="a1", machine="M1", start=0, end=10),
        Assignment(order_id="B", op_id="b1", machine="M1", start=20, end=30)]


def run(ci, early_finish):
    policy = ReschedulingPolicy(cpsat_planner(time_limit=2, objective=TOTAL_TARDINESS), early_finish=early_finish)
    result = execute(ci, PLAN, scenario(ci, A_a1=0.5), policy)
    replans = [d for d in result.decisions if d["type"] == "REPLAN"]
    return next(a.start for a in result.schedule if a.op_id == "b1"), replans


def test_early_finish_lets_cpsat_use_the_gap():
    start, replans = run(instance(15), early_finish=3)
    assert start == 5
    assert [(d["t"], d["triggers"]) for d in replans] == [(5, ["early_finish"])]


@pytest.mark.parametrize(("due_b", "early_finish"), [
    (15, None),  # no trigger configured: the repair keeps b1 at 20
    (15, 6),  # a1 is only 5 minutes early
    (40, 3),  # nothing to gain: the plan is on time (and has no overtime)
])
def test_no_rescheduling_without_the_conditions(due_b, early_finish):
    start, replans = run(instance(due_b), early_finish)
    assert (start, replans) == (20, [])


def test_early_finish_must_be_positive():
    with pytest.raises(ValueError, match="early_finish"):
        ReschedulingPolicy(early_finish=0)


# --- every start is an event for the planning tool (math/13_des.md section 3, user 2026-11-11) --------------------

def test_an_early_start_reaches_the_planning_tool_at_once():
    # X on M1 [0, 10), Y on M2 planned [5, 15) with an early start offset of 3: Y is released and starts at 2. The
    # repair of time point 2 after the start already sees Y running from 2 (a REPAIR record at 2); before, the tool
    # learned about it only at the next event (X's completion at 10)
    ci = compile_instance(Instance.model_validate({
        "schema_version": "0.6", "name": "starts", "machines": ["M1", "M2"],
        "orders": [{"id": "X", "operations": [{"id": "x", "step": "s", "options": {"M1": 10}}]},
                   {"id": "Y", "operations": [{"id": "y", "step": "s", "options": {"M2": 10}}]}]}))
    plan = [Assignment(order_id="X", op_id="x", machine="M1", start=0, end=10),
            Assignment(order_id="Y", op_id="y", machine="M2", start=5, end=15)]
    result = execute(ci, plan, scenario(ci, Y_y=(1.0, -3)), ReschedulingPolicy())
    assert next(a.start for a in result.schedule if a.op_id == "y") == 2
    assert [d["t"] for d in result.decisions if d["type"] == "REPAIR"][0] == 2


def test_start_operations_counts_the_starts():
    from simulation.sim.des import Simulation

    ci = instance(15)
    sim = Simulation(ci, PLAN)
    sim.process_events()
    assert sim.start_operations() == 1  # a1 at 0
    sim.process_events()
    assert sim.start_operations() == 0  # a1 completes at 10, b1 is planned at 20
