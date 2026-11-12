"""Order arrivals, step 1: format (accepted, arrival), packages, visible sub-instance (math/07_order-arrivals.md)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance, visible_instance

DATA = Path(__file__).parents[1] / "data"


def two_packages(arrival: int = 10) -> dict:
    """toy-carriers twice: package 1 (A, B, C on L1, L2, runs R1, R2) known at 0, package 2 (A2, B2, C2 on L12,
    L22, runs R12, R22) arriving at `arrival`, released then."""
    base = json.loads((DATA / "instances" / "toy-carriers.json").read_text(encoding="utf-8"))
    late = copy.deepcopy(base)
    for o in late["orders"]:
        o["id"] += "2"
        o["arrival"] = o["release"] = arrival
    for c in late["carriers"]:
        c["id"] += "2"
        c["parts"] = [[k + "2", p] for k, p in c["parts"]]
    for r in late["runs"]:
        r["id"] += "2"
        r["carriers"] = [c + "2" for c in r["carriers"]]
    return base | {"name": "two-packages", "orders": base["orders"] + late["orders"],
                   "carriers": base["carriers"] + late["carriers"], "runs": base["runs"] + late["runs"]}


# --- format -------------------------------------------------------------------------------------------------------


def test_defaults_known_from_the_start(toy_data):
    inst = Instance.model_validate(toy_data)
    assert all(o.accepted == 0 and o.arrival == 0 for o in inst.orders)


def test_accepted_arrival_release_in_order(toy_data):
    toy_data["orders"][0] |= {"accepted": 2, "arrival": 5, "release": 7}
    order = Instance.model_validate(toy_data).orders[0]
    assert (order.accepted, order.arrival, order.release) == (2, 5, 7)


def test_two_packages_valid():
    inst = Instance.model_validate(two_packages())
    assert [o.arrival for o in inst.orders] == [0, 0, 0, 10, 10, 10]


def arrival_after_release(d):
    d["orders"][0] |= {"arrival": 6, "release": 5}


def accepted_after_arrival(d):
    d["orders"][0] |= {"accepted": 6, "arrival": 5, "release": 5}


def negative_arrival(d):
    d["orders"][0]["arrival"] = -1


def negative_accepted(d):
    d["orders"][0]["accepted"] = -1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (arrival_after_release, r"order J1: arrival 6 after release 5"),
        (accepted_after_arrival, r"order J1: accepted 6 after arrival 5"),
        (negative_arrival, r"greater than or equal to 0"),
        (negative_accepted, r"greater than or equal to 0"),
    ],
    ids=lambda v: v.__name__ if callable(v) else None,
)
def test_invalid_times_rejected(toy_data, mutate, message):
    mutate(toy_data)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(toy_data)


def test_carrier_across_packages_rejected():
    d = two_packages()
    carriers = {c["id"]: c for c in d["carriers"]}
    carriers["L2"]["parts"] = [["A", "s2"], ["C2", "s"]]  # swap C and C2: both carriers mix the packages
    carriers["L22"]["parts"] = [["A2", "s2"], ["C", "s"]]
    with pytest.raises(ValidationError, match=r"carrier L2: orders with different arrivals \{'A': 0, 'C2': 10\}"):
        Instance.model_validate(d)


def test_run_across_packages_rejected():
    d = two_packages()
    d["runs"] = [r for r in d["runs"] if r["id"] != "R12"]
    next(r for r in d["runs"] if r["id"] == "R1")["carriers"] = ["L1", "L12"]
    with pytest.raises(ValidationError, match=r"run R1: carriers with different arrivals \{'L1': 0, 'L12': 10\}"):
        Instance.model_validate(d)


# --- visible sub-instance -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("t", "orders", "carriers", "runs"), [
    (0, ["A", "B", "C"], ["L1", "L2"], ["R1", "R2"]),
    (9, ["A", "B", "C"], ["L1", "L2"], ["R1", "R2"]),
    (10, ["A", "B", "C", "A2", "B2", "C2"], ["L1", "L2", "L12", "L22"], ["R1", "R2", "R12", "R22"]),
])
def test_visible_instance_holds_the_known_packages(t, orders, carriers, runs):
    inst = Instance.model_validate(two_packages())
    vis = visible_instance(inst, t)
    assert [o.id for o in vis.orders] == orders
    assert [c.id for c in vis.carriers] == carriers
    assert [r.id for r in vis.runs] == runs
    assert vis.name == inst.name  # scenarios and snapshots keep matching by name
    assert Instance.model_validate(vis.model_dump()) == vis  # a valid instance on its own
    ci = compile_instance(vis)
    assert set(ci.order_ids) == set(orders)


def test_visible_instance_after_all_arrivals_is_the_instance():
    inst = Instance.model_validate(two_packages())
    assert visible_instance(inst, 10) == inst
