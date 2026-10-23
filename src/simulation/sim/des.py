"""Discrete-event simulation of plan execution (math/13_des.md).

The DES executes a plan; it decides nothing. Every operation runs on its planned machine, in the
planned order per machine, and starts at its planned time or, if the plan has been delayed by
disturbances, as soon as its predecessors and its machine allow (never earlier than planned).
Realized durations come from an optional disturbance scenario.
"""

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.sim.scenario import Scenario, factors_by_index, realized_duration


class EventType(IntEnum):
    # value = priority at equal time: completions are processed before operations become due
    COMPLETE = 0
    DUE = 1  # planned start reached


class PlanNotExecutable(ValueError):
    pass


@dataclass(slots=True)
class SimState:
    """Everything that changes during the run; plain containers so that it can be copied."""

    t: int = 0
    events: list[tuple[int, EventType, int, int]] = field(default_factory=list)  # heap: (t, type, seq, op)
    seq: int = 0  # insertion counter: deterministic order among equal (t, type)
    running: list[int | None] = field(default_factory=list)  # per machine: running op
    next_pos: list[int] = field(default_factory=list)  # per machine: position of the next op in its planned order
    due: set[int] = field(default_factory=set)  # ops whose planned start has passed but which have not started
    start: list[int | None] = field(default_factory=list)  # per op: actual start
    end: list[int | None] = field(default_factory=list)  # per op: actual completion

    def push(self, t: int, kind: EventType, o: int) -> None:
        heapq.heappush(self.events, (t, kind, self.seq, o))
        self.seq += 1


@dataclass(frozen=True, slots=True)
class SimResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # one record per START and COMPLETE: t, type, order_id, op_id, machine


def replay(ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None) -> SimResult:
    """Execute the whole plan; without a scenario the realized schedule equals the plan."""
    state, log = run(ci, plan, scenario)
    machine = {(a.order_id, a.op_id): a.machine for a in plan}
    schedule = [
        Assignment(order_id=k, op_id=j, machine=machine[k, j], start=state.start[o], end=state.end[o])
        for o, (k, j) in enumerate(ci.op_keys)
    ]
    return SimResult(schedule, log)


def run(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None, until: int | None = None
) -> tuple[SimState, list[dict]]:
    """Execute the plan event by event, up to and including time point `until` (default: to the end).

    The returned state is the factory after all events and starts at `until` (state.t == until).
    """
    # waiting would silently repair a broken plan, so it is validated first (C1-C5)
    if violations := check_schedule(ci, plan):
        raise PlanNotExecutable("\n".join(f"[{v.constraint}] {v.message}" for v in violations))
    machine = [0] * ci.n_ops
    planned_start = [0] * ci.n_ops
    for a in plan:
        o = ci.op_index[a.order_id, a.op_id]
        machine[o], planned_start[o] = ci.machine_index[a.machine], a.start
    order_on: list[list[int]] = [[] for _ in range(ci.n_machines)]  # planned order per machine
    for o in sorted(range(ci.n_ops), key=lambda o: planned_start[o]):
        order_on[machine[o]].append(o)
    factor = factors_by_index(ci, scenario) if scenario else [1.0] * ci.n_ops
    duration = [realized_duration(dict(ci.options[o])[machine[o]], factor[o]) for o in range(ci.n_ops)]

    state = SimState(
        running=[None] * ci.n_machines, next_pos=[0] * ci.n_machines,
        start=[None] * ci.n_ops, end=[None] * ci.n_ops,
    )
    for o in range(ci.n_ops):
        state.push(planned_start[o], EventType.DUE, o)

    log: list[dict] = []

    def record(kind: str, o: int) -> None:
        order_id, op_id = ci.op_keys[o]
        log.append({"t": state.t, "type": kind, "order_id": order_id, "op_id": op_id,
                    "machine": ci.machine_ids[machine[o]]})

    while state.events and (until is None or state.events[0][0] <= until):
        state.t = state.events[0][0]
        # 1. process every event at time t
        while state.events and state.events[0][0] == state.t:
            _, kind, _, o = heapq.heappop(state.events)
            if kind is EventType.COMPLETE:
                m = machine[o]
                state.running[m], state.end[o] = None, state.t
                state.next_pos[m] += 1
                record("COMPLETE", o)
            else:
                state.due.add(o)
        # 2. then start every due operation that can start (a start cannot enable another one at t: p >= 1)
        for o in sorted(state.due):
            m = machine[o]
            if (
                state.running[m] is None
                and order_on[m][state.next_pos[m]] == o
                and all(state.end[q] is not None for q in ci.predecessors[o])
            ):
                state.due.remove(o)
                state.running[m], state.start[o] = o, state.t
                state.push(state.t + duration[o], EventType.COMPLETE, o)
                record("START", o)

    if until is not None:
        state.t = until
    elif state.due:  # cannot happen for a feasible plan: waiting only shifts operations to the right
        raise RuntimeError(f"operations never started: {[ci.op_keys[o] for o in sorted(state.due)]}")
    return state, log
