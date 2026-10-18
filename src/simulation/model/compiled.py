"""Index-based, immutable view of an Instance for the hot path (simulator, rules, solvers).

Operations are indexed in file order (orders in sequence, operations within each order),
so the operations of one order form a contiguous index range.
"""

from dataclasses import dataclass, fields
from graphlib import TopologicalSorter
from types import MappingProxyType
from typing import Mapping

from simulation.model.instance import Instance

type OpKey = tuple[str, str]  # (order_id, op_id)


@dataclass(frozen=True, slots=True)
class CompiledInstance:
    name: str
    time_unit: str
    machine_ids: tuple[str, ...]  # machine idx -> ID
    machine_index: Mapping[str, int]  # ID -> machine idx (read-only)
    order_ids: tuple[str, ...]  # order idx -> ID
    op_keys: tuple[OpKey, ...]  # op idx -> (order_id, op_id)
    op_index: Mapping[OpKey, int]  # (order_id, op_id) -> op idx (read-only)
    options: tuple[tuple[tuple[int, int], ...], ...]  # op idx -> ((machine idx, duration), ...)
    predecessors: tuple[tuple[int, ...], ...]  # op idx -> op idxs
    successors: tuple[tuple[int, ...], ...]  # op idx -> op idxs
    op_order: tuple[int, ...]  # op idx -> order idx
    release: tuple[int, ...]  # op idx -> release of its order
    topo_order: tuple[int, ...]  # all op idxs, every predecessor before its successors

    @property
    def n_ops(self) -> int:
        return len(self.op_keys)

    @property
    def n_machines(self) -> int:
        return len(self.machine_ids)

    # immutable, so copies (e.g. MCTS state deepcopy) can share it
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    # mappingproxy can't be pickled; needed for multiprocessing IPC, not for storage
    def __reduce__(self):
        state = {f.name: getattr(self, f.name) for f in fields(self)}
        state["machine_index"] = dict(self.machine_index)
        state["op_index"] = dict(self.op_index)
        return _rebuild, (state,)


def _rebuild(state: dict) -> CompiledInstance:
    state["machine_index"] = MappingProxyType(state["machine_index"])
    state["op_index"] = MappingProxyType(state["op_index"])
    return CompiledInstance(**state)


def compile_instance(instance: Instance) -> CompiledInstance:
    machine_ids = instance.machines
    machine_index = {m: i for i, m in enumerate(machine_ids)}
    flat = [(o_idx, order, op) for o_idx, order in enumerate(instance.orders) for op in order.operations]
    op_keys = tuple((order.id, op.id) for _, order, op in flat)
    op_index = {key: i for i, key in enumerate(op_keys)}

    predecessors = tuple(
        tuple(op_index[order.id, p] for p in op.predecessors) for _, order, op in flat
    )
    successors: list[list[int]] = [[] for _ in flat]
    for i, preds in enumerate(predecessors):
        for p in preds:
            successors[p].append(i)

    return CompiledInstance(
        name=instance.name,
        time_unit=instance.time_unit,
        machine_ids=machine_ids,
        machine_index=MappingProxyType(machine_index),
        order_ids=tuple(order.id for order in instance.orders),
        op_keys=op_keys,
        op_index=MappingProxyType(op_index),
        options=tuple(
            tuple((machine_index[m], d) for m, d in op.options.items()) for _, _, op in flat
        ),
        predecessors=predecessors,
        successors=tuple(map(tuple, successors)),
        op_order=tuple(o_idx for o_idx, _, _ in flat),
        release=tuple(order.release for _, order, _ in flat),
        # Instance validation guarantees an acyclic graph
        topo_order=tuple(TopologicalSorter(dict(enumerate(predecessors))).static_order()),
    )
