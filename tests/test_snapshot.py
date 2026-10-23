import random
from pathlib import Path

import pytest

from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model, write_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.dispatching import best_dispatch
from simulation.sim.des import replay, run
from simulation.sim.scenario import OperationFactor, Scenario, sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot, snapshot

DATA = Path(__file__).parents[1] / "data"
TOY_INSTANCE = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
TOY = compile_instance(TOY_INSTANCE)
# hand-checked feasible plan (tests/test_feasibility.py)
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]


def scenario(**factor_of_op) -> Scenario:
    return Scenario(instance=TOY.name, seed=0, sigma=0, factors=[
        {"order_id": o.id, "op_id": op.id, "factor": factor_of_op.get(op.id, 1.0)}
        for o in TOY_INSTANCE.orders for op in o.operations
    ])


def snap(sc: Scenario | None, t: int) -> Snapshot:
    state, _ = run(TOY, PLAN, sc, until=t)
    return snapshot(TOY, PLAN, state)


def test_snapshot_at_5_with_b1_delayed():
    # b1 takes 4 instead of 2 (realized end 7); at t=5 it is still running although planned to end at 5,
    # so the planner sees the earliest possible end 6. b2 is due at 5 but waits for b1: not frozen.
    s = snap(scenario(b1=2.0), t=5)
    assert s.t == 5
    assert s.frozen == (
        FrozenOperation(order_id="A", op_id="a1", machine="M1", start=0, end=3, running=False),
        FrozenOperation(order_id="A", op_id="a2", machine="M3", start=3, end=6, running=True),
        FrozenOperation(order_id="B", op_id="b1", machine="M1", start=3, end=6, running=True),
    )


def test_running_operation_shows_planned_not_realized_end():
    # without overrun the expected end is start + planned duration (a2: 3 + 3), whatever the factor is
    assert {f.op_id: f.end for f in snap(scenario(a2=1.9), t=4).frozen if f.running} == {"a2": 6, "b1": 5}


def test_snapshot_does_not_depend_on_the_factor_of_a_running_operation():
    assert snap(scenario(b1=2.0), t=5) == snap(scenario(b1=3.0), t=5)


@pytest.mark.parametrize("t", [0, 7, 20, 40])
@pytest.mark.parametrize("seed", range(3))
def test_no_information_leakage_on_mk01(seed, t):
    # change the future (factors of running ops upwards, of unstarted ops arbitrarily): the snapshot must not change
    inst = load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")
    ci = compile_instance(inst)
    _, plan = best_dispatch(ci)
    base = sample_scenario(inst, sigma=0.3, seed=seed)
    state, _ = run(ci, plan, base, until=t)
    rng = random.Random(seed)
    future = [
        f.model_copy(update={"factor": f.factor * rng.uniform(1.0, 3.0)}) if state.start[o] is not None
        else OperationFactor(order_id=f.order_id, op_id=f.op_id, factor=rng.uniform(0.2, 3.0))
        for o, f in enumerate(base.factors)
        if state.end[o] is None
    ]
    past = [f for o, f in enumerate(base.factors) if state.end[o] is not None]
    changed = base.model_copy(update={"factors": (*past, *future)})
    changed_state, _ = run(ci, plan, changed, until=t)
    assert snapshot(ci, plan, changed_state) == snapshot(ci, plan, state)


def test_frozen_operations_lie_in_the_past_or_around_t():
    for t in range(0, 16):
        s = snap(scenario(b1=2.0, c1=1.5), t)
        for f in s.frozen:
            assert f.start <= t
            assert (f.end > t) if f.running else (f.end <= t)


def test_snapshot_at_0_and_after_the_end():
    assert snap(None, 0).frozen == (FrozenOperation(order_id="A", op_id="a1", machine="M1", start=0, end=3,
                                                    running=True),)
    realized = replay(TOY, PLAN, scenario(b1=2.0)).schedule
    end = snap(scenario(b1=2.0), t=100)
    assert end.t == 100
    assert [(f.op_id, f.machine, f.start, f.end, f.running) for f in end.frozen] == [
        (a.op_id, a.machine, a.start, a.end, False) for a in realized
    ]


def test_snapshot_round_trips_as_json(tmp_path):
    s = snap(scenario(b1=2.0), t=5)
    write_model(s, tmp_path / "snapshot.json")
    assert read_model(tmp_path / "snapshot.json", Snapshot) == s
