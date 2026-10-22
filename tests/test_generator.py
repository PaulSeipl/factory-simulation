import pytest
from pydantic import ValidationError

from simulation.check.feasibility import assert_feasible
from simulation.generator import GeneratorParams, generate_instance
from simulation.io.json_loader import read_model, write_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import best_dispatch

BASE = {
    "seed": 7, "n_machines": 5, "n_orders": 6, "n_operations": 40, "min_order_length": 4,
    "max_machines_per_op": 3, "duration_range": (2, 9), "max_duration_spread": 3, "release_range": (0, 10),
    "routing_modes": ("chain", "split", "join", "split_join"), "max_branches": 3,
}


def params(**changes) -> GeneratorParams:
    return GeneratorParams(**{**BASE, **changes})


def test_same_seed_same_instance_other_seed_other_instance():
    assert generate_instance(params()) == generate_instance(params())
    assert generate_instance(params()) != generate_instance(params(seed=8))


def test_counts_lengths_machines_durations_and_releases_respect_the_parameters():
    inst = generate_instance(params())
    assert inst.machines == ("M1", "M2", "M3", "M4", "M5")
    assert len(inst.orders) == 6
    assert sum(len(o.operations) for o in inst.orders) == 40
    assert all(len(o.operations) >= 4 for o in inst.orders)
    assert all(0 <= o.release <= 10 for o in inst.orders)
    for op in (op for o in inst.orders for op in o.operations):
        assert 1 <= len(op.options) <= 3
        assert all(2 <= p <= 9 + 3 for p in op.options.values())
        assert max(op.options.values()) - min(op.options.values()) <= 3


def degrees(order):
    succ = {op.id: 0 for op in order.operations}
    for op in order.operations:
        for q in op.predecessors:
            succ[q] += 1
    pred = {op.id: len(op.predecessors) for op in order.operations}
    return pred, succ


@pytest.mark.parametrize("mode", ["chain", "split", "join", "split_join"])
def test_each_routing_mode_has_its_shape(mode):
    inst = generate_instance(params(routing_modes=(mode,), n_operations=60))
    for order in inst.orders:
        pred, succ = degrees(order)
        sources = [o for o, d in pred.items() if d == 0]
        sinks = [o for o, d in succ.items() if d == 0]
        forks = [succ[o] for o in succ if succ[o] >= 2]  # out-degree of operations with several successors
        merges = [pred[o] for o in pred if pred[o] >= 2]
        if mode == "chain":
            assert (len(sources), len(sinks), forks, merges) == (1, 1, [], [])
        elif mode == "split":
            assert len(sources) == 1 and merges == [] and len(forks) == 1
            assert len(sinks) == forks[0] and 2 <= forks[0] <= 3  # one sink per branch
        elif mode == "join":
            assert len(sinks) == 1 and forks == [] and len(merges) == 1
            assert len(sources) == merges[0] and 2 <= merges[0] <= 3  # one source per branch
        else:
            assert (len(sources), len(sinks), len(forks), len(merges)) == (1, 1, 1, 1)
            assert forks[0] == merges[0] and 2 <= forks[0] <= 3


def test_templates_keep_structure_and_given_options_fill_the_rest():
    template = {"operations": [
        {"id": "print", "options": {"M1": 5}},
        {"id": "secondary", "predecessors": ["print"]},
        {"id": "primary-1", "predecessors": ["print"]},
        {"id": "primary-2", "predecessors": ["print"]},
        {"id": "qm", "predecessors": ["secondary", "primary-1", "primary-2"]},
    ]}
    inst = generate_instance(params(templates=(template,), n_orders=6, n_operations=40))
    t1 = next(o for o in inst.orders if o.id == "T1")
    ops = {op.id: op for op in t1.operations}
    assert dict(ops["print"].options) == {"M1": 5}
    assert ops["qm"].predecessors == ("secondary", "primary-1", "primary-2")
    assert all(ops[j].options for j in ops)
    assert len(inst.orders) == 6 and sum(len(o.operations) for o in inst.orders) == 40


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"n_operations": 20}, r"cannot fill 6 generated orders with at least 4"),
        ({"min_order_length": 3}, r"need min_order_length >= 4"),
        ({"max_machines_per_op": 6}, r"max_machines_per_op 6 > n_machines 5"),
        ({"duration_range": (9, 2)}, r"duration_range: min 9 > max 2"),
        ({"routing_modes": ("tree",)}, r"routing_modes"),
        ({"max_branches": 1}, r"greater than or equal to 2"),
    ],
)
def test_inconsistent_parameters_are_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


def test_generated_instance_is_solvable_and_round_trips_with_its_parameters(tmp_path):
    p = params()
    inst = generate_instance(p)
    write_model(inst, tmp_path / f"{inst.name}.json")
    write_model(p, tmp_path / f"{inst.name}.params.json")
    assert read_model(tmp_path / f"{inst.name}.json", Instance) == inst
    assert generate_instance(read_model(tmp_path / f"{inst.name}.params.json", GeneratorParams)) == inst
    ci = compile_instance(inst)
    assert_feasible(ci, best_dispatch(ci)[1])
