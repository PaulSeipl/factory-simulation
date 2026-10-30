from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible, check_schedule
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import (
    ASSIGNMENT_RULES,
    SEQUENCING_RULES,
    dispatch,
    ect,
    fifo,
    least_load,
    lrp,
    mwkr,
    spt,
)
from simulation.sim.des import run
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot, snapshot

DATA = Path(__file__).parents[1] / "data"
PATHS = [
    DATA / "instances" / "toy-3x3.json",
    DATA / "instances" / "toy-dag-3x4.json",
    *sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs")),
]
ASSIGNMENTS = {**ASSIGNMENT_RULES, "joint": None}  # None: the sequencing rule also picks the machine


def load(path: Path) -> Instance:
    return load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)


def instance(name: str, machines: list[str], orders: list[dict]) -> Instance:
    return Instance.model_validate({"schema_version": "0.2", "name": name, "machines": machines, "orders": orders})


@pytest.mark.parametrize("assignment", ASSIGNMENTS.values(), ids=ASSIGNMENTS.keys())
@pytest.mark.parametrize("sequencing", SEQUENCING_RULES.values(), ids=SEQUENCING_RULES.keys())
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_every_rule_combination_yields_feasible_schedule(path, sequencing, assignment):
    ci = compile_instance(load(path))
    assert_feasible(ci, dispatch(ci, sequencing, assignment))


# hand computations: math/11_dispatching-rules.md, section 5
@pytest.mark.parametrize(
    ("assignment", "expected"),
    [
        pytest.param(least_load, [
            ("a1", "M1", 0, 3), ("b1", "M3", 2, 6), ("a2", "M2", 3, 7), ("c1", "M1", 4, 7), ("b3", "M4", 6, 9),
            ("b2", "M2", 7, 10), ("a3", "M4", 9, 11), ("b4", "M2", 10, 13), ("c2", "M4", 11, 15),
        ], id="least_load"),
        pytest.param(ect, [
            ("a1", "M1", 0, 3), ("b1", "M1", 3, 5), ("a2", "M3", 3, 6), ("b2", "M2", 5, 8), ("b3", "M4", 5, 8),
            ("c1", "M3", 6, 8), ("a3", "M4", 8, 10), ("c2", "M2", 8, 10), ("b4", "M2", 10, 13),
        ], id="ect"),
        pytest.param(None, [
            ("a1", "M1", 0, 3), ("b1", "M3", 2, 6), ("a2", "M2", 3, 7), ("c1", "M1", 4, 7), ("b2", "M3", 6, 9),
            ("b3", "M4", 6, 9), ("c2", "M2", 7, 9), ("a3", "M4", 9, 11), ("b4", "M2", 9, 12),
        ], id="joint"),
    ],
)
def test_spt_on_toy_dag_matches_hand_computation(assignment, expected):
    ci = compile_instance(load(DATA / "instances" / "toy-dag-3x4.json"))
    assert [(a.op_id, a.machine, a.start, a.end) for a in dispatch(ci, spt, assignment)] == expected


# M1 is busy with w1 until t=2; then x1 (ready since 1, p=5), z1 (p=1, no successor) and
# y1 (p=1, then y2 with p=10) compete for M1. Every operation has a single eligible machine.
CONFLICT = instance("sequencing-conflict", ["M1", "M2"], [
    {"id": "W", "release": 0, "operations": [{"id": "w1", "step": "s", "options": {"M1": 2}}]},
    {"id": "X", "release": 1, "operations": [{"id": "x1", "step": "s", "options": {"M1": 5}}]},
    {"id": "Z", "release": 2, "operations": [{"id": "z1", "step": "s", "options": {"M1": 1}}]},
    {"id": "Y", "release": 2, "operations": [
        {"id": "y1", "step": "s", "options": {"M1": 1}},
        {"id": "y2", "step": "s", "options": {"M2": 10}, "predecessors": ["y1"]},
    ]},
])


@pytest.mark.parametrize(
    ("sequencing", "winner"),
    [(fifo, "x1"), (spt, "z1"), (mwkr, "y1"), (lrp, "y1")],  # spt: z1/y1 tie on p, z1 has the lower index
    ids=["fifo", "spt", "mwkr", "lrp"],
)
def test_sequencing_rules_resolve_the_conflict_differently(sequencing, winner):
    schedule = dispatch(compile_instance(CONFLICT), sequencing, least_load)
    assert [a.op_id for a in schedule][:2] == ["w1", winner]
    assert schedule[1].start == 2


# f1 is assigned first and queues 1 unit on M1; g1 can run on M1 (p=2) or M2 (p=5)
ASSIGNMENT_CONFLICT = instance("assignment-conflict", ["M1", "M2"], [
    {"id": "F", "operations": [{"id": "f1", "step": "s", "options": {"M1": 1}}]},
    {"id": "G", "operations": [{"id": "g1", "step": "s", "options": {"M1": 2, "M2": 5}}]},
])


@pytest.mark.parametrize(
    ("assignment", "machine_of_g1"),
    [(least_load, "M2"), (ect, "M1")],  # least load: 0 < 1; ect: completion 1 + 2 = 3 < 0 + 5 = 5
    ids=["least_load", "ect"],
)
def test_assignment_rules_resolve_the_conflict_differently(assignment, machine_of_g1):
    machines = {a.op_id: a.machine for a in dispatch(compile_instance(ASSIGNMENT_CONFLICT), spt, assignment)}
    assert machines == {"f1": "M1", "g1": machine_of_g1}


# --- dispatching from a snapshot (rescheduling, math/05) ---------------------------------------

TOY_SNAPSHOT = Snapshot(instance="toy-dag-3x4", t=5, frozen=[
    FrozenOperation(order_id="A", op_id="a1", machine="M1", start=0, end=3, running=False),
    FrozenOperation(order_id="A", op_id="a2", machine="M3", start=3, end=6, running=True),
    FrozenOperation(order_id="B", op_id="b1", machine="M1", start=3, end=6, running=True),  # overrunning
])


def test_joint_spt_from_snapshot_matches_hand_computation():
    # math/11_dispatching-rules.md, section 5: M1 and M3 busy until 6, nothing starts before 5
    ci = compile_instance(load(DATA / "instances" / "toy-dag-3x4.json"))
    plan = dispatch(ci, spt, None, TOY_SNAPSHOT)
    assert sorted((a.op_id, a.machine, a.start, a.end) for a in plan) == [
        ("a1", "M1", 0, 3), ("a2", "M3", 3, 6), ("a3", "M4", 6, 8), ("b1", "M1", 3, 6), ("b2", "M2", 6, 9),
        ("b3", "M1", 6, 10), ("b4", "M2", 10, 13), ("c1", "M3", 6, 8), ("c2", "M4", 8, 12),
    ]
    assert check_schedule(ci, plan, TOY_SNAPSHOT) == []


@pytest.mark.parametrize("assignment", ASSIGNMENTS.values(), ids=ASSIGNMENTS.keys())
@pytest.mark.parametrize("sequencing", SEQUENCING_RULES.values(), ids=SEQUENCING_RULES.keys())
def test_every_rule_combination_from_a_mid_run_snapshot_is_feasible(sequencing, assignment):
    inst = load(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")
    ci = compile_instance(inst)
    plan = dispatch(ci, spt, ect)
    state, _ = run(ci, plan, sample_scenario(inst, 0.3, seed=1), until=15)
    snap = snapshot(ci, plan, state)
    assert check_schedule(ci, dispatch(ci, sequencing, assignment, snap), snap) == []
