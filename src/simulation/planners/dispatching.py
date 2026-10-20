"""Dispatching with a sequencing rule and an optional assignment rule (math/11_dispatching-rules.md).

With an assignment rule:
  when an operation becomes ready (all predecessors scheduled), the assignment rule fixes its
  machine; at every step the earliest possible start t over all ready operations on their
  assigned machines is computed, and among those that can start at t the sequencing rule picks one.
Without an assignment rule ("joint"):
  the earliest possible start t is taken over all (ready operation, eligible machine) pairs, and
  the sequencing rule ranks the pairs that can start at t, i.e. it chooses operation and machine.

Both variants are non-delay: a machine never stays idle while a candidate could start on it.
"""

from collections.abc import Callable
from dataclasses import dataclass

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment


@dataclass(slots=True)
class DispatchState:
    ready_at: list[int]  # per op: max(release, completion of all predecessors)
    machine_free: list[int]  # per machine: end of its last scheduled operation
    load: list[int]  # per machine: total processing time assigned so far
    backlog: list[int]  # per machine: processing time assigned but not yet scheduled
    work_left: list[int]  # per order: sum of min_m p_{o,m} over its unscheduled operations
    remaining_path: list[int]  # per op: longest path to the end of its order with min_m p (static)


# rule(ci, state, o, m, p) -> priority; the smallest wins, ties broken by operation, then machine index
type SequencingRule = Callable[[CompiledInstance, DispatchState, int, int, int], tuple[int, ...]]
# rule(ci, state, o) -> machine index from M_o
type AssignmentRule = Callable[[CompiledInstance, DispatchState, int], int]


def spt(_ci: CompiledInstance, _state: DispatchState, _o: int, _m: int, p: int) -> tuple[int, ...]:
    """Shortest processing time on the (assigned) machine."""
    return (p,)


def fifo(_ci: CompiledInstance, state: DispatchState, o: int, _m: int, p: int) -> tuple[int, ...]:
    """First in, first out: the operation that has been ready longest; SPT as tie-breaker."""
    return (state.ready_at[o], p)


def mwkr(ci: CompiledInstance, state: DispatchState, o: int, _m: int, p: int) -> tuple[int, ...]:
    """Most work remaining in the operation's order; SPT as tie-breaker."""
    return (-state.work_left[ci.op_order[o]], p)


def lrp(_ci: CompiledInstance, state: DispatchState, o: int, _m: int, p: int) -> tuple[int, ...]:
    """Longest remaining path from the operation to the end of its order; SPT as tie-breaker."""
    return (-state.remaining_path[o], p)


def least_load(ci: CompiledInstance, state: DispatchState, o: int) -> int:
    """Eligible machine with the least assigned processing time; then shorter p, then lower index."""
    return min(ci.options[o], key=lambda mp: (state.load[mp[0]], mp[1], mp[0]))[0]


def ect(ci: CompiledInstance, state: DispatchState, o: int) -> int:
    """Earliest completion time, counting work already queued on the machine; then shorter p, lower index."""
    def completion(mp: tuple[int, int]) -> int:
        m, p = mp
        return max(state.ready_at[o], state.machine_free[m] + state.backlog[m]) + p

    return min(ci.options[o], key=lambda mp: (completion(mp), mp[1], mp[0]))[0]


SEQUENCING_RULES: dict[str, SequencingRule] = {"spt": spt, "fifo": fifo, "mwkr": mwkr, "lrp": lrp}
ASSIGNMENT_RULES: dict[str, AssignmentRule] = {"least_load": least_load, "ect": ect}


def dispatch(
    ci: CompiledInstance, sequencing: SequencingRule, assignment: AssignmentRule | None = None
) -> list[Assignment]:
    min_p = [min(p for _, p in opts) for opts in ci.options]
    work_left = [0] * len(ci.order_ids)
    for o in range(ci.n_ops):
        work_left[ci.op_order[o]] += min_p[o]
    remaining_path = [0] * ci.n_ops
    for o in reversed(ci.topo_order):
        remaining_path[o] = min_p[o] + max((remaining_path[s] for s in ci.successors[o]), default=0)
    zeros = [0] * ci.n_machines
    state = DispatchState(list(ci.release), list(zeros), list(zeros), list(zeros), work_left, remaining_path)
    open_preds = [len(preds) for preds in ci.predecessors]
    duration = [dict(opts) for opts in ci.options]
    ready: dict[int, tuple[tuple[int, int], ...]] = {}  # ready operation -> machines it may still use

    def make_ready(o: int) -> None:
        if assignment is None:
            ready[o] = ci.options[o]
        else:
            m = assignment(ci, state, o)
            ready[o] = ((m, duration[o][m]),)
            state.load[m] += duration[o][m]
            state.backlog[m] += duration[o][m]

    for o in range(ci.n_ops):
        if open_preds[o] == 0:
            make_ready(o)

    out: list[Assignment] = []
    while ready:
        candidates = [
            (max(state.ready_at[o], state.machine_free[m]), o, m, p) for o, mps in ready.items() for m, p in mps
        ]
        t = min(c[0] for c in candidates)
        _, o, m, p = min(
            (c for c in candidates if c[0] == t),
            key=lambda c: (*sequencing(ci, state, c[1], c[2], c[3]), c[1], c[2]),
        )
        del ready[o]
        if assignment is None:
            state.load[m] += p
        else:
            state.backlog[m] -= p

        order_id, op_id = ci.op_keys[o]
        out.append(Assignment(order_id=order_id, op_id=op_id, machine=ci.machine_ids[m], start=t, end=t + p))
        state.machine_free[m] = t + p
        state.work_left[ci.op_order[o]] -= min_p[o]
        for s in ci.successors[o]:
            state.ready_at[s] = max(state.ready_at[s], t + p)
            open_preds[s] -= 1
            if open_preds[s] == 0:
                make_ready(s)

    return out
