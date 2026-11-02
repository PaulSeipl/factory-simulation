"""Batches decided by the planner, e.g. oven runs (math/03_loads.md, C10)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.dispatching import dispatch, ect, spt

PATH = Path(__file__).parents[1] / "data" / "instances" / "toy-carriers.json"


def data(capacity: int | None = 3) -> dict:
    d = json.loads(PATH.read_text(encoding="utf-8"))
    if capacity is not None:
        d["carrier_steps"]["oven"]["batch_capacity"] = capacity
    return d


CI = compile_instance(Instance.model_validate(data()))

# hand plan of tests/test_carriers.py, but L1 waits for L2 and both share one oven run [16,19) on O;
# QM L1 [19,20) L2 [20,21); saw L1 [20,21) L2 [21,22); finish B [21,22), A [22,23), C [23,24)
JOINT = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "design", "D", 0, 2), ("B", "design", "D", 2, 4), ("C", "design", "D", 4, 6),
        ("A", "mill", "M", 2, 5), ("B", "mill", "M", 5, 8),
        ("R1", "setup", "P", 4, 5), ("R1", "print", "P", 5, 9), ("R1", "removal", "P", 9, 10),
        ("R2", "setup", "P", 10, 11), ("R2", "print", "P", 11, 15), ("R2", "removal", "P", 15, 16),
        ("L1", "oven", "O", 16, 19), ("L2", "oven", "O", 16, 19),
        ("L1", "qm", "Q", 19, 20), ("L2", "qm", "Q", 20, 21),
        ("L1", "saw", "S", 20, 21), ("L2", "saw", "S", 21, 22),
        ("B", "finish", "F", 21, 22), ("A", "finish", "F", 22, 23), ("C", "finish", "F", 23, 24),
    ]
]


def moved(plan, **moves):
    return [a.model_copy(update=dict(zip(("machine", "start", "end"), moves[f"{a.order_id}/{a.op_id}"], strict=True)))
            if f"{a.order_id}/{a.op_id}" in moves else a for a in plan]


def test_capacity_only_for_the_batch_step():
    caps = {key: CI.batch_capacity[o] for o, key in enumerate(CI.op_keys)}
    assert caps["L1", "oven"] == caps["L2", "oven"] == 3
    assert {c for key, c in caps.items() if key[1] != "oven"} == {1}


def test_joint_oven_run_is_feasible():
    assert check_schedule(CI, JOINT) == []


def test_staggered_overlap_is_not_a_batch():
    plan = moved(JOINT, **{"L2/oven": ("O", 17, 20), "L2/qm": ("Q", 20, 21)})
    assert (("L1", "oven"), ("L2", "oven")) in {v.ops for v in check_schedule(CI, plan) if v.constraint == "C5"}


def test_without_batching_a_joint_run_overlaps():
    ci = compile_instance(Instance.model_validate(data(capacity=None)))
    assert "C5" in {v.constraint for v in check_schedule(ci, JOINT)}


def test_more_carriers_than_capacity():
    # three orders of size 12 fill three carriers; oven capacity 2; all three ovens at the same time
    params = CarrierGeneratorParams(
        seed=0, n_orders=3, count_range=(12, 12), carriers_per_run=1,
        route=[{"id": "print", "step": "print", "scope": "carrier", "role": "form"},
               {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["print"]},
               {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["oven"]}],
        machines={"print": 3, "oven": 1, "saw": 1}, durations={"print": (5, 5), "oven": (10, 10), "saw": (1, 1)})
    raw = generate_carrier_instance(params).model_dump()
    raw["carrier_steps"]["oven"]["batch_capacity"] = 2
    ci = compile_instance(Instance.model_validate(raw))
    plan = [a.model_copy(update={"start": 5, "end": 15}) if a.op_id == "oven" else a
            for a in dispatch(ci, spt, ect)]
    plan = [a.model_copy(update={"start": 15 + i, "end": 16 + i}) if a.op_id == "saw" else a
            for i, a in enumerate(sorted(plan, key=lambda a: a.op_id != "saw"))]
    violations = check_schedule(ci, plan)
    assert [v.constraint for v in violations] == ["C10"]
    assert "3 operations in one run on oven1 [5,15), capacity 2" in violations[0].message


@pytest.mark.parametrize(("change", "message"), [
    (lambda d: d["carrier_steps"]["oven"].update(batch_capacity=1), r"greater than or equal to 2"),
    (lambda d: d["carrier_steps"]["oven"].update(setup=1), r"carrier step oven: a batch step has no setup"),
    (lambda d: d["runs"].append({"id": "R9", "step": "oven", "carriers": ["L1"]}),
     r"carrier step oven: batched by the planner, so no given runs"),
])
def test_invalid_batch_step_rejected(change, message):
    d = data()
    change(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)
