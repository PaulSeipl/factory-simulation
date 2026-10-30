"""Shift repair (math/05_rescheduling-frozen-part.md): re-time the operations not yet started.

Machine and order per machine stay as planned. An operation whose planned start was tight (equal to
the end of a predecessor, of the previous operation on its machine, or to its release) moves with its
blocker, earlier or later; an operation with a gap keeps its planned start unless its blocker now
ends later. Only what a planner may know at time t is used: realized times of finished operations,
starts of running operations and planned durations, never the scenario.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot


def shift_repair(
    ci: CompiledInstance,
    t: int,
    machine: Sequence[int],
    order_on: Sequence[Sequence[int]],
    planned_start: Sequence[int],
    planned_end: Sequence[int],
    start: Sequence[int | None],
    end: Sequence[int | None],
) -> tuple[list[int], list[int]]:
    """New planned start and end per operation.

    machine[o], order_on[m]: machine and order per machine of the current plan;
    planned_start, planned_end: the current plan (the one sent to the MES);
    start, end: realized start and completion, None if not (yet) known.
    """
    p = [dict(ci.options[o])[machine[o]] for o in range(ci.n_ops)]
    prev: list[int | None] = [None] * ci.n_ops  # previous operation on the same machine
    for ops in order_on:
        for a, b in zip(ops, ops[1:], strict=False):
            prev[b] = a

    new_start, new_end = list(planned_start), list(planned_end)
    for o in range(ci.n_ops):
        if start[o] is not None:  # finished: realized end; running: expected end, at least t + 1
            new_start[o] = start[o]
            new_end[o] = end[o] if end[o] is not None else max(start[o] + p[o], t + 1)

    # planned starts of a feasible plan respect precedence and machine order, so blockers come first
    for o in sorted((o for o in range(ci.n_ops) if start[o] is None), key=lambda o: (planned_start[o], o)):
        blockers = [*ci.predecessors[o], *([prev[o]] if prev[o] is not None else [])]
        old_block = max([ci.release[o], *(planned_end[q] for q in blockers)])
        new_block = max([t, ci.release[o], *(new_end[q] for q in blockers)])
        tight = planned_start[o] == old_block
        new_start[o] = new_block if tight else max(planned_start[o], new_block)
        new_end[o] = new_start[o] + p[o]
    return new_start, new_end


def repair(ci: CompiledInstance, snapshot: Snapshot, plan: Sequence[Assignment]) -> list[Assignment]:
    """Shift repair with the planner interface: (ci, snapshot, current plan) -> repaired complete plan."""
    machine, planned_start, planned_end = [0] * ci.n_ops, [0] * ci.n_ops, [0] * ci.n_ops
    for a in plan:
        o = ci.op_index[a.order_id, a.op_id]
        machine[o], planned_start[o], planned_end[o] = ci.machine_index[a.machine], a.start, a.end
    start: list[int | None] = [None] * ci.n_ops
    end: list[int | None] = [None] * ci.n_ops
    for f in snapshot.frozen:
        o = ci.op_index[f.order_id, f.op_id]
        start[o], end[o] = f.start, None if f.running else f.end
    order_on: list[list[int]] = [[] for _ in range(ci.n_machines)]
    for o in sorted(range(ci.n_ops), key=lambda o: (planned_start[o], o)):
        order_on[machine[o]].append(o)
    new_start, new_end = shift_repair(ci, snapshot.t, machine, order_on, planned_start, planned_end, start, end)
    return [Assignment(order_id=k, op_id=j, machine=ci.machine_ids[machine[o]], start=new_start[o], end=new_end[o])
            for o, (k, j) in enumerate(ci.op_keys)]
