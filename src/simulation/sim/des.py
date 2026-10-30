"""Discrete-event simulation of the factory (math/13_des.md).

The DES executes the current plan under the disturbances of a scenario; it decides nothing. Every
operation runs on its planned machine, in the planned order per machine (no overtaking). An operation
is released to the shop floor at its planned start shifted by its start offset (early or late) and
starts as soon as it is released, its predecessors are finished, its machine is free and its release
time has passed. Realized durations come from the scenario.

Changing the plan is the job of the planning tool (repair, complete rescheduling): it reads the
snapshot and hands a new plan to `Simulation.update_plan` between processing the events of a time
point and starting operations (simulation.control.rescheduling).
"""

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.sim.scenario import Scenario, factors_by_index, realized_duration
from simulation.sim.snapshot import Snapshot, snapshot


class EventType(IntEnum):
    # value = priority at equal time: completions free machines first
    COMPLETE = 0
    RELEASE = 1  # a late start offset has elapsed: the operation is released to the shop floor
    DUE = 2  # planned start + min(offset, 0) reached; ignored if the plan has moved it since


class PlanNotExecutable(ValueError):
    pass


@dataclass(slots=True)
class SimState:
    """Everything that changes during the run; plain containers so that it can be copied."""

    t: int = 0
    events: list[tuple[int, EventType, int, int]] = field(default_factory=list)  # heap: (t, type, seq, op)
    seq: int = 0  # insertion counter: deterministic order among equal (t, type)
    machine: list[int] = field(default_factory=list)  # current plan: machine per op
    order_on: list[list[int]] = field(default_factory=list)  # current plan: order of the ops per machine
    planned_start: list[int] = field(default_factory=list)  # current plan: start and end per op
    planned_end: list[int] = field(default_factory=list)
    due_at: list[int | None] = field(default_factory=list)  # per op: pending DUE time, None once processed
    running: list[int | None] = field(default_factory=list)  # per machine: running op
    next_pos: list[int] = field(default_factory=list)  # per machine: position of the next op in its planned order
    released: set[int] = field(default_factory=set)  # released to the shop floor, not started yet
    start: list[int | None] = field(default_factory=list)  # per op: actual start
    end: list[int | None] = field(default_factory=list)  # per op: actual completion

    def push(self, t: int, kind: EventType, o: int) -> None:
        heapq.heappush(self.events, (t, kind, self.seq, o))
        self.seq += 1


@dataclass(frozen=True, slots=True)
class SimResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # one START and one COMPLETE record per op: t, type, order_id, op_id, machine


class Simulation:
    """The factory, executing the current plan event by event."""

    def __init__(self, ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None):
        # waiting would silently repair a broken plan, so it is validated first (C1-C5)
        if violations := check_schedule(ci, plan):
            raise PlanNotExecutable(_describe(violations))
        self.ci = ci
        self.log: list[dict] = []
        disturbance = factors_by_index(ci, scenario) if scenario else None
        self.factor = [d.factor for d in disturbance] if disturbance else [1.0] * ci.n_ops
        self.offset = [d.start_offset for d in disturbance] if disturbance else [0] * ci.n_ops
        self.state = SimState(
            machine=[0] * ci.n_ops, planned_start=[0] * ci.n_ops, planned_end=[0] * ci.n_ops,
            due_at=[None] * ci.n_ops, running=[None] * ci.n_machines, start=[None] * ci.n_ops, end=[None] * ci.n_ops,
        )
        self.duration = [0] * ci.n_ops  # realized durations on the currently planned machines
        self._apply(plan)
        for o in range(ci.n_ops):
            self._set_due(o)

    # --- running ------------------------------------------------------------------------------

    @property
    def done(self) -> bool:
        return not self.state.events

    def run(self, until: int | None = None) -> None:
        """Without a planning tool: execute up to and including time point `until` (default: to the end)."""
        while self.state.events and (until is None or self.state.events[0][0] <= until):
            self.process_events()
            self.start_operations()
        if until is not None:
            self.state.t = until
        else:
            self.check_completed()

    def process_events(self) -> int:
        """Advance the clock to the next event time and process every event at that time."""
        state = self.state
        state.t = state.events[0][0]
        while state.events and state.events[0][0] == state.t:
            _, kind, _, o = heapq.heappop(state.events)
            if kind is EventType.COMPLETE:
                m = state.machine[o]
                state.running[m], state.end[o] = None, state.t
                state.next_pos[m] += 1
                self._record("COMPLETE", o)
            elif kind is EventType.RELEASE:
                state.released.add(o)
            elif state.due_at[o] == state.t:  # DUE events moved by a plan update are stale and skipped
                self._on_due(o)
        return state.t

    def start_operations(self) -> None:
        """Start every released operation that can start now (a start cannot enable another one: p >= 1)."""
        state = self.state
        for o in sorted(state.released):
            m = state.machine[o]
            if (
                state.t >= self.ci.release[o]
                and state.running[m] is None
                and state.order_on[m][state.next_pos[m]] == o
                and all(state.end[q] is not None for q in self.ci.predecessors[o])
            ):
                state.released.remove(o)
                state.running[m], state.start[o] = o, state.t
                state.push(state.t + self.duration[o], EventType.COMPLETE, o)
                self._record("START", o)

    def check_completed(self) -> None:
        if any(e is None for e in self.state.end):
            # cannot happen for a feasible plan: waiting only shifts operations to the right
            raise RuntimeError("operations never completed")

    # --- interface to the planning tool ----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return snapshot(self.ci, self.current_plan(), self.state)

    def current_plan(self) -> list[Assignment]:
        """The plan the factory currently executes (the one last sent to it)."""
        s = self.state
        return [Assignment(order_id=k, op_id=j, machine=self.ci.machine_ids[s.machine[o]], start=s.planned_start[o],
                           end=s.planned_end[o])
                for o, (k, j) in enumerate(self.ci.op_keys)]

    def update_plan(self, plan: Sequence[Assignment]) -> None:
        """Replace the current plan; it must respect the frozen part (C1-C7 against the snapshot)."""
        if violations := check_schedule(self.ci, plan, self.snapshot()):
            raise PlanNotExecutable(_describe(violations))
        self._apply(plan)
        for o in range(self.ci.n_ops):
            due = self.state.due_at[o]
            if due is not None and self._due_time(o) != due:  # released ops are not moved any more
                self._set_due(o)
                if self.state.due_at[o] == self.state.t:
                    self._on_due(o)

    def realized(self) -> list[Assignment]:
        s = self.state
        return [Assignment(order_id=k, op_id=j, machine=self.ci.machine_ids[s.machine[o]], start=s.start[o],
                           end=s.end[o])
                for o, (k, j) in enumerate(self.ci.op_keys)]

    # --- internals ---------------------------------------------------------------------------------

    def _apply(self, plan: Sequence[Assignment]) -> None:
        """Machine, planned times, order per machine and realized durations of the operations not started."""
        ci, s = self.ci, self.state
        for a in plan:
            o = ci.op_index[a.order_id, a.op_id]
            s.planned_start[o], s.planned_end[o] = a.start, a.end
            if s.start[o] is None:
                s.machine[o] = ci.machine_index[a.machine]
                self.duration[o] = realized_duration(dict(ci.options[o])[s.machine[o]], self.factor[o])
        s.order_on = [[] for _ in range(ci.n_machines)]
        for o in sorted(range(ci.n_ops), key=lambda o: (s.planned_start[o], o)):
            s.order_on[s.machine[o]].append(o)
        s.next_pos = [sum(s.end[o] is not None for o in ops) for ops in s.order_on]

    def _due_time(self, o: int) -> int:
        return max(self.state.planned_start[o] + min(self.offset[o], 0), self.state.t)

    def _set_due(self, o: int) -> None:
        """(Re)schedule the DUE event of a pending operation; earlier DUE events of it become stale."""
        self.state.due_at[o] = self._due_time(o)
        self.state.push(self.state.due_at[o], EventType.DUE, o)

    def _on_due(self, o: int) -> None:
        self.state.due_at[o] = None
        if self.offset[o] > 0:  # a late start is fixed once, relative to the planned start reached now
            self.state.push(self.state.t + self.offset[o], EventType.RELEASE, o)
        else:
            self.state.released.add(o)

    def _record(self, kind: str, o: int) -> None:
        order_id, op_id = self.ci.op_keys[o]
        self.log.append({"t": self.state.t, "type": kind, "order_id": order_id, "op_id": op_id,
                         "machine": self.ci.machine_ids[self.state.machine[o]]})


def _describe(violations) -> str:
    return "\n".join(f"[{v.constraint}] {v.message}" for v in violations)


def run(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None, until: int | None = None
) -> tuple[SimState, list[dict]]:
    """Execute the plan without a planning tool up to time point `until`; return state and log."""
    sim = Simulation(ci, plan, scenario)
    sim.run(until)
    return sim.state, sim.log


def replay(ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None) -> SimResult:
    """Execute the whole plan without a planning tool; without a scenario the realized schedule equals the plan."""
    sim = Simulation(ci, plan, scenario)
    sim.run()
    return SimResult(sim.realized(), sim.log)
