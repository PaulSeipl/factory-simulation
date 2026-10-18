import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance

DATA = Path(__file__).parents[1] / "data"
PATHS = [DATA / "instances" / "toy-3x3.json", *sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs"))]

# operations listed against precedence order, so topo_order must actually sort
UNORDERED = Instance.model_validate(
    {
        "schema_version": "0.2",
        "name": "unordered",
        "machines": ["M1", "M2"],
        "orders": [
            {"id": "A", "release": 5, "operations": [
                {"id": "c", "step": "s", "options": {"M2": 1}, "predecessors": ["a", "b"]},
                {"id": "b", "step": "s", "options": {"M1": 2}, "predecessors": ["a"]},
                {"id": "a", "step": "s", "options": {"M1": 3, "M2": 4}},
            ]},
            {"id": "B", "operations": [{"id": "a", "step": "s", "options": {"M2": 6}}]},
        ],
    }
)


def load(path: Path) -> Instance:
    return load_fjs(path) if path.suffix == ".fjs" else read_model(path, Instance)


@pytest.fixture(params=[*PATHS, None], ids=[*(p.stem for p in PATHS), "unordered"])
def instance(request) -> Instance:
    return UNORDERED if request.param is None else load(request.param)


def test_id_mappings_roundtrip(instance):
    c = compile_instance(instance)
    keys = [(o.id, op.id) for o in instance.orders for op in o.operations]
    assert list(c.op_keys) == keys
    assert all(c.op_keys[c.op_index[k]] == k for k in keys)
    assert all(c.op_index[k] == i for i, k in enumerate(c.op_keys))
    assert c.machine_ids == instance.machines
    assert all(c.machine_ids[c.machine_index[m]] == m for m in instance.machines)
    assert c.order_ids == tuple(o.id for o in instance.orders)


def test_options_release_and_order_per_op(instance):
    c = compile_instance(instance)
    assert c.n_ops == sum(len(o.operations) for o in instance.orders)
    assert len(c.options) == len(c.predecessors) == len(c.successors) == c.n_ops
    for o_idx, order in enumerate(instance.orders):
        for op in order.operations:
            i = c.op_index[order.id, op.id]
            assert {c.machine_ids[m]: d for m, d in c.options[i]} == op.options
            assert len(c.options[i]) == len(op.options)
            assert [c.op_keys[p] for p in c.predecessors[i]] == [(order.id, p) for p in op.predecessors]
            assert c.op_order[i] == o_idx
            assert c.release[i] == order.release


def test_successors_consistent_with_predecessors(instance):
    c = compile_instance(instance)
    pred_edges = {(p, i) for i, preds in enumerate(c.predecessors) for p in preds}
    succ_edges = {(i, s) for i, succs in enumerate(c.successors) for s in succs}
    assert pred_edges == succ_edges
    assert sum(map(len, c.predecessors)) == sum(map(len, c.successors))  # no duplicates


def test_topo_order(instance):
    c = compile_instance(instance)
    assert sorted(c.topo_order) == list(range(c.n_ops))
    pos = {op: k for k, op in enumerate(c.topo_order)}
    assert all(pos[p] < pos[i] for i, preds in enumerate(c.predecessors) for p in preds)


def test_compiled_is_immutable(instance):
    c = compile_instance(instance)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.name = "other"
    with pytest.raises(TypeError):
        c.op_index["X", "1"] = 0
    with pytest.raises(TypeError):
        c.machine_index["M99"] = 0


def test_compiled_copy_and_pickle(instance):
    c = compile_instance(instance)
    assert copy.copy(c) is c
    assert copy.deepcopy({"state": c})["state"] is c
    restored = pickle.loads(pickle.dumps(c))
    assert restored == c
    with pytest.raises(TypeError):
        restored.op_index["X", "1"] = 0


def test_toy_topo_order_pinned():
    # graphlib emits level by level (interleaved across orders); not guaranteed by the docs,
    # so a Python upgrade that changes it fails here instead of silently changing decoders
    c = compile_instance(read_model(PATHS[0], Instance))
    assert c.topo_order == (0, 2, 5, 1, 3, 6, 4)
