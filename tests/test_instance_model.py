import json

import pytest
from pydantic import ValidationError

from simulation.io.json_loader import read_model, write_model
from simulation.model.instance import Instance
from simulation.model.schedule import Schedule


def ops(data, order_idx):
    return data["orders"][order_idx]["operations"]


# --- positive ---------------------------------------------------------------


def test_toy_loads(toy_path):
    inst = read_model(toy_path, Instance)
    assert inst.machines == ("M1", "M2", "M3")
    assert [len(o.operations) for o in inst.orders] == [2, 3, 2]
    assert inst.orders[1].operations[2].predecessors == ("2",)


def test_toy_roundtrip_lossless(toy_path, tmp_path):
    original = json.loads(toy_path.read_text(encoding="utf-8"))
    inst = read_model(toy_path, Instance)
    # exclude_unset: dump exactly the fields the file provided (no injected defaults)
    assert json.loads(inst.model_dump_json(exclude_unset=True)) == original
    write_model(inst, tmp_path / "out.json")
    assert read_model(tmp_path / "out.json", Instance) == inst


def test_same_op_ids_and_steps_across_orders_allowed():
    inst = Instance.model_validate(
        {
            "schema_version": "0.2",
            "name": "dup-across-orders",
            "machines": ["M1"],
            "orders": [
                {"id": "A", "operations": [{"id": "1", "step": "print", "options": {"M1": 1}}]},
                {"id": "B", "operations": [{"id": "1", "step": "print", "options": {"M1": 2}}]},
            ],
        }
    )
    assert inst.orders[0].operations[0].id == inst.orders[1].operations[0].id


def test_instance_is_frozen(toy_path):
    inst = read_model(toy_path, Instance)
    with pytest.raises(ValidationError, match="frozen"):
        inst.name = "other"
    assert isinstance(inst.orders, tuple)


# --- negative: one per validation -------------------------------------------


def unknown_machine(d):
    ops(d, 0)[0]["options"]["M9"] = 1


def empty_options(d):
    ops(d, 0)[0]["options"] = {}


def unknown_predecessor(d):
    ops(d, 0)[1]["predecessors"] = ["99"]


def predecessor_from_other_order(d):
    # "3" exists only in J2; local IDs always resolve within J1
    ops(d, 0)[1]["predecessors"] = ["3"]


def cycle(d):
    ops(d, 0)[0]["predecessors"] = ["2"]  # 1 <- 2 <- 1


def self_loop(d):
    ops(d, 0)[0]["predecessors"] = ["1"]


def duplicate_op_id(d):
    ops(d, 1)[2]["id"] = "1"


def duplicate_order_id(d):
    d["orders"][1]["id"] = "J1"


def duplicate_machine(d):
    d["machines"].append("M1")


def zero_duration(d):
    ops(d, 0)[0]["options"]["M1"] = 0


def negative_duration(d):
    ops(d, 0)[0]["options"]["M1"] = -3


def negative_release(d):
    d["orders"][0]["release"] = -1


def unknown_field(d):
    ops(d, 0)[0]["predeccessors"] = []  # the old typo


def wrong_schema_version(d):
    d["schema_version"] = "0.1"


def unknown_time_unit(d):
    d["time_unit"] = "mins"


def duplicate_predecessor(d):
    ops(d, 0)[1]["predecessors"] = ["1", "1"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (unknown_machine, r"order J1, op 1: unknown machines \['M9'\]"),
        (empty_options, r"at least 1 item"),
        (unknown_predecessor, r"order J1, op 2: unknown predecessors \['99'\]"),
        (duplicate_predecessor, r"order J1, op 2: duplicate predecessors \['1'\]"),
        (predecessor_from_other_order, r"order J1, op 2: unknown predecessors \['3'\]"),
        (cycle, r"order J1: cycle in predecessors: (1 -> 2 -> 1|2 -> 1 -> 2)"),
        (self_loop, r"order J1: cycle in predecessors: 1 -> 1"),
        (duplicate_op_id, r"order J2: duplicate operation IDs: \['1'\]"),
        (duplicate_order_id, r"duplicate order IDs: \['J1'\]"),
        (duplicate_machine, r"duplicate machine IDs: \['M1'\]"),
        (zero_duration, r"greater than 0"),
        (negative_duration, r"greater than 0"),
        (negative_release, r"greater than or equal to 0"),
        (unknown_field, r"predeccessors\s+Extra inputs are not permitted"),
        (wrong_schema_version, r"Input should be '0.2'"),
        (unknown_time_unit, r"Input should be 's', 'min' or 'h'"),
    ],
    ids=lambda v: v.__name__ if callable(v) else None,
)
def test_invalid_instance_rejected(toy_data, mutate, message):
    mutate(toy_data)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(toy_data)


# --- schedule (structural only) ---------------------------------------------

VALID_ASSIGNMENT = {"order_id": "J1", "op_id": "1", "machine": "M1", "start": 0, "end": 4}


def test_schedule_roundtrip():
    sched = Schedule.model_validate({"assignments": [VALID_ASSIGNMENT]})
    assert Schedule.model_validate_json(sched.model_dump_json()) == sched


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"start": -1}, r"greater than or equal to 0"),
        ({"end": 0}, r"J1/1: end \(0\) must be > start \(0\)"),
        ({"end": -2}, r"must be > start"),
        ({"machnie": "M1"}, r"machnie\s+Extra inputs are not permitted"),
    ],
)
def test_invalid_assignment_rejected(override, message):
    with pytest.raises(ValidationError, match=message):
        Schedule.model_validate({"assignments": [VALID_ASSIGNMENT | override]})
