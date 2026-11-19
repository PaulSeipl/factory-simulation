"""Checker C15 for s-batches (math/08, s-batch spec §7 step 3), on the tiny instance of test_s_batch_format: two
orders O1, O2 on one plate C1 (print [0,5), saw [5,6)), each with 3 primary parts; polish (setup 5 inside its 30)
and pack (10) by worker A without machine."""

import re

import pytest
from test_s_batch_format import tiny

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.schedule import Assignment

CI = compile_instance(tiny(3, polish={"setup": 5}))


def plan(**changes) -> list[Assignment]:
    """By hand: one s-batch b1 of both polishings [6, 61) = 5 + 25 + 25 (instead of 30 + 30), then pack O1 [61,71),
    O2 [71,81): makespan 81 against 86 with singletons."""
    rows = {"R1/print": ("print1", 0, 5, (), None), "C1/saw": ("saw1", 5, 6, (), None),
            "O1/polish": (None, 6, 61, ("A",), "b1"), "O2/polish": (None, 6, 61, ("A",), "b1"),
            "O1/pack": (None, 61, 71, ("A",), None), "O2/pack": (None, 71, 81, ("A",), None)} | changes
    return [Assignment(order_id=k.split("/")[0], op_id=k.split("/")[1], machine=m, start=s, end=e, workers=w, batch=b)
            for k, (m, s, e, w, b) in rows.items()]


def test_compiled_s_batch_fields():
    by_key = {key: o for o, key in enumerate(CI.op_keys)}
    polish, pack = by_key["O1", "polish"], by_key["O1", "pack"]
    assert (CI.s_setup[polish], CI.s_capacity[polish], CI.units[polish]) == (5, None, 3)
    assert (CI.s_setup[pack], CI.units[pack]) == (None, 1)


def test_hand_batch_is_feasible():
    assert check_schedule(CI, plan()) == []


def test_singletons_without_batch_id_pay_the_full_setup():
    # today's plan: polish O1 [6,36), O2 [46,76): no batch id, each its own 30
    assert check_schedule(CI, plan(**{"O1/polish": (None, 6, 36, ("A",), None),
                                      "O1/pack": (None, 36, 46, ("A",), None),
                                      "O2/polish": (None, 46, 76, ("A",), None),
                                      "O2/pack": (None, 76, 86, ("A",), None)})) == []


def test_a_singleton_batch_lasts_its_own_duration():
    changes = {"O2/polish": (None, 61, 91, ("A",), "b2"), "O1/polish": (None, 6, 36, ("A",), "b1"),
               "O1/pack": (None, 36, 46, ("A",), None), "O2/pack": (None, 91, 101, ("A",), None)}
    assert check_schedule(CI, plan(**changes)) == []


@pytest.mark.parametrize(("changes", "constraint", "message"), [
    ({"O2/polish": (None, 6, 66, ("A",), "b1")}, "C15", r"batch b1: members with different ends"),
    # the batch's length is its C2 (a realized schedule deviates there, like any duration)
    ({"O1/polish": (None, 6, 60, ("A",), "b1"), "O2/polish": (None, 6, 60, ("A",), "b1")}, "C2",
     r"batch b1: end - start = 54, p = 55 \(setup 5 once\)"),
    ({"O1/pack": (None, 61, 71, ("A",), "b1")}, "C15",
     r"O1', 'pack'\) in batch b1, but its step pack is no s-batch step"),
])
def test_invalid_batches_rejected(changes, constraint, message):
    violations = check_schedule(CI, plan(**changes))
    assert any(v.constraint == constraint and re.search(message, v.message) for v in violations), violations


def test_members_with_different_workers_rejected():
    ci = compile_instance(tiny(3, polish={"setup": 5}).model_copy(update={"workers": ("A", "B")}))
    violations = check_schedule(ci, plan(**{"O2/polish": (None, 6, 61, ("B",), "b1")}))
    assert "batch b1: members with different workers [('A',), ('B',)]" in {v.message for v in violations}


def test_capacity_in_units():
    # capacity 3 parts: each polishing covers 3, together 6
    ci = compile_instance(tiny(3, polish={"setup": 5, "capacity": 3}))
    assert [v.message for v in check_schedule(ci, plan())] == ["batch b1: 6 units, capacity 3"]


def test_the_worker_counts_a_batch_once_and_not_twice():
    # without the batch the two polishings would overlap on A (C12); a pack inside the batch does (C12)
    assert not [v for v in check_schedule(CI, plan()) if v.constraint == "C12"]
    clash = plan(**{"O1/pack": (None, 50, 60, ("A",), None)})
    assert "C12" in {v.constraint for v in check_schedule(CI, clash)}


def test_a_batch_on_a_machine_occupies_it_once():
    # polishing on a tracked tool (user 2026-11-18): both members on polish1 [6,61) are one interval, not a C5 overlap
    ci = compile_instance(tiny(3, polish_machines=2, polish={"setup": 5}))
    on = {"O1/polish": ("polish1", 6, 61, ("A",), "b1"), "O2/polish": ("polish1", 6, 61, ("A",), "b1")}
    assert check_schedule(ci, plan(**on)) == []
    split = on | {"O2/polish": ("polish2", 6, 61, ("A",), "b1")}
    assert "batch b1: members with different machines ['polish1', 'polish2']" in {
        v.message for v in check_schedule(ci, plan(**split))}
