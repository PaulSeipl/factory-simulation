"""Discrete-event simulation of plan execution (math/13_des.md).

Version 1 replays a plan without disturbances: every operation runs on its planned machine,
in the planned order per machine, and starts at its planned time. The DES decides nothing;
it checks at every start that the plan can be executed as given and raises otherwise.
"""

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment


class EventType(IntEnum):
    # value = priority at equal time: a completion frees the machine before the next start
    COMPLETE = 0
    START = 1


class PlanNotExecutable(ValueError):
    pass


@dataclass(slots=True)
class SimState:
    """Everything that changes during the run; plain lists so that it can be copied."""

    t: int = 0
    events: list[tuple[int, EventType, int, int]] = field(default_factory=list)  # heap: (t, type, seq, op)
    seq: int = 0  # insertion counter: deterministic order among equal (t, type)
    running: list[int | None] = field(default_factory=list)  # per machine: running op
    start: list[int | None] = field(default_factory=list)  # per op: actual start
    end: list[int | None] = field(default_factory=list)  # per op: actual completion

    def push(self, t: int, kind: EventType, o: int) -> None:
        heapq.heappush(self.events, (t, kind, self.seq, o))
        self.seq += 1


@dataclass(frozen=True, slots=True)
class SimResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # one record per event: t, type, order_id, op_id, machine


def replay(ci: CompiledInstance, plan: Sequence[Assignment]) -> SimResult:
    """Execute the plan event by event; raise PlanNotExecutable if it cannot run as planned."""
    machine, planned_start = _index_plan(ci, plan)
    duration = [dict(opts)[machine[o]] for o, opts in enumerate(ci.options)]

    state = SimState(
        running=[None] * ci.n_machines,
        start=[None] * ci.n_ops, end=[None] * ci.n_ops,
    )
    for o in range(ci.n_ops):
        state.push(planned_start[o], EventType.START, o)

    log: list[dict] = []
    while state.events:
        t, kind, _, o = heapq.heappop(state.events)
        state.t, m = t, machine[o]
        if kind is EventType.START:
            # v1 has no disturbances, so a plan that cannot start on time is an error; with disturbances
            # this check becomes "wait until the operation can start" (math/13_des.md, section 6)
            if reason := _blocked(ci, state, o, m):
                raise PlanNotExecutable(f"{ci.op_keys[o]} cannot start at {t} on {ci.machine_ids[m]}: {reason}")
            state.running[m], state.start[o] = o, t
            state.push(t + duration[o], EventType.COMPLETE, o)
        else:
            state.running[m], state.end[o] = None, t
        order_id, op_id = ci.op_keys[o]
        log.append({"t": t, "type": kind.name, "order_id": order_id, "op_id": op_id, "machine": ci.machine_ids[m]})

    schedule = [
        Assignment(order_id=k, op_id=j, machine=ci.machine_ids[machine[o]], start=state.start[o], end=state.end[o])
        for o, (k, j) in enumerate(ci.op_keys)
    ]
    return SimResult(schedule, log)


def _index_plan(ci: CompiledInstance, plan: Sequence[Assignment]) -> tuple[list[int], list[int]]:
    """Planned machine index and start per operation; every operation exactly once on an eligible machine."""
    machine: list[int | None] = [None] * ci.n_ops
    planned_start = [0] * ci.n_ops
    for a in plan:
        o = ci.op_index.get((a.order_id, a.op_id))
        m = ci.machine_index.get(a.machine)
        if o is None:
            raise PlanNotExecutable(f"{(a.order_id, a.op_id)} is not an operation of the instance")
        if machine[o] is not None:
            raise PlanNotExecutable(f"{ci.op_keys[o]} is planned more than once")
        if m is None or m not in dict(ci.options[o]):
            raise PlanNotExecutable(f"{ci.op_keys[o]} is planned on {a.machine}, which is not eligible")
        machine[o], planned_start[o] = m, a.start
    if missing := [ci.op_keys[o] for o in range(ci.n_ops) if machine[o] is None]:
        raise PlanNotExecutable(f"operations missing from the plan: {missing}")
    return machine, planned_start


def _blocked(ci: CompiledInstance, state: SimState, o: int, m: int) -> str | None:
    """Why operation o cannot start now on machine m, or None if it can."""
    if state.t < ci.release[o]:
        return f"before release {ci.release[o]}"
    if waiting := [ci.op_keys[q] for q in ci.predecessors[o] if state.end[q] is None]:
        return f"predecessors not finished: {waiting}"
    if state.running[m] is not None:
        return f"machine busy with {ci.op_keys[state.running[m]]}"
    return None
