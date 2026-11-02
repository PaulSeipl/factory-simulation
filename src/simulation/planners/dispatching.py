"""Dispatching with a sequencing rule and an optional assignment rule (math/11_dispatching-rules.md).

With an assignment rule:
  when an operation becomes ready (all predecessors scheduled), the assignment rule fixes its
  machine; at every step the earliest possible start t over all ready operations on their
  assigned machines is computed, and among those that can start at t the sequencing rule picks one.
Without an assignment rule ("joint"):
  the earliest possible start t is taken over all (ready operation, eligible machine) pairs, and
  the sequencing rule ranks the pairs that can start at t, i.e. it chooses operation and machine.

Both variants are non-delay: a machine never stays idle while a candidate could start on it.

A run (setup, main operation, removal; math/03_loads.md) is dispatched as one unit: its first operation stands for
the whole run, and when it is chosen the run's operations are placed back to back on one machine (C8, C9).

From a snapshot (rescheduling, math/05_rescheduling-frozen-part.md): the frozen operations are kept as
they are, their machines are busy until their (expected) end, and nothing new starts before snapshot.t.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN, Objective

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot


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
    return (-max(state.work_left[k] for k in ci.op_orders[o]), p)


def lrp(_ci: CompiledInstance, state: DispatchState, o: int, _m: int, p: int) -> tuple[int, ...]:
    """Longest remaining path from the operation to the end of its order; SPT as tie-breaker."""
    return (-state.remaining_path[o], p)


def edd(ci: CompiledInstance, _state: DispatchState, o: int, _m: int, p: int) -> tuple[int, ...]:
    """Earliest due date of the operation's order; SPT as tie-breaker; orders without due date last."""
    due = min((d for k in ci.op_orders[o] if (d := ci.due_date[k]) is not None), default=None)
    return (0, due, p) if due is not None else (1, 0, p)


def least_load(ci: CompiledInstance, state: DispatchState, o: int) -> int:
    """Eligible machine with the least assigned processing time; then shorter p, then lower index."""
    return min(ci.options[o], key=lambda mp: (state.load[mp[0]], mp[1], mp[0]))[0]


def ect(ci: CompiledInstance, state: DispatchState, o: int) -> int:
    """Earliest completion time, counting work already queued on the machine; then shorter p, lower index."""
    def completion(mp: tuple[int, int]) -> int:
        m, p = mp
        return max(state.ready_at[o], state.machine_free[m] + state.backlog[m]) + p

    return min(ci.options[o], key=lambda mp: (completion(mp), mp[1], mp[0]))[0]


SEQUENCING_RULES: dict[str, SequencingRule] = {"spt": spt, "fifo": fifo, "mwkr": mwkr, "lrp": lrp, "edd": edd}
ASSIGNMENT_RULES: dict[str, AssignmentRule] = {"least_load": least_load, "ect": ect}


def dispatch(
    ci: CompiledInstance,
    sequencing: SequencingRule,
    assignment: AssignmentRule | None = None,
    snapshot: Snapshot | None = None,
) -> list[Assignment]:
    min_p = [min(p for _, p in opts) for opts in ci.options]
    work_left = [0] * len(ci.order_ids)
    for o in range(ci.n_ops):
        for k in ci.op_orders[o]:
            work_left[k] += min_p[o]
    remaining_path = [0] * ci.n_ops
    for o in reversed(ci.topo_order):
        remaining_path[o] = min_p[o] + max((remaining_path[s] for s in ci.successors[o]), default=0)
    t0 = snapshot.t if snapshot else 0
    state = DispatchState(
        [max(r, t0) for r in ci.release], [t0] * ci.n_machines, [0] * ci.n_machines, [0] * ci.n_machines,
        work_left, remaining_path,
    )
    open_preds = [len(preds) for preds in ci.predecessors]
    duration = [dict(opts) for opts in ci.options]
    run_of = {g[0]: g for g in ci.machine_groups}  # first operation -> the whole run
    for head, group in run_of.items():  # the head stands for the run: duration of the run on each machine
        duration[head] = {m: sum(duration[q][m] for q in group) for m in duration[head]}
    ready: dict[int, tuple[tuple[int, int], ...]] = {}  # ready operation -> machines it may still use

    out: list[Assignment] = []
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    for o, f in frozen.items():  # the frozen part: kept unchanged, occupies its machine until its end
        m = ci.machine_index[f.machine]
        out.append(Assignment(order_id=f.order_id, op_id=f.op_id, machine=f.machine, start=f.start, end=f.end))
        state.machine_free[m] = max(state.machine_free[m], f.end)
        state.load[m] += duration[o][m]
        for k in ci.op_orders[o]:
            state.work_left[k] -= min_p[o]
        for s in ci.successors[o]:
            state.ready_at[s] = max(state.ready_at[s], f.end)
            open_preds[s] -= 1

    for g in ci.machine_groups:  # a partly started run continues back to back on its machine (C8, C9)
        if (rest := [q for q in g if q not in frozen]) and len(rest) < len(g):
            m = ci.machine_index[frozen[g[0]].machine]
            start = max(t0, state.machine_free[m])
            for q in rest:
                end = start + duration[q][m]
                owner, op_id = ci.op_keys[q]
                out.append(Assignment(order_id=owner, op_id=op_id, machine=ci.machine_ids[m], start=start, end=end))
                state.load[m] += duration[q][m]
                for k in ci.op_orders[q]:
                    state.work_left[k] -= min_p[q]
                for s in ci.successors[q]:
                    state.ready_at[s] = max(state.ready_at[s], end)
                    open_preds[s] -= 1
                start = end
            state.machine_free[m] = start
            frozen.update(dict.fromkeys(rest))  # placed: never made ready below

    def make_ready(o: int) -> None:
        if assignment is None:
            ready[o] = tuple(duration[o].items())
        else:
            # shortcut: assignment rules see the head's own duration (e.g. setup), not the whole run; fine while
            # the run's durations rank the machines like its setup, revisit with the print-duration estimator
            m = assignment(ci, state, o)
            ready[o] = ((m, duration[o][m]),)
            state.load[m] += duration[o][m]
            state.backlog[m] += duration[o][m]

    for o in range(ci.n_ops):
        if open_preds[o] == 0 and o not in frozen:
            make_ready(o)

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

        state.machine_free[m] = t + p
        group = run_of.get(o)
        start = t
        for q in group or (o,):  # a run back to back on one machine; a single operation otherwise
            end = start + (dict(ci.options[q])[m] if group else p)
            owner, op_id = ci.op_keys[q]
            out.append(Assignment(order_id=owner, op_id=op_id, machine=ci.machine_ids[m], start=start, end=end))
            for k in ci.op_orders[q]:
                state.work_left[k] -= min_p[q]
            for s in ci.successors[q]:
                if group and s in group:
                    continue  # placed in this loop
                state.ready_at[s] = max(state.ready_at[s], end)
                open_preds[s] -= 1
                if open_preds[s] == 0:
                    make_ready(s)
            start = end

    return out


def best_dispatch(ci: CompiledInstance, objective: Objective = MAKESPAN) -> tuple[str, list[Assignment]]:
    """Best schedule over all sequencing rules x (assignment rules + joint) under the objective."""
    runs = (
        (f"{s}/{a or 'joint'}", dispatch(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None))
        for s in SEQUENCING_RULES
        for a in [*ASSIGNMENT_RULES, None]
    )
    return min(runs, key=lambda run: objective.evaluate(ci, run[1]))


def dispatch_planner(sequencing: SequencingRule, assignment: AssignmentRule | None = None):
    """Rescheduling planner for the DES: planner(ci, snapshot, current_plan) -> new complete plan."""

    def planner(ci: CompiledInstance, snapshot: Snapshot, _current: Sequence[Assignment]) -> list[Assignment]:
        return dispatch(ci, sequencing, assignment, snapshot)

    return planner

