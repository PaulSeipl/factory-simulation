"""Format of s-batches across orders (math/08, s-batch spec §7 step 2): `Instance.s_batch_steps`, validation V23,
`Assignment.batch`, generator pass-through. Small toy instances only."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.model.instance import Calendar, Instance, longest_share, units
from simulation.model.schedule import Assignment

DATA = Path(__file__).parents[1] / "data"


def workers(**s_batch_steps) -> dict:
    """toy-workers: pack of k1 and k2 without machine, whole share, 20 minutes each."""
    d = json.loads((DATA / "instances" / "toy-workers.json").read_text(encoding="utf-8"))
    return d | ({"s_batch_steps": s_batch_steps} if s_batch_steps else {})


def carriers(**s_batch_steps) -> dict:
    """toy-carriers with qm as a worker-only carrier step (3 minutes, whole share) and one worker."""
    d = json.loads((DATA / "instances" / "toy-carriers.json").read_text(encoding="utf-8"))
    d["workers"] = ["A"]
    d["carrier_steps"]["qm"] = {"duration": 3, "worker": {"whole": True}}
    d["machines"] = [m for m in d["machines"] if m != "Q"]
    return d | {"s_batch_steps": s_batch_steps}


def test_order_and_carrier_steps_accepted():
    inst = Instance.model_validate(workers(pack={"setup": 10}))
    assert inst.s_batch_steps["pack"].setup == 10 and inst.s_batch_steps["pack"].capacity is None
    assert Instance.model_validate(carriers(qm={"setup": 1, "capacity": 4})).s_batch_steps["qm"].capacity == 4


def test_machine_bound_steps_accepted():
    # user 2026-11-18: a machine without worker (saw on S, 1 min), or a machine with one whole share (qm on Q)
    assert Instance.model_validate(carriers(saw={"setup": 0})).s_batch_steps["saw"].setup == 0
    d = carriers(qm={"setup": 1})
    d["machines"] += ["Q"]
    d["carrier_steps"]["qm"] = {"options": {"Q": 3}, "worker": {"whole": True}}
    assert Instance.model_validate(d).s_batch_steps["qm"].setup == 1


def test_left_out_when_empty_or_default():
    # instance files and digests from before stay unchanged
    assert "s_batch_steps" not in Instance.model_validate(workers()).model_dump()
    assert Instance.model_validate(workers(pack={"setup": 10})).model_dump()["s_batch_steps"] == {"pack": {"setup": 10}}
    a = Assignment(order_id="k1", op_id="pack", machine=None, start=0, end=20)
    assert "batch" not in a.model_dump() and a.model_copy(update={"batch": "b1"}).model_dump()["batch"] == "b1"


def test_longest_share_by_hand():
    # default calendar: before the break 780 - 480 = 300; after it 1050 + 120 - min(780, 720 + 60) = 390
    assert longest_share(Calendar()) == 390
    assert longest_share(Calendar(max_overtime=0, break_latest=800, break_length=30)) == max(800 - 480, 1050 - 750)


@pytest.mark.parametrize(("data", "message"), [
    (workers(nope={"setup": 1}), r"\[V23\] s-batch step nope: no operation of this step"),
    # a prefix share (print on P, gegenbetten without machine): unattended time makes it a run, not an s-batch
    (workers(print={"setup": 1}), r"\[V23\] s-batch step print: needs operations with one whole worker share, or a "
                                  r"machine without worker"),
    (workers(gegenbetten={"setup": 1}), r"\[V23\] s-batch step gegenbetten: needs operations with one whole worker"),
    (workers(pack={"setup": 20}), r"\[V23\] s-batch step pack: setup 20 not shorter than an operation \(20\)"),
    (carriers(print={"setup": 1}), r"\[V23\] s-batch step print: a run step or p-batch step"),
    (carriers(oven={"setup": 1}) | {"carrier_steps": carriers()["carrier_steps"] | {
        "oven": {"options": {"O": 3}, "batch_capacity": 2}}}, r"\[V23\] s-batch step oven: a run step or p-batch"),
    (carriers(saw={"setup": 1}), r"\[V23\] s-batch step saw: setup 1 not shorter than an operation \(1\)"),
    (workers(pack={"setup": -1}), r"greater than or equal to 0"),
    (workers(pack={"setup": 1, "capacity": 1}), r"greater than or equal to 2"),
    (workers(pack={"setup": 1, "size": 3}), r"Extra inputs are not permitted"),
])
def test_invalid_s_batch_steps_rejected(data, message):
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(data)


def test_operation_longer_than_one_shift_part_rejected():
    d = workers(pack={"setup": 1})
    for o in d["orders"]:
        for op in o["operations"]:
            if op["step"] == "pack":
                op["duration"] = 391
    with pytest.raises(ValidationError, match=r"\[V23\] s-batch step pack: an operation of 391 does not fit one "
                                              r"shift part \(390\)"):
        Instance.model_validate(d)


def test_generator_passes_s_batch_steps_and_rejects_unknown_steps():
    base = CarrierGeneratorParams(
        seed=0, n_orders=2, count_range=(2, 2), carriers_per_run=1, workers=("A",), no_machine=("pack",),
        route=[{"id": "print", "step": "print", "scope": "carrier", "role": "form"},
               {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["print"]},
               {"id": "pack", "step": "pack", "predecessors": ["saw"], "worker": {"whole": True}}],
        machines={"print": 1, "saw": 1}, durations={"print": (5, 5), "saw": (1, 1), "pack": (10, 10)})
    inst = generate_carrier_instance(base.model_copy(update={"s_batch_steps": {"pack": {"setup": 1}}}))
    assert inst.s_batch_steps["pack"].setup == 1
    assert "s_batch_steps" not in base.model_dump()  # omitted at its default: config hashes stay unchanged
    with pytest.raises(ValidationError, match=r"s_batch_steps for steps \['nope'\] not in the route"):
        CarrierGeneratorParams.model_validate(base.model_dump() | {"s_batch_steps": {"nope": {"setup": 1}}})


def tiny(parts: int, polish_machines: int = 0, orders: int = 2, plate: int = 12, **s_batch_steps) -> Instance:
    """Two orders of `parts` primary parts each on one plate: print, saw, polish of the primary parts (scope
    primary) and pack (scope order) by worker A, pack without machine, polish on `polish_machines` tools
    (polish1, ...) or without machine; `orders` orders, `plate` size units per plate (3: one plate per order)."""
    return generate_carrier_instance(CarrierGeneratorParams(
        seed=0, n_orders=orders, count_range=(parts, parts), carriers_per_run=1, workers=("A",), carrier_capacity=plate,
        no_machine=("pack",) if polish_machines else ("polish", "pack"), s_batch_steps=s_batch_steps,
        route=[{"id": "print", "step": "print", "scope": "carrier", "role": "form"},
               {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["print"]},
               {"id": "polish", "step": "polish", "scope": "primary", "predecessors": ["saw"],
                "worker": {"whole": True}},
               {"id": "pack", "step": "pack", "predecessors": ["polish"], "worker": {"whole": True}}],
        machines={"print": 1, "saw": 1} | ({"polish": polish_machines} if polish_machines else {}),
        durations={"print": (5, 5), "saw": (1, 1), "polish": (10, 10), "pack": (10, 10)}))


def test_units_by_hand():
    # 3 primary parts: polish covers 3; pack counts the order as 1, print and saw their carrier as 1 (the same factors
    # the generator multiplies the per-unit time with: polish 3 * 10 = 30)
    inst = tiny(3)
    order = inst.orders[0]
    assert {op.id: units(order, op) for op in order.operations} == {"print": 1, "saw": 1, "polish": 3, "pack": 1}
    assert next(op.duration for op in order.operations if op.id == "polish") == 30


def test_capacity_in_parts():
    assert tiny(3, polish={"setup": 5, "capacity": 3}).s_batch_steps["polish"].capacity == 3
    with pytest.raises(ValidationError, match=r"\[V23\] s-batch step polish: O1/polish covers 3 parts, more than "
                                              r"the capacity 2"):
        tiny(3, polish={"setup": 5, "capacity": 2})
