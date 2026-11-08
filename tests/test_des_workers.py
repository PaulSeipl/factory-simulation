"""DES with worker shares and machine-less operations, no calendar effects yet (math/13_des.md, math/04_workers.md).

Hand plans: tests/test_workers_checker.py (toy-workers: print with prefix, Gegenbetten with prefix and rest,
packaging) and the carrier instance with an oven batch (prefix and suffix) and attended mill runs.
"""

from pathlib import Path

import pytest
from test_worker_compile import CARRIERS, carriers
from test_workers_checker import BREAKS, CI, carrier_plan, plan

from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.sim.des import replay
from simulation.sim.scenario import Scenario, sample_scenario

TOY = read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-workers.json", Instance)


def by_key(schedule):
    return {(a.order_id, a.op_id): (a.machine, a.start, a.end, a.workers) for a in schedule}


def scenario(ci, **changes):
    """Factor 1 and no offset, except `changes`: op_id -> factor or (factor, offset); op ids unique per instance
    in these tests, keyed by order_op."""
    rows = []
    for k, j in ci.op_keys:
        value = changes.get(f"{k}_{j}".replace("/", "_"), 1.0)
        factor, offset = value if isinstance(value, tuple) else (value, 0)
        rows.append({"order_id": k, "op_id": j, "factor": factor, "start_offset": offset})
    return Scenario(instance=ci.name, seed=0, sigma=0, factors=rows)


def test_zero_disturbance_toy_workers():
    result = replay(CI, plan(), breaks=BREAKS)
    assert by_key(result.schedule) == by_key(plan()) and result.breaks == BREAKS


def test_zero_disturbance_oven_batch_and_runs():
    assert by_key(replay(CARRIERS, carrier_plan()).schedule) == by_key(carrier_plan())


def test_scenario_with_factor_one_changes_nothing():
    assert by_key(replay(CI, plan(), scenario(CI), breaks=BREAKS).schedule) == by_key(plan())


def test_late_worker_on_a_prefix_delays_the_operation():
    # print planned at 0, B comes 5 minutes late: print [5, 65), Gegenbetten [65, 155), packaging [155, 175)
    got = by_key(replay(CI, plan(), scenario(CI, k1_print=(1.0, 5)), breaks=BREAKS).schedule)
    assert (got["k1", "print"][1:3], got["k1", "gb"][1:3], got["k1", "pack"][1:3]) == ((5, 65), (65, 155), (155, 175))


def test_prefix_of_a_machine_operation_scales_with_it():
    # print factor 2: machine time 120, prefix 30; Gegenbetten [120, 210), packaging [210, 230)
    got = by_key(replay(CI, plan(), scenario(CI, k1_print=2.0), breaks=BREAKS).schedule)
    assert (got["k1", "print"][1:3], got["k1", "gb"][1:3], got["k1", "pack"][1:3]) == ((0, 120), (120, 210), (210, 230))


def test_rest_is_fixed_and_only_the_work_scales():
    # Gegenbetten factor 2: work 30 -> 60, rest 60 fixed: [60, 180); A is free again at 120
    got = by_key(replay(CI, plan(), scenario(CI, k1_gb=2.0), breaks=BREAKS).schedule)
    assert (got["k1", "gb"][1:3], got["k1", "pack"][1:3]) == ((60, 180), (180, 200))


def polish_instance(workers=("W1", "W2"), polish=4):
    """The carrier instance plus a polishing of order A by W1 (whole) planned right before the oven removal."""
    data = carriers() | {"workers": list(workers)}
    data["orders"][0]["operations"].append(
        {"id": "polish", "step": "polish", "duration": polish, "worker": {"whole": True, "qualified": ["W1"]}})
    return compile_instance(Instance.model_validate(data))


def test_oven_waits_for_its_removal_worker():
    # one worker only: oven loading [4, 5), polishing [5, 8), removal [8, 9) all by W1. Polishing takes 6 instead
    # of 3, so W1 is busy until 11: removal [11, 12) -> overstay 3; mill runs L1 [12, 18), L2 [18, 24)
    ci = polish_instance(("W1",), polish=3)
    rows = [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e, workers=w) for o, j, m, s, e, w in [
        ("L1", "print", "P", 0, 2, ()), ("L2", "print", "P", 2, 4, ()),
        ("L1", "oven", "O", 4, 9, ("W1", "W1")), ("L2", "oven", "O", 4, 9, ("W1", "W1")),
        ("A", "polish", None, 5, 8, ("W1",)),
        ("L1", "mill/setup", "M", 9, 10, ("W1",)), ("L1", "mill", "M", 10, 14, ()),
        ("L1", "mill/removal", "M", 14, 15, ("W1",)),
        ("L2", "mill/setup", "M", 15, 16, ("W1",)), ("L2", "mill", "M", 16, 20, ()),
        ("L2", "mill/removal", "M", 20, 21, ("W1",)),
    ]]
    assert check_schedule(ci, rows) == []
    result = replay(ci, rows, scenario(ci, A_polish=2.0))
    got = by_key(result.schedule)
    assert got["L1", "oven"][1:3] == got["L2", "oven"][1:3] == (4, 12)
    assert (got["L1", "mill/setup"][1], got["L2", "mill/removal"][2]) == (12, 24)
    assert [r for r in result.log if r["type"] == "OVERSTAY"] == [
        {"t": 11, "type": "OVERSTAY", "order_id": "L1", "op_id": "oven", "machine": "O", "minutes": 3}]
    assert check_schedule(ci, result.schedule) == [] or {v.constraint for v in check_schedule(ci, result.schedule)} \
        == {"C2"}


@pytest.mark.parametrize("seed", range(5))
def test_disturbed_runs_pass_the_checker(seed):
    # C2 differs by design (realized durations); shifts and breaks are not simulated before Task 2 (C13, C14)
    realized = replay(CI, plan(), sample_scenario(TOY, 0.3, seed, q=0.5, max_late=5), breaks=BREAKS).schedule
    assert [v for v in check_schedule(CI, realized, breaks=BREAKS) if v.constraint not in {"C2", "C13", "C14"}] == []
    carrier_scenario = scenario(CARRIERS, **{f"{k}_{j}".replace("/", "_"): 1.0 + 0.2 * ((seed + o) % 3)
                                             for o, (k, j) in enumerate(CARRIERS.op_keys)})
    realized = replay(CARRIERS, carrier_plan(), carrier_scenario).schedule
    assert [v for v in check_schedule(CARRIERS, realized) if v.constraint != "C2"] == []
