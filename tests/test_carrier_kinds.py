"""Several carrier kinds per order (math/03_loads.md, G1/G2): primary parts of several orders on one blank,
secondary parts on build plates; QM of a plate waits for the polished primary parts of its orders only."""

import pytest
from pydantic import ValidationError

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch
from simulation.sim.des import replay


def order(k: str) -> dict:
    return {"id": k, "parts": [{"id": "p", "type": "primary", "times": {"mill": 2}}, {"id": "s", "type": "secondary"}],
            "operations": [
                {"id": "design", "step": "design", "options": {"D": 1}},
                {"id": "mill", "step": "mill", "scope": "carrier", "carries": "primary", "role": "form",
                 "predecessors": ["design"]},
                {"id": "separate", "step": "separate", "scope": "carrier", "carries": "primary", "role": "separate",
                 "predecessors": ["mill"]},
                {"id": "polish", "step": "polish", "scope": "primary", "options": {"W": 1},
                 "predecessors": ["separate"]},
                {"id": "print", "step": "print", "scope": "carrier", "carries": "secondary", "role": "form",
                 "predecessors": ["design"]},
                {"id": "qm", "step": "qm", "scope": "carrier", "carries": "secondary",
                 "predecessors": ["print", "polish"]},
                {"id": "saw", "step": "saw", "scope": "carrier", "carries": "secondary", "role": "separate",
                 "predecessors": ["qm"]},
            ]}


def data() -> dict:
    """Blank K1 holds the primary parts of A and B (mill per blank: setup 1, main 2 + 2, removal 1); plates L1, L2."""
    return {
        "schema_version": "0.6", "name": "carrier-kinds", "machines": ["D", "P", "M", "W", "Q", "S"],
        "carrier_steps": {
            "mill": {"options": {"M": 9}, "runs": "per_carrier", "setup": 1, "removal": 1,
                     "estimator": {"fixed": 0, "share": 1}},
            "separate": {"options": {"W": 1}},
            "print": {"options": {"P": 2}},
            "qm": {"options": {"Q": 1}},
            "saw": {"options": {"S": 1}},
        },
        "orders": [order("A"), order("B")],
        "carriers": [{"id": "K1", "parts": [["A", "p"], ["B", "p"]]},
                     {"id": "L1", "parts": [["A", "s"]]}, {"id": "L2", "parts": [["B", "s"]]}],
    }


CI = compile_instance(Instance.model_validate(data()))


def preds(key):
    return {CI.op_keys[p] for p in CI.predecessors[CI.op_index[key]]}


def by_key(plan):
    return {(a.order_id, a.op_id): (a.machine, a.start, a.end) for a in plan}


def test_synchronization_across_carrier_kinds():
    assert preds(("K1", "mill/setup")) == {("A", "design"), ("B", "design")}  # the blank waits for both designs
    assert preds(("K1", "separate")) == {("K1", "mill/removal")}
    assert preds(("A", "polish")) == {("K1", "separate")}  # only the blank, not the plate
    assert preds(("L1", "qm")) == {("L1", "print"), ("A", "polish")}  # only its own order's primary parts
    assert preds(("L1", "print")) == {("A", "design")}
    assert dict(CI.options[CI.op_index["K1", "mill"]]) == {CI.machine_index["M"]: 4}
    assert {CI.order_ids[k] for k in CI.op_orders[CI.op_index["K1", "separate"]]} == {"A", "B"}


def test_cpsat_optimum_by_hand():
    # Lower bound 13: the blank needs both designs (>= 2) and its run of 6, separation ends >= 9, the second
    # polishing on W >= 11, its QM >= 12, its saw >= 13. Reached e.g. by designs A [0,1) B [1,2), blank run [2,8),
    # separation [8,9), polishing [9,10) [10,11), QM [10,11) [11,12), saws [11,12) [12,13).
    result = solve(CI, time_limit=10, workers=1)
    assert (result.status, result.objective, result.bound) == ("OPTIMAL", 13, 13)
    assert check_schedule(CI, result.schedule) == []
    assert by_key(replay(CI, result.schedule).schedule) == by_key(result.schedule)  # zero-disturbance


@pytest.mark.parametrize("seq", sorted(SEQUENCING_RULES))
@pytest.mark.parametrize("assign", sorted(ASSIGNMENT_RULES))
def test_every_rule_is_feasible_and_replays_unchanged(seq, assign):
    plan = dispatch(CI, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[assign])
    assert check_schedule(CI, plan) == []
    assert by_key(replay(CI, plan).schedule) == by_key(plan)


def test_checker_finds_qm_before_the_polished_primary_part():
    plan = {(a.order_id, a.op_id): a for a in solve(CI, time_limit=10, workers=1).schedule}
    qm = plan["L1", "qm"]
    plan["L1", "qm"] = qm.model_copy(update={"start": plan["A", "polish"].end - 1, "end": plan["A", "polish"].end})
    assert "C3" in {v.constraint for v in check_schedule(CI, list(plan.values()))}


def ops_of(d, k):
    return {op["id"]: op for op in next(o for o in d["orders"] if o["id"] == k)["operations"]}


def drop_blank_chain(d, k):
    o = next(o for o in d["orders"] if o["id"] == k)
    o["operations"] = [op for op in o["operations"] if op["id"] not in ("mill", "separate")]
    ops_of(d, k)["polish"]["predecessors"] = ["design"]


def m_mixed_carrier(d):
    d["carriers"][0]["parts"] = [["A", "p"]]
    d["carriers"][2]["parts"] = [["B", "s"], ["B", "p"]]


def m_unknown_kind(d):
    ops_of(d, "A")["print"]["carries"] = "tertiary"


def m_carries_on_order_operation(d):
    ops_of(d, "A")["polish"]["carries"] = "primary"


def m_named_and_unnamed(d):
    del ops_of(d, "A")["print"]["carries"]


def m_unnamed_with_two_kinds(d):
    drop_blank_chain(d, "A")
    for op in ops_of(d, "A").values():
        op.pop("carries", None)


def m_kind_without_chain(d):
    drop_blank_chain(d, "A")


def m_chain_without_carried_parts(d):
    d["carriers"][0]["parts"] = [["B", "p"]]


@pytest.mark.parametrize(("mutate", "message"), [
    (m_mixed_carrier, r"carrier L2: parts of different types \['primary', 'secondary'\]"),
    (m_unknown_kind, r"order A, op print: carries unknown part type 'tertiary'"),
    (m_carries_on_order_operation, r"order A, op polish: carries only for carrier operations"),
    (m_named_and_unnamed, r"order A: with several carrier kinds every carrier operation names the part type"),
    (m_unnamed_with_two_kinds, r"order A: parts of types \['primary', 'secondary'\] on carriers, so every carrier "
                               r"operation must name"),
    (m_kind_without_chain, r"order A has parts on carriers but no carrier operations for primary"),
    (m_chain_without_carried_parts, r"order A has carrier operations for primary but no part on a carrier"),
], ids=lambda v: v.__name__ if callable(v) else None)
def test_invalid_kinds_rejected(mutate, message):
    d = data()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)
