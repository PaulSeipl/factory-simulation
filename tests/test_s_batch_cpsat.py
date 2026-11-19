"""CP-SAT forms s-batches (math/08, s-batch spec §7 step 6): slots per step with variable length, one worker share
per slot; on the tiny instances of test_s_batch_format."""

import pytest
from test_s_batch_checker import CI, plan
from test_s_batch_des import rows, scenario
from test_s_batch_format import tiny

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Calendar
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch, spt
from simulation.sim.des import replay


def solved(ci):
    result = solve(ci, time_limit=20, workers=1)
    assert result.status == "OPTIMAL"
    assert check_schedule(ci, result.schedule, breaks=result.breaks) == []
    realized = replay(ci, result.schedule, breaks=result.breaks).schedule  # zero disturbance
    assert rows(realized) == rows(result.schedule) and max(a.end for a in realized) == result.objective
    return result


def test_hand_optimum():
    # both polishings ready at 6: one batch [6, 61) = 5 + 25 + 25, packs after: 81, proven (alone 86)
    result = solved(CI)
    assert (result.objective, result.bound) == (81, 81)
    r = rows(result.schedule)
    assert r["O1", "polish"] == r["O2", "polish"] == (6, 61, "O1/polish")


def test_capacity_keeps_them_apart():
    result = solved(compile_instance(tiny(3, polish={"setup": 5, "capacity": 3})))
    assert result.objective == 86 and {a.batch for a in result.schedule} == {None}


def test_a_batch_on_one_of_two_tools():
    ci = compile_instance(tiny(3, polish_machines=2, polish={"setup": 5}))
    result = solved(ci)
    polish = [a for a in result.schedule if a.op_id == "polish"]
    assert result.objective == 81 and len({a.machine for a in polish}) == 1
    assert {a.batch for a in polish} == {"O1/polish"}


def test_three_plates_by_hand():
    # one plate per order (plate 3), one printer: polishings ready at 6, 11, 16; setup 9 of 30 per polishing.
    # O1 alone [6, 36) (O2 not ready), its pack [36, 46), then O2 + O3 [46, 97) = 9 + 21 + 21, packs to 117.
    # Waiting for all three at 16: 16 + 9 + 3 * 21 + 3 * 10 = 118; all alone: 6 + 3 * 30 + 3 * 10 = 126
    ci = compile_instance(tiny(3, orders=3, plate=3, polish={"setup": 9}))
    result = solved(ci)
    assert (result.objective, result.bound) == (117, 117)
    r = rows(result.schedule)
    assert r["O1", "polish"] == (6, 36, None) and r["O2", "polish"] == r["O3", "polish"] == (46, 97, "O2/polish")
    assert max(a.end for a in dispatch(ci, spt)) == 117  # the rule finds it too


def test_with_a_calendar():
    # t = 0 is Monday 08:00, a break owed: the batch lies in the shift, the plan passes C13 and C14
    solved(compile_instance(tiny(3, polish={"setup": 5}).model_copy(update={"calendar": Calendar()})))


@pytest.mark.parametrize("factor", [0.6, 1.0, 1.5])
def test_rescheduling_forms_the_batch(factor):
    # start from the singleton plan; CP-SAT replans every minute from t = 1: it forms the batch itself, and every
    # plan, also those made while the batch runs (frozen, its id kept), passes the checker against its snapshot
    singletons = plan(**{"O1/polish": (None, 6, 36, ("A",), None), "O1/pack": (None, 36, 46, ("A",), None),
                         "O2/polish": (None, 46, 76, ("A",), None), "O2/pack": (None, 76, 86, ("A",), None)})
    disturbed = scenario(CI, factor={"R1/print": factor, "O1/polish": 1.3})
    result = execute(CI, singletons, disturbed, ReschedulingPolicy(planner=cpsat_planner(time_limit=5), period=1))
    r = rows(result.schedule)
    assert r["O1", "polish"][2] == r["O2", "polish"][2] == "O1/polish"
    assert {v.constraint for v in check_schedule(CI, result.schedule)} <= {"C2"}


def test_the_hint_caps_the_horizon_and_its_batches_are_hinted():
    # makespan with a hint: the horizon is the hint's end (math/12); the rule plan (81, one batch) is optimal, so the
    # capped model proves 81. Three plates: the rule's batch O2 + O3 hinted into O2's slot, optimum 117 again
    assert solve(CI, time_limit=20, workers=1, hint=dispatch(CI, spt)).objective == 81
    ci = compile_instance(tiny(3, orders=3, plate=3, polish={"setup": 9}))
    result = solve(ci, time_limit=20, workers=1, hint=dispatch(ci, spt))
    assert (result.status, result.objective) == ("OPTIMAL", 117)


def test_an_infeasible_hint_falls_back_to_the_full_horizon():
    # a hint ending at 70 (no plan does): the capped model is infeasible, the full one finds 81
    short = [a.model_copy(update={"end": min(a.end, 70), "start": min(a.start, 69)}) for a in plan()]
    result = solve(CI, time_limit=20, workers=1, hint=short)
    assert (result.status, result.objective) == ("OPTIMAL", 81)
