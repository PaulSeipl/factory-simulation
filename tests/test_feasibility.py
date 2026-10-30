from pathlib import Path

import pytest

from simulation.check.feasibility import assert_feasible, check_schedule
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.sim.snapshot import FrozenOperation, Snapshot

DATA = Path(__file__).parents[1] / "data"
TOY = compile_instance(read_model(DATA / "instances" / "toy-dag-3x4.json", Instance))

# hand-checked feasible schedule for toy-dag-3x4, makespan 11
FEASIBLE = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]


def mutate(op_id: str, **changes) -> list[Assignment]:
    return [a.model_copy(update=changes) if a.op_id == op_id else a for a in FEASIBLE]


def serial_schedule(ci: CompiledInstance) -> list[Assignment]:
    """One operation after another in topological order, first eligible machine: always feasible."""
    t, out = 0, []
    for o in ci.topo_order:
        m, p = ci.options[o][0]
        start = max(t, ci.release[o])
        order_id, op_id = ci.op_keys[o]
        out.append(Assignment(order_id=order_id, op_id=op_id, machine=ci.machine_ids[m], start=start, end=start + p))
        t = start + p
    return out


def test_hand_schedule_is_feasible():
    assert check_schedule(TOY, FEASIBLE) == []


@pytest.mark.parametrize(
    "path",
    [DATA / "instances" / "toy-3x3.json", DATA / "instances" / "toy-dag-3x4.json",
     *sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs"))],
    ids=lambda p: p.stem,
)
def test_serial_schedule_is_feasible(path):
    # guards against false positives on all instances
    inst = load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)
    ci = compile_instance(inst)
    assert_feasible(ci, serial_schedule(ci))


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        pytest.param(
            [*FEASIBLE, Assignment(order_id="A", op_id="zz", machine="M1", start=20, end=23)], "C0", id="unknown-op"
        ),
        pytest.param(FEASIBLE[:-1], "C1", id="missing-op"),
        pytest.param([*FEASIBLE, FEASIBLE[0]], "C1", id="duplicate-op"),
        pytest.param(mutate("c2", machine="M3"), "C1", id="ineligible-machine"),
        pytest.param(mutate("a3", machine="M9"), "C1", id="unknown-machine"),
        pytest.param(mutate("b3", end=7), "C2", id="wrong-duration"),
        pytest.param(mutate("b4", start=8, end=10), "C3", id="before-predecessor"),
        pytest.param(mutate("c1", start=1, end=3), "C4", id="before-release"),
        pytest.param(mutate("c2", machine="M4", start=8, end=12), "C5", id="machine-overlap"),
    ],
)
def test_each_violation_is_detected_alone(schedule, expected):
    violations = check_schedule(TOY, schedule)
    assert {v.constraint for v in violations} == {expected}, violations


def test_c5_reports_every_overlapping_pair():
    # a1, b1, c1 all on M1 from time 10 (durations on M1: 3, 2, 3) -> three pairs
    duration_on_m1 = {"a1": 3, "b1": 2, "c1": 3}
    schedule = [
        a.model_copy(update={"machine": "M1", "start": 10, "end": 10 + duration_on_m1[a.op_id]})
        if a.op_id in duration_on_m1 else a
        for a in FEASIBLE
    ]
    pairs = {frozenset(v.ops) for v in check_schedule(TOY, schedule) if v.constraint == "C5"}
    assert pairs >= {
        frozenset({("A", "a1"), ("B", "b1")}),
        frozenset({("A", "a1"), ("C", "c1")}),
        frozenset({("B", "b1"), ("C", "c1")}),
    }


def test_touching_intervals_do_not_overlap():
    # a1 ends at 3 and b1 starts at 3 on M1 in FEASIBLE: [S, C) is half-open
    assert not [v for v in check_schedule(TOY, FEASIBLE) if v.constraint == "C5"]


def test_assert_feasible_lists_violations():
    with pytest.raises(AssertionError, match=r"\[C4\]"):
        assert_feasible(TOY, mutate("c1", start=1, end=3))


# --- revised plans against a snapshot (math/05: C6, C7) ---------------------------------------

# at t = 4: a1 finished [0,3); a2 running on M3 since 3 (expected end 6); b1 running on M1 since 3,
# realized end unknown, expected end 5 (planned)
SNAPSHOT = Snapshot(instance=TOY.name, t=4, frozen=[
    FrozenOperation(order_id="A", op_id="a1", machine="M1", start=0, end=3, running=False),
    FrozenOperation(order_id="A", op_id="a2", machine="M3", start=3, end=6, running=True),
    FrozenOperation(order_id="B", op_id="b1", machine="M1", start=3, end=5, running=True),
])


def test_feasible_plan_passes_with_snapshot():
    assert check_schedule(TOY, FEASIBLE, SNAPSHOT) == []


def test_frozen_operation_with_expected_end_is_not_a_c2_violation():
    # a2 overruns: frozen with expected end 7 instead of 6; its successors are shifted accordingly
    overrun = Snapshot(instance=TOY.name, t=4, frozen=[*SNAPSHOT.frozen[:1],
                       SNAPSHOT.frozen[1].model_copy(update={"end": 7}), SNAPSHOT.frozen[2]])
    plan = [a.model_copy(update=changes.get(a.op_id, {})) for a in FEASIBLE
            for changes in [{"a2": {"end": 7}, "a3": {"start": 7, "end": 9}, "c1": {"start": 7, "end": 9},
                             "c2": {"start": 9, "end": 11}}]]
    assert check_schedule(TOY, plan, overrun) == []


@pytest.mark.parametrize(
    "plan",
    [
        pytest.param(mutate("a1", machine="M2"), id="frozen-machine-changed"),  # a1 also fits on M2 at [0,3)
        pytest.param(mutate("a2", end=5), id="frozen-end-changed"),  # expected end 6 in the snapshot
    ],
)
def test_changed_frozen_operation_is_c7(plan):
    assert {v.constraint for v in check_schedule(TOY, plan, SNAPSHOT)} == {"C7"}


def test_free_operation_before_t_is_c6():
    # at t = 4 only a1 is frozen; b1 (free) planned at 3 is before the rescheduling point
    # (a2 and b1 are free in this snapshot, but planned at 3)
    early = Snapshot(instance=TOY.name, t=4, frozen=SNAPSHOT.frozen[:1])
    assert {(v.constraint, v.ops[0][1]) for v in check_schedule(TOY, FEASIBLE, early)} == {("C6", "a2"), ("C6", "b1")}
