"""Index-based, immutable view of an Instance for the hot path (simulator, rules, solvers).

Operations are indexed in file order: the operations of every order (contiguous per order), then the
operations of the carriers and of the runs (math/03_loads.md). Owners in op_keys are orders, carriers or runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType

from graphlib import TopologicalSorter

from simulation.model.instance import Instance, operation_graph

type OpKey = tuple[str, str]  # (owner_id, op_id); owner: order, carrier or run


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
    op_orders: tuple[tuple[int, ...], ...]  # op idx -> idxs of the orders it serves (one for order operations)
    release: tuple[int, ...]  # op idx -> latest release of the orders it serves
    due_date: tuple[int | None, ...]  # order idx -> due date (None: the order has none)
    # run operations (setup, main, removal): one machine, blocked from the first start to the last end
    machine_groups: tuple[tuple[int, ...], ...]
    # op idx -> carriers that may share one machine run with it (p-batch step), 1 otherwise
    batch_capacity: tuple[int, ...]
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
    order_index = {o.id: i for i, o in enumerate(instance.orders)}
    release = {o.id: o.release for o in instance.orders}
    graph = operation_graph(instance)
    op_keys = tuple(graph)
    op_index = {key: i for i, key in enumerate(op_keys)}

    predecessors = tuple(tuple(op_index[q] for q in node.predecessors) for node in graph.values())
    successors: list[list[int]] = [[] for _ in op_keys]
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
        options=tuple(tuple((machine_index[m], d) for m, d in node.options.items()) for node in graph.values()),
        predecessors=predecessors,
        successors=tuple(map(tuple, successors)),
        op_orders=tuple(tuple(order_index[k] for k in node.orders) for node in graph.values()),
        # carrier and run operations wait for their orders anyway; the latest release is the honest bound
        release=tuple(max(release[k] for k in node.orders) for node in graph.values()),
        due_date=tuple(order.due_date for order in instance.orders),
        batch_capacity=tuple(
            (instance.carrier_steps[step].batch_capacity or 1) if (step := _carrier_step(instance, key)) else 1
            for key in op_keys
        ),
        machine_groups=tuple(dict.fromkeys(
            tuple(op_index[key] for key in node.group) for node in graph.values() if node.group
        )),
        # Instance validation guarantees an acyclic graph
        topo_order=tuple(TopologicalSorter(dict(enumerate(predecessors))).static_order()),
    )


def _carrier_step(instance: Instance, key: OpKey) -> str | None:
    """Step of a carrier operation (owner is a carrier), None for order and run operations."""
    carrier = next((c for c in instance.carriers if c.id == key[0]), None)
    if carrier is None:
        return None
    order = next(o for o in instance.orders if o.id == carrier.parts[0][0])
    return next((op.step for op in order.operations if op.id == key[1]), None)  # None: setup, removal of a run
