from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import dispatch, ect, spt
from simulation.sim.des import replay

# dental-like route: design, milling of the primary parts, carrier from print to saw with one QM per carrier
ROUTE = [
    {"id": "design", "step": "design"},
    {"id": "mill", "step": "mill", "scope": "primary", "predecessors": ["design"]},
    {"id": "print", "step": "print", "scope": "carrier", "role": "form", "predecessors": ["design"]},
    {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["print"]},
    {"id": "qm", "step": "qm", "scope": "carrier", "predecessors": ["oven", "mill"]},
    {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["qm"]},
    {"id": "finish", "step": "finish", "predecessors": ["saw"]},
]
BASE = {
    "seed": 3, "n_orders": 10, "release_range": (0, 30), "route": ROUTE,
    "machines": {"design": 2, "mill": 3, "print": 2, "oven": 1, "qm": 1, "saw": 1, "finish": 2},
    "durations": {"design": (10, 20), "mill": (5, 10), "print": (60, 90), "oven": (90, 90), "qm": (10, 15),
                  "saw": (5, 10), "finish": (10, 20)},
    "setup": 10, "removal": 10, "unit_time": 8, "estimator": {"fixed": 20, "share": 0.5},
}


def params(**changes) -> CarrierGeneratorParams:
    return CarrierGeneratorParams(**{**BASE, **changes})


def test_nesting_by_hand():
    # 7 orders with 4 primary parts each (size 4), capacity 12: three orders per carrier, in index order (no due
    # dates, all released at 0); two carriers per run
    inst = generate_carrier_instance(params(n_orders=7, release_range=(0, 0), count_range=(4, 4),
                                            carriers_per_run=2))
    assert [(c.id, [k for k, _ in c.parts]) for c in inst.carriers] == [
        ("C1", ["O1", "O2", "O3"]), ("C2", ["O4", "O5", "O6"]), ("C3", ["O7"])]
    assert [(r.id, r.carriers) for r in inst.runs] == [("R1", ("C1", "C2")), ("R2", ("C3",))]
    assert all(len([p for p in o.parts if p.type == "primary"]) == 4 for o in inst.orders)


def test_same_seed_same_instance():
    assert generate_carrier_instance(params()) == generate_carrier_instance(params())
    assert generate_carrier_instance(params()) != generate_carrier_instance(params(seed=4))


@pytest.mark.parametrize("seed", range(10))
def test_nesting_respects_capacity_runs_and_due_date_order(seed):
    inst = generate_carrier_instance(params(seed=seed, n_orders=15, due_date_tightness=(1.5, 2.0)))
    size = {o.id: sum(p.type == "primary" for p in o.parts) for o in inst.orders}
    due = {o.id: o.due_date for o in inst.orders}
    assert all(1 <= n <= 7 for n in size.values())
    assert sorted(k for c in inst.carriers for k, _ in c.parts) == sorted(size)  # every order on one carrier
    assert all(sum(size[k] for k, _ in c.parts) <= 12 for c in inst.carriers)
    assert all(len(r.carriers) <= 4 for r in inst.runs)
    in_nesting_order = [due[k] for c in inst.carriers for k, _ in c.parts]
    assert in_nesting_order == sorted(in_nesting_order)  # earliest due date first


def test_part_type_operations_scale_with_the_number_of_parts():
    inst = generate_carrier_instance(params())
    for o in inst.orders:
        n = sum(p.type == "primary" for p in o.parts)
        mill = next(op for op in o.operations if op.id == "mill")
        assert all(d % n == 0 and 5 * n <= d <= 10 * n for d in mill.options.values())
        assert next(p for p in o.parts if p.type == "secondary").times == {"print": 8 * n}


def test_generated_instance_is_solvable_and_replays_unchanged():
    ci = compile_instance(generate_carrier_instance(params(n_orders=6)))
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []
        realized = replay(ci, plan).schedule
        def key(a):
            return a.order_id, a.op_id

        assert sorted(realized, key=key) == sorted(plan, key=key)


@pytest.mark.parametrize(("changes", "message"), [
    ({"count_range": (1, 13)}, r"a carried part of size 13 exceeds the carrier capacity 12"),
    ({"machines": {**BASE["machines"], "oven": 0}}, r"greater than 0"),
    ({"machines": {k: v for k, v in BASE["machines"].items() if k != "saw"}}, r"no machines for steps \['saw'\]"),
    ({"durations": {k: v for k, v in BASE["durations"].items() if k != "qm"}}, r"no durations for steps \['qm'\]"),
    ({"run_step": "design"}, r"run step 'design' is not a carrier step of the route"),
    ({"unit_time": None}, r"the estimator needs unit_time"),
    ({"count_range": (5, 2)}, r"count_range: min 5 > max 2"),
    ({"batch_capacity": {"print": 3}}, r"batch_capacity for \['print'\]: only carrier steps other than the run step"),
    ({"batch_capacity": {"oven": 1}}, r"greater than or equal to 2"),
])
def test_invalid_parameters_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


# blanks: primary parts of several orders on one blank (mill per blank, separation, polishing), carrier milling
# per plate after the oven; both milling steps on the same mills
BLANK_ROUTE = [
    {"id": "design", "step": "design"},
    {"id": "mill_blank", "step": "mill_blank", "scope": "carrier", "carries": "primary", "role": "form",
     "predecessors": ["design"]},
    {"id": "separate", "step": "separate", "scope": "carrier", "carries": "primary", "role": "separate",
     "predecessors": ["mill_blank"]},
    {"id": "polish", "step": "polish", "scope": "primary", "predecessors": ["separate"]},
    {"id": "print", "step": "print", "scope": "carrier", "carries": "secondary", "role": "form",
     "predecessors": ["design"]},
    {"id": "oven", "step": "oven", "scope": "carrier", "carries": "secondary", "predecessors": ["print"]},
    {"id": "mill_carrier", "step": "mill_carrier", "scope": "carrier", "carries": "secondary",
     "predecessors": ["oven"]},
    {"id": "qm", "step": "qm", "scope": "carrier", "carries": "secondary", "predecessors": ["mill_carrier", "polish"]},
    {"id": "saw", "step": "saw", "scope": "carrier", "carries": "secondary", "role": "separate",
     "predecessors": ["qm"]},
    {"id": "finish", "step": "finish", "predecessors": ["saw"]},
]
BLANKS = {
    "route": BLANK_ROUTE,
    "machines": {"design": 2, "mill": 3, "bench": 2, "print": 2, "oven": 1, "qm": 1, "saw": 1, "finish": 2},
    "machine_pool": {"mill_blank": "mill", "mill_carrier": "mill", "separate": "bench", "polish": "bench"},
    "durations": {**{k: v for k, v in BASE["durations"].items() if k != "mill"}, "mill_blank": (30, 30),
                  "mill_carrier": (20, 20), "separate": (5, 5), "polish": (3, 6)},
    "per_carrier": {"mill_blank": {"setup": 5, "removal": 5, "unit_time": 12},
                    "mill_carrier": {"setup": 5, "removal": 5, "unit_time": 4}},
    "batch_capacity": {"oven": 3}, "blank_capacity": 6,
}


def test_blank_nesting_and_times_by_hand():
    # 3 orders with 4 primary parts each, blank capacity 6, index order: B1 = O1 n1..n4 + O2 n1, n2;
    # B2 = O2 n3, n4 + O3 n1..n4 (O2 spans two blanks)
    inst = generate_carrier_instance(params(**BLANKS, n_orders=3, release_range=(0, 0), count_range=(4, 4)))
    blanks = [(c.id, c.parts) for c in inst.carriers if c.id.startswith("B")]
    assert blanks == [("B1", (("O1", "n1"), ("O1", "n2"), ("O1", "n3"), ("O1", "n4"), ("O2", "n1"), ("O2", "n2"))),
                      ("B2", (("O2", "n3"), ("O2", "n4"), ("O3", "n1"), ("O3", "n2"), ("O3", "n3"), ("O3", "n4")))]
    parts = {p.id: p for p in inst.orders[0].parts}
    assert parts["c"].times == {"print": 32, "mill_carrier": 16}  # 4 telescopes * 4
    assert parts["n1"].times == {"mill_blank": 12}
    assert set(inst.carrier_steps["mill_blank"].options) == set(inst.carrier_steps["mill_carrier"].options) == {
        "mill1", "mill2", "mill3"}
    assert inst.carrier_steps["mill_carrier"].runs == "per_carrier"
    ci = compile_instance(inst)
    assert dict(ci.options[ci.op_index["B1", "mill_blank"]]) == dict.fromkeys(
        (ci.machine_index[m] for m in ("mill1", "mill2", "mill3")), 6 * 12)
    polish = {ci.op_keys[q] for q in ci.predecessors[ci.op_index["O2", "polish"]]}
    assert polish == {("B1", "separate"), ("B2", "separate")}  # O2's primary parts are on both blanks


def test_generated_instance_with_blanks_is_solvable_and_replays_unchanged():
    ci = compile_instance(generate_carrier_instance(params(**BLANKS, n_orders=6)))
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []
        assert {(a.order_id, a.op_id): (a.machine, a.start) for a in replay(ci, plan).schedule} == {
            (a.order_id, a.op_id): (a.machine, a.start) for a in plan}


@pytest.mark.parametrize(("changes", "message"), [
    ({"blank_capacity": None}, r"blank_capacity is needed exactly when carrier operations carry 'primary'"),
    ({"per_carrier": {**BLANKS["per_carrier"], "print": {"unit_time": 1}}},
     r"per_carrier for \['print'\]: only carrier steps other than the run step and batch steps"),
    ({"per_carrier": {**BLANKS["per_carrier"], "oven": {"unit_time": 1}}}, r"per_carrier for \['oven'\]"),
    ({"machine_pool": {**BLANKS["machine_pool"], "grind": "mill"}}, r"machine_pool for steps \['grind'\] not in the"),
    ({"machine_pool": {**BLANKS["machine_pool"], "polish": "lathe"}}, r"no machines for steps \['polish'\]"),
    ({"route": [{**op, "carries": "tertiary"} if op["id"] == "oven" else op for op in BLANK_ROUTE]},
     r"carrier operations carry \['tertiary'\]"),
    ({"route": [{**op, "carries": "primary"} if op["id"] == "print" else op for op in BLANK_ROUTE]},
     r"run step 'print' must not carry 'primary'"),
])
def test_invalid_blank_parameters_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**{**BLANKS, **changes})


def test_blank_capacity_without_blanks_rejected():
    with pytest.raises(ValidationError, match=r"blank_capacity is needed exactly when"):
        params(blank_capacity=6)


def test_example_parameter_file():
    path = Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-example.json"
    inst = generate_carrier_instance(read_model(path, CarrierGeneratorParams))
    assert len(inst.orders) == 40 and all(o.due_date is not None for o in inst.orders)
    assert inst.carrier_steps["oven"].batch_capacity == 3
