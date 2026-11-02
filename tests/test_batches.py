"""Batches decided by the planner, e.g. oven runs (math/03_loads.md, C10)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch, dispatch_planner, ect, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import Scenario, sample_scenario

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


def three_carriers(capacity: int | None) -> CompiledInstance:
    """Three orders of size 12 fill three carriers, each in its own print run on three printers (5 min);
    one oven (10 min, given capacity), one saw (1 min)."""
    params = CarrierGeneratorParams(
        seed=0, n_orders=3, count_range=(12, 12), carriers_per_run=1,
        route=[{"id": "print", "step": "print", "scope": "carrier", "role": "form"},
               {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["print"]},
               {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["oven"]}],
        machines={"print": 3, "oven": 1, "saw": 1}, durations={"print": (5, 5), "oven": (10, 10), "saw": (1, 1)})
    raw = generate_carrier_instance(params).model_dump()
    raw["carrier_steps"]["oven"]["batch_capacity"] = capacity
    return compile_instance(Instance.model_validate(raw))


def test_more_carriers_than_capacity():
    ci = three_carriers(2)
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


# --- step 2: dispatching, DES, repair ------------------------------------------------------------


def one_run() -> CompiledInstance:
    """Both carriers in one print run, oven capacity 3: they leave the printer together."""
    d = data()
    d["runs"] = [{"id": "R1", "step": "print", "carriers": ["L1", "L2"]}]
    return compile_instance(Instance.model_validate(d))


def times(schedule):
    return {(a.order_id, a.op_id): (a.start, a.end) for a in schedule}


def neutral(ci, factor=None, offset=None):
    factor, offset = factor or {}, offset or {}
    return Scenario(instance=ci.name, seed=0, sigma=0, factors=[
        {"order_id": k, "op_id": j, "factor": factor.get(f"{k}/{j}", 1.0), "start_offset": offset.get(f"{k}/{j}", 0)}
        for k, j in ci.op_keys])


def test_greedy_batching_by_hand():
    # R1 waits for all three designs (6): setup [6,7), print [7,11), removal [11,12); both carriers are ready at 12
    # and share the oven run [12,15); QM L1 [15,16) L2 [16,17); saw [16,17) [17,18); finish B 17, A 18, C 19
    t = times(dispatch(one_run(), spt, ect))
    assert t["L1", "oven"] == t["L2", "oven"] == (12, 15)
    assert (t["B", "finish"], t["A", "finish"], t["C", "finish"]) == ((17, 18), (18, 19), (19, 20))


@pytest.mark.parametrize("rule", [(s, a) for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None]],
                         ids=lambda r: f"{r[0]}-{r[1] or 'joint'}")
def test_every_rule_batches_feasibly_and_replays_unchanged(rule):
    ci = one_run()
    plan = dispatch(ci, SEQUENCING_RULES[rule[0]], ASSIGNMENT_RULES[rule[1]] if rule[1] else None)
    assert check_schedule(ci, plan) == []
    assert times(replay(ci, plan).schedule) == times(plan)


def test_batch_starts_jointly_and_a_late_worker_delays_all():
    ci = one_run()
    plan = dispatch(ci, spt, ect)
    t = times(replay(ci, plan, neutral(ci, offset={"L2/oven": 2})).schedule)
    assert t["L1", "oven"] == t["L2", "oven"] == (14, 17)


def test_oven_program_duration_does_not_deviate():
    ci = one_run()
    t = times(replay(ci, dispatch(ci, spt, ect), neutral(ci, factor={"L1/oven": 2.0})).schedule)
    assert t["L1", "oven"] == t["L2", "oven"] == (12, 15)


def test_repair_moves_the_batch_as_one():
    # the print takes 6 instead of 4: removal ends at 14, the batch moves to [14,17) together
    ci = one_run()
    t = times(execute(ci, dispatch(ci, spt, ect), neutral(ci, factor={"R1/print": 1.5}), ReschedulingPolicy()).schedule)
    assert t["L1", "oven"] == t["L2", "oven"] == (14, 17)


@pytest.mark.parametrize("seed", range(5))
def test_disturbed_execution_with_repair_keeps_batches(seed):
    ci = one_run()
    sc = sample_scenario(Instance.model_validate(data() | {"runs": [{"id": "R1", "step": "print",
                                                                     "carriers": ["L1", "L2"]}]}),
                         sigma=0.3, seed=seed, q=0.5, max_early=2, max_late=2)
    realized = execute(ci, dispatch(ci, spt, ect), sc, ReschedulingPolicy()).schedule
    assert {v.constraint for v in check_schedule(ci, realized)} <= {"C2"}
    t = times(realized)
    assert t["L1", "oven"] == t["L2", "oven"]


# --- step 3: CP-SAT ------------------------------------------------------------------------------


@pytest.mark.parametrize(("capacity", "optimum"), [(None, 36), (3, 18)])
def test_cpsat_batching_by_hand(capacity, optimum):
    # all prints end at 5. Without batching the ovens run one after another: the last ends at 35, its saw at 36.
    # With capacity 3 one oven run [5,15) takes all three carriers; the single saw then needs 3 minutes: 18.
    ci = three_carriers(capacity)
    result = solve(ci, time_limit=10, workers=1)
    assert (result.status, result.objective, result.bound) == ("OPTIMAL", optimum, optimum)
    assert check_schedule(ci, result.schedule) == []
    if capacity:
        assert {a.start for a in result.schedule if a.op_id == "oven"} == {5}


def test_zero_disturbance_of_a_batched_cpsat_plan():
    ci = three_carriers(3)
    plan = solve(ci, time_limit=10, workers=1).schedule
    realized = replay(ci, plan).schedule
    assert times(realized) == times(plan) and max(a.end for a in realized) == 18


def test_batching_is_optional_for_cpsat():
    # on the mini instance the carriers leave the printers at different times: the optimum stays 20 (no joint run)
    assert solve(CI, time_limit=10, workers=1).objective == 20


def test_cpsat_from_a_snapshot_with_a_running_batch():
    ci = one_run()
    sim = Simulation(ci, dispatch(ci, spt, ect))
    sim.run(until=13)  # the joint oven run [12,15) is running
    snap = sim.snapshot()
    result = solve(ci, time_limit=10, workers=1, snapshot=snap)
    assert result.status == "OPTIMAL" and check_schedule(ci, result.schedule, snap) == []


# --- step 4: rescheduling ----------------------------------------------------------------------------


@pytest.mark.parametrize("planner", ["rule", "cpsat"])
@pytest.mark.parametrize("seed", range(4))
def test_rescheduling_with_batches_keeps_every_constraint(planner, seed):
    ci = one_run()
    inst = Instance.model_validate(data() | {"runs": [{"id": "R1", "step": "print", "carriers": ["L1", "L2"]}]})
    plan_of = {"rule": dispatch_planner(spt, ect), "cpsat": cpsat_planner(time_limit=2)}
    policy = ReschedulingPolicy(plan_of[planner], max_makespan_change=0, period=4)
    sc = sample_scenario(inst, sigma=0.3, seed=seed, q=0.5, max_early=2, max_late=2)
    result = execute(ci, dispatch(ci, spt, ect), sc, policy)
    assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}  # incl. C10
    assert any(d["type"] == "REPLAN" for d in result.decisions)
