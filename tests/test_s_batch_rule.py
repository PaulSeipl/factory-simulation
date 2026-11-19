"""The dispatching rule forms s-batches (math/08, s-batch spec §7 step 5): greedy join of the ready operations of
the chosen operation's step while units and the worker's shift allow; on the tiny instance of test_s_batch_format."""

import pytest
from test_s_batch_checker import CI
from test_s_batch_des import rows, scenario
from test_s_batch_format import tiny

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Calendar
from simulation.planners.dispatching import (
    ASSIGNMENT_RULES,
    SEQUENCING_RULES,
    dispatch,
    dispatch_plan,
    dispatch_planner,
    ect,
    spt,
)
from simulation.sim.des import replay


@pytest.mark.parametrize("rule", [(s, a) for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None]],
                         ids=lambda r: f"{r[0]}-{r[1] or 'joint'}")
def test_every_rule_forms_the_hand_batch(rule):
    # both polishings are ready at 6 on worker A: one batch [6, 61) = 5 + 25 + 25, packs after: makespan 81 (86 alone)
    plan = dispatch(CI, SEQUENCING_RULES[rule[0]], ASSIGNMENT_RULES[rule[1]] if rule[1] else None)
    r = rows(plan)
    assert r["O1", "polish"] == r["O2", "polish"] == (6, 61, "O1/polish")
    assert max(a.end for a in plan) == 81
    assert check_schedule(CI, plan) == []
    assert rows(replay(CI, plan).schedule) == r  # zero disturbance


def test_capacity_keeps_them_apart():
    # capacity 3 parts, each polishing covers 3: no join, singletons pay their setup: makespan 86
    ci = compile_instance(tiny(3, polish={"setup": 5, "capacity": 3}))
    plan = dispatch(ci, spt, ect)
    assert {a.batch for a in plan} == {None} and max(a.end for a in plan) == 86
    assert check_schedule(ci, plan) == []


def test_a_batch_that_does_not_fit_the_shift_is_not_formed():
    # t = 0 is Monday 16:44 (origin 1004): the polishings are ready at 6 = 16:50; one (30) ends 17:20, within the shift
    # (17:30), the batch (55) would end 17:45, so the rule plans singletons
    ci = compile_instance(tiny(3, polish={"setup": 5}).model_copy(update={"calendar": Calendar(origin=1004)}))
    plan = dispatch_plan(ci, spt, ect)
    r = rows(plan.assignments)
    assert r["O1", "polish"] == (6, 36, None) and r["O2", "polish"][2] is None
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []


def test_rule_on_a_machine():
    # two polishing tools. Joint (machine chosen at dispatch): both join on one tool. With ECT the machine is fixed
    # when an operation becomes ready (O1 polish1, O2 polish2, balancing load), so they cannot join: the assignment
    # rule decides before batching, as for the oven (a limit of the rule, math/08 section 6)
    ci = compile_instance(tiny(3, polish_machines=2, polish={"setup": 5}))
    joint = dispatch(ci, spt)
    r = rows(joint)
    assert r["O1", "polish"] == r["O2", "polish"] == (6, 61, "O1/polish")
    assert len({a.machine for a in joint if a.op_id == "polish"}) == 1
    assert check_schedule(ci, joint) == []
    apart = dispatch(ci, spt, ect)
    assert {a.batch for a in apart} == {None} and check_schedule(ci, apart) == []


@pytest.mark.parametrize("seed_factor", [0.6, 1.0, 1.5])
def test_rescheduling_with_the_rule_keeps_batch_ids_apart(seed_factor):
    # replanned every minute from the rule's own start plan: a started batch stays frozen with its id, new batches
    # take their first member's key, so C15 never merges two batches
    start = dispatch(CI, spt, ect)
    disturbed = scenario(CI, factor={"R1/print": seed_factor, "O1/polish": 1.3, "O2/pack": 0.7})
    result = execute(CI, start, disturbed, ReschedulingPolicy(planner=dispatch_planner(spt, ect), period=1))
    assert {v.constraint for v in check_schedule(CI, result.schedule)} <= {"C2"}
    r = rows(result.schedule)
    assert r["O1", "polish"][2] == r["O2", "polish"][2] == "O1/polish"


def test_a_batch_longer_than_a_shift_part_is_not_formed():
    # 15 parts: polishing 150 each, a batch 5 + 145 + 145 = 295 > 270 (13:00-17:30), the longest part the rule may use
    # (no overtime): singletons, no error (before: free_from raised for the batch's share)
    ci = compile_instance(tiny(15, plate=30, polish={"setup": 5}).model_copy(update={"calendar": Calendar()}))
    plan = dispatch_plan(ci, spt, ect)
    assert {a.batch for a in plan.assignments} == {None}
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
