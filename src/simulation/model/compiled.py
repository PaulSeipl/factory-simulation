"""Index-based, immutable view of an Instance for the hot path (simulator, rules, solvers).

Operations are indexed in file order: the operations of every order (contiguous per order), then the
operations of the carriers and of the runs (math/03_carriers.md). Owners in op_keys are orders, carriers or runs.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import NamedTuple

from graphlib import TopologicalSorter

from simulation.calendar import WeekCalendar
from simulation.model.instance import Instance, operation_graph, units, visible_instance

type OpKey = tuple[str, str]  # (owner_id, op_id); owner: order, carrier or run


class Share(NamedTuple):
    """A worker share of an operation (math/04_workers.md): kind "whole", "prefix" or "suffix"; length in time
    units (0 for whole); qualified worker idxs. Stored independent of the duration, so it holds on every machine."""

    kind: str
    length: int
    workers: tuple[int, ...]


def share_interval(share: Share, start: int, end: int, length: int | None = None) -> tuple[int, int]:
    """[from, to) of the worker time of a share for an operation running in [start, end); `length` instead of the
    share's own (e.g. a started share's length from the snapshot)."""
    n = share.length if length is None else length
    if share.kind == "prefix":
        return start, start + n
    if share.kind == "suffix":
        return end - n, end
    return start, end


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
    calendar: WeekCalendar | None = None  # work calendar (math/04); None: no shifts, tardiness in minutes
    worker_ids: tuple[str, ...] = ()  # worker idx -> ID
    # op idx -> duration of an operation without machine (its options are empty), None otherwise
    fixed_duration: tuple[int | None, ...] = ()
    shares: tuple[tuple[Share, ...], ...] = ()  # op idx -> worker shares (whole, prefix, suffix)
    # order idx -> arrival: the planning tool knows the order from then on (math/07); the DES only wakes the tool
    arrival: tuple[int, ...] = ()
    accepted: tuple[int, ...] = ()  # order idx -> acceptance (math/07), for the lead time
    # op idx -> process step s(o) (setup and removal of a run: the run's step); a batch holds one step only (C10)
    step: tuple[str, ...] = ()
    # op idx -> setup of its s-batch step, inside its duration (math/08); None: not an s-batch step
    s_setup: tuple[int | None, ...] = ()
    s_capacity: tuple[int | None, ...] = ()  # op idx -> units per s-batch of its step; None: no limit
    units: tuple[int, ...] = ()  # op idx -> n_o, its units against the s-batch capacity (math/08)

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


def s_batch_length(ci: CompiledInstance, ops: Sequence[int], machine: int | None) -> int:
    """Planned length of the s-batch `ops` on machine idx `machine` (None: without machine): the setup once plus each
    member without it (math/08 C15); a single member lasts its own duration."""
    setup = ci.s_setup[ops[0]]
    return setup + sum((ci.fixed_duration[o] if machine is None else dict(ci.options[o])[machine]) - setup for o in ops)


def batch_key(ci: CompiledInstance, o: int, x) -> tuple | None:
    """The batch of operation o in assignment or frozen operation x: a p-batch by step, machine and time (C10), an
    s-batch by its id (C15); None if o is in none. Members of one batch share the key."""
    if ci.batch_capacity[o] > 1:
        return ci.step[o], x.machine, x.start, x.end
    if x.batch is not None and ci.s_setup[o] is not None:
        return "s-batch", x.batch
    return None


def compile_instance(instance: Instance) -> CompiledInstance:
    machine_ids = instance.machines
    machine_index = {m: i for i, m in enumerate(machine_ids)}
    order_index = {o.id: i for i, o in enumerate(instance.orders)}
    release = {o.id: o.release for o in instance.orders}
    graph = operation_graph(instance)
    op_of = {(o.id, op.id): op for o in instance.orders for op in o.operations}  # order operations by key
    order_of = {(o.id, op.id): o for o in instance.orders for op in o.operations}
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
        arrival=tuple(order.arrival for order in instance.orders),
        accepted=tuple(order.accepted for order in instance.orders),
        batch_capacity=tuple(
            (instance.carrier_steps[step].batch_capacity or 1) if (step := _carrier_step(instance, key)) else 1
            for key in op_keys
        ),
        machine_groups=tuple(dict.fromkeys(
            tuple(op_index[key] for key in node.group) for node in graph.values() if node.group
        )),
        # Instance validation guarantees an acyclic graph
        topo_order=tuple(TopologicalSorter(dict(enumerate(predecessors))).static_order()),
        calendar=WeekCalendar(**instance.calendar.model_dump()) if instance.calendar else None,
        worker_ids=instance.workers,
        fixed_duration=tuple(node.duration for node in graph.values()),
        shares=tuple(_compile_shares(node.shares, instance.workers) for node in graph.values()),
        step=tuple(node.step for node in graph.values()),
        s_setup=tuple(sb.setup if (sb := instance.s_batch_steps.get(node.step)) else None for node in graph.values()),
        s_capacity=tuple(sb.capacity if (sb := instance.s_batch_steps.get(node.step)) else None
                         for node in graph.values()),
        units=tuple(units(order_of[key], op_of[key]) if key in op_of else 1 for key in op_keys),
    )


def compile_visible(instance: Instance) -> Callable[[int], CompiledInstance]:
    """t -> the compiled visible sub-instance at t (math/07_order-arrivals.md), compiled once per set of known orders,
    so that the same object comes back until the next arrival."""
    cache: dict[tuple[str, ...], CompiledInstance] = {}

    def at(t: int) -> CompiledInstance:
        vis = visible_instance(instance, t)
        key = tuple(o.id for o in vis.orders)
        if key not in cache:
            cache[key] = compile_instance(vis)
        return cache[key]

    return at


def _compile_shares(shares, workers: tuple[str, ...]) -> tuple[Share, ...]:
    out = []
    for s in shares:
        idxs = tuple(workers.index(w) for w in s.qualified) if s.qualified else tuple(range(len(workers)))
        if s.whole:
            out.append(Share("whole", 0, idxs))
        out += [Share(kind, n, idxs) for kind, n in (("prefix", s.prefix), ("suffix", s.suffix)) if n]
    return tuple(out)


def _carrier_step(instance: Instance, key: OpKey) -> str | None:
    """Step of a carrier operation (owner is a carrier), None for order and run operations."""
    carrier = next((c for c in instance.carriers if c.id == key[0]), None)
    if carrier is None:
        return None
    order = next(o for o in instance.orders if o.id == carrier.parts[0][0])
    return next((op.step for op in order.operations if op.id == key[1]), None)  # None: setup, removal of a run
