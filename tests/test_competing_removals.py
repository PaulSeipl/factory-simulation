"""Two pending oven removals that compete for the only free worker (math/04_workers.md (C7^o), user 2026-11-11).

Two ovens with loading (1) and removal (2) by a worker: X on O1 [0, 10) (W1 loads and removes), Y on O2 [0, 12)
(W2 loads, W1 removes). W1 packs Z1 [1, 7), W2 packs Z2 [1, 20). Z1 takes three times as long, so at t = 10 W1 is
still packing (expected end 11), W2 is busy until 20, and both removals are pending (X due at 8, Y at 10): each can
start at 11 at the earliest, both with W1. C7^o books them one at a time: the one with the earliest possible start
first, ties by the earliest due date (Y, due 20, before X, due 30), then by operation index. So Y is removed
[11, 13) and X [13, 15), both by W1. The checker takes the plan's order: X first ([11, 13), then Y [13, 15)) passes
as well; both at 11 does not (C12). Before this rule each removal was computed on its own and both were required at
11: no plan passed.
"""

import pytest
from test_des_workers import scenario
from test_dispatching_workers import by_key, snap_at

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch_plan, dispatch_planner, spt
from simulation.planners.repair import forced_removals, repair_plan

OVEN = {"step": "oven", "worker": {"prefix": 1, "suffix": 2}}
PACK = {"step": "pack", "worker": {"whole": True}}
CI = compile_instance(Instance.model_validate({
    "schema_version": "0.6", "name": "competing-removals", "machines": ["O1", "O2"], "workers": ["W1", "W2"],
    "orders": [
        {"id": "X", "due_date": 30, "operations": [{"id": "oven", "options": {"O1": 10}, **OVEN}]},
        {"id": "Y", "due_date": 20, "operations": [{"id": "oven", "options": {"O2": 12}, **OVEN}]},
        {"id": "Z1", "operations": [{"id": "pack", "duration": 6, **PACK}]},
        {"id": "Z2", "operations": [{"id": "pack", "duration": 19, **PACK}]},
    ]}))
PLAN = [Assignment(order_id="X", op_id="oven", machine="O1", start=0, end=10, workers=("W1", "W1")),
        Assignment(order_id="Y", op_id="oven", machine="O2", start=0, end=12, workers=("W2", "W1")),
        Assignment(order_id="Z1", op_id="pack", machine=None, start=1, end=7, workers=("W1",)),
        Assignment(order_id="Z2", op_id="pack", machine=None, start=1, end=20, workers=("W2",))]
SLOW_PACK = scenario(CI, Z1_pack=3.0)


def at_10():
    return snap_at(CI, PLAN, 10, SLOW_PACK)


def removals(plan):
    got = by_key(plan)
    return got["X", "oven"][2:], got["Y", "oven"][2:]  # (end, workers)


def test_snapshot_has_two_pending_removals_and_one_worker_soon_free():
    frozen = {f.order_id: f for f in at_10().frozen}
    assert (frozen["X"].workers, frozen["Y"].workers) == (("W1", None), ("W2", None))
    assert (frozen["Z1"].end, frozen["Z2"].end) == (11, 20)


def test_forced_removals_books_the_earlier_due_order_first():
    # op indices: X oven 0, Y oven 1; worker indices W1 0, W2 1
    assert forced_removals(CI, at_10()) == {1: (1, 11, [0], 0), 0: (1, 13, [0], 0)}


def test_checker_takes_the_plans_order():
    snap = at_10()
    packs = [Assignment(order_id=f.order_id, op_id=f.op_id, machine=None, start=f.start, end=f.end, workers=f.workers)
             for f in snap.frozen if f.order_id.startswith("Z")]

    def plan(x_end, y_end):
        return packs + [Assignment(order_id="X", op_id="oven", machine="O1", start=0, end=x_end, workers=("W1", "W1")),
                        Assignment(order_id="Y", op_id="oven", machine="O2", start=0, end=y_end, workers=("W2", "W1"))]

    assert check_schedule(CI, plan(15, 13), snap) == []  # Y first (the planners' order)
    assert check_schedule(CI, plan(13, 15), snap) == []  # X first: another allowed order
    assert {v.constraint for v in check_schedule(CI, plan(13, 13), snap)} == {"C7", "C12"}  # both at 11
    assert {v.constraint for v in check_schedule(CI, plan(16, 13), snap)} == {"C7"}  # X delayed on its own


@pytest.mark.parametrize("planner", ["repair", "rule", "cpsat"])
def test_planners_book_y_first(planner):
    snap = at_10()
    if planner == "repair":
        new = repair_plan(CI, snap, PLAN).assignments
    elif planner == "rule":
        new = dispatch_plan(CI, spt, snapshot=snap).assignments
    else:
        result = solve(CI, time_limit=5, workers=1, snapshot=snap)
        assert result.status == "OPTIMAL"
        new = result.schedule
    assert check_schedule(CI, new, snap) == []
    assert removals(new) == ((15, ("W1", "W1")), (13, ("W2", "W1")))


@pytest.mark.parametrize("policy", [ReschedulingPolicy(),
                                    ReschedulingPolicy(dispatch_planner(spt), period=1),
                                    ReschedulingPolicy(cpsat_planner(time_limit=2), period=1)])
def test_execute_finishes_with_every_policy(policy):
    result = execute(CI, PLAN, SLOW_PACK, policy)
    # every adapted plan passed update_plan's checker; with repair only the removals wait (rescheduling from t = 1
    # may plan around the slow packing)
    assert {v.constraint for v in check_schedule(CI, result.schedule)} <= {"C2"}
    if policy.planner is None:
        assert sum(r["minutes"] for r in result.log if r["type"] == "OVERSTAY") > 0


def test_snapshot_expects_a_late_started_removal_to_its_own_end():
    # repair only: W1 packs until 19 (realized), then starts X's removal (due since 8) at 19: it runs [19, 21). The
    # snapshot at 19 expects X's end at 21, not at max(start + p, t + 1) = 20 (W1 would seem free at 20)
    sim_t = 19
    frozen = {f.order_id: f for f in snap_at(CI, PLAN, sim_t, SLOW_PACK).frozen}
    assert (frozen["X"].end, frozen["X"].workers, frozen["X"].running) == (21, ("W1", "W1"), True)
