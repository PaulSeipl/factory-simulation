"""Discrete-event simulation of the factory (math/13_des.md).

The DES executes the current plan under the disturbances of a scenario; it decides nothing. Every
operation runs on its planned machine, in the planned order per machine (no overtaking). It is ready
when its predecessors are finished, its machine is free, it is next on that machine and its order is
released. An early start offset releases it before its planned start (it starts once ready); a late
start offset delays the start by that many minutes after the operation has reached its planned start
and is ready (the worker comes late, counted once). Realized durations come from the scenario.

A batch (operations of a batch step planned on one machine with the same start, e.g. carriers in one oven run)
starts jointly once all its operations are ready; the program fixes its duration, so scenario factors do not
apply to it (math/03_carriers.md).

Workers (math/04_workers.md): every worker share is served by its planned worker, in the planned order per
worker (no overtaking). A whole share or a prefix starts with the operation, which therefore also waits for those
workers; a suffix (oven removal) starts when the machine part ends, or later when its worker is still busy: the
operation then ends later (oven overstay, logged). A batch's shares count once. Operations without machine wait
only for their predecessors and workers. Realized durations: everything scales with the scenario factor except the
rest of a machine-less operation and fixed programs (oven batch).

Work calendar: a worker starts a share only on a working day, from shift start, outside a due or running break,
and only if its planned length fits before shift end + max overtime (otherwise it waits for the next possible
time); a share that then runs longer is finished (overrun). Planned breaks are taken at their planned start, or
right after the current share if the worker is busy (postponed individually); no break is invented for days
without a planned one.

A running operation that has not completed by its expected end (planned duration; afterwards every minute)
raises an OVERDUE event. It changes nothing in the factory; it only gives the planning tool a time point at
which it sees the overrun, as an MES would report it.

Changing the plan is the job of the planning tool (repair, complete rescheduling): it reads the
snapshot and hands a new plan to `Simulation.update_plan` between processing the events of a time
point and starting operations (simulation.control.rescheduling).
"""

import heapq
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum

from simulation.calendar import day_index, day_start, is_working_day, minute_of_day
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance, share_interval
from simulation.model.schedule import Assignment, Break
from simulation.sim.scenario import Scenario, factors_by_index, realized_duration
from simulation.sim.snapshot import Snapshot, snapshot

NO_MACHINE = -1  # machine index of an operation without machine
_SHARES = 4  # share events carry op * _SHARES + share index (an operation has at most 3 shares)


class EventType(IntEnum):
    # value = priority at equal time: completions free machines and workers first
    COMPLETE = 0
    SHARE_END = 1  # a worker share ends: the worker is free
    SUFFIX_DUE = 2  # the machine part of an operation with a suffix ends: its removal can start
    LATE_START = 3  # a late start offset has elapsed: the waiting operation starts now
    PLANNED_START = 4  # planned start + min(offset, 0) reached; ignored if the plan has moved it since
    OVERDUE = 5  # a running operation has passed its expected end; ignored if it has completed
    WAKE = 6  # a time point requested by the planning tool (e.g. periodic rescheduling); no effect in the factory


class PlanNotExecutable(ValueError):
    pass


@dataclass(slots=True)
class SimState:
    """Everything that changes during the run; plain containers so that it can be copied."""

    t: int = 0
    events: list[tuple[int, EventType, int, int]] = field(default_factory=list)  # heap: (t, type, seq, op)
    seq: int = 0  # insertion counter: deterministic order among equal (t, type)
    machine: list[int] = field(default_factory=list)  # current plan: machine per op (NO_MACHINE: none)
    order_on: list[list[int]] = field(default_factory=list)  # current plan: order of the ops per machine
    planned_start: list[int] = field(default_factory=list)  # current plan: start and end per op
    planned_end: list[int] = field(default_factory=list)
    planned_start_at: list[int | None] = field(default_factory=list)  # per op: pending PLANNED_START, None once done
    running: list[int | None] = field(default_factory=list)  # per machine: running op
    next_pos: list[int] = field(default_factory=list)  # per machine: position of the next op in its planned order
    released: set[int] = field(default_factory=set)  # released to the shop floor, not started yet
    late_start_at: list[int | None] = field(default_factory=list)  # per op: start time after a late offset
    batch: list[tuple[int, ...]] = field(default_factory=list)  # per op: its planned batch, (o,) if none
    start: list[int | None] = field(default_factory=list)  # per op: actual start
    end: list[int | None] = field(default_factory=list)  # per op: actual completion
    worker: list[list[int]] = field(default_factory=list)  # current plan: worker idx per share of each op
    worker_order: list[list[tuple[int, int]]] = field(default_factory=list)  # per worker: planned (op, share)
    worker_next: list[int] = field(default_factory=list)  # per worker: position of its next share
    worker_on: list[tuple[int, int] | None] = field(default_factory=list)  # per worker: share it works on
    share_done: set[tuple[int, int]] = field(default_factory=set)
    started_batch: dict[int, tuple[int, ...]] = field(default_factory=dict)  # first op -> its started batch
    followers: set[int] = field(default_factory=set)  # started batch members whose shares the first one carries
    suffix_due: dict[int, int] = field(default_factory=dict)  # op -> time its removal became due (waiting)
    break_until: list[int] = field(default_factory=list)  # per worker: end of its current break
    pending_breaks: list[list[tuple[int, int]]] = field(default_factory=list)  # per worker: (planned start, idx)
    break_start: list[int | None] = field(default_factory=list)  # per planned break: realized start
    wakes: set[int] = field(default_factory=set)  # time points pushed for waiting workers

    def push(self, t: int, kind: EventType, o: int) -> None:
        heapq.heappush(self.events, (t, kind, self.seq, o))
        self.seq += 1


@dataclass(frozen=True, slots=True)
class SimResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # START and COMPLETE per op (t, type, order_id, op_id, machine); OVERSTAY with minutes
    breaks: tuple[Break, ...] = ()  # breaks of the workers


class Simulation:
    """The factory, executing the current plan event by event."""

    def __init__(
        self, ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None,
        breaks: Iterable[Break] = (),
    ):
        self.breaks = tuple(breaks)
        # waiting would silently repair a broken plan, so it is validated first (C1-C5, C11-C14)
        if violations := check_schedule(ci, plan, breaks=self.breaks):
            raise PlanNotExecutable(_describe(violations))
        self.ci = ci
        self.log: list[dict] = []
        disturbance = factors_by_index(ci, scenario) if scenario else None
        # a batch step's program fixes its duration: no deviation
        self.factor = [1.0 if ci.batch_capacity[o] > 1 else d.factor for o, d in enumerate(disturbance)] \
            if disturbance else [1.0] * ci.n_ops
        self.offset = [d.start_offset for d in disturbance] if disturbance else [0] * ci.n_ops
        n_w = len(ci.worker_ids)
        self.state = SimState(
            machine=[0] * ci.n_ops, planned_start=[0] * ci.n_ops, planned_end=[0] * ci.n_ops,
            planned_start_at=[None] * ci.n_ops, running=[None] * ci.n_machines, start=[None] * ci.n_ops,
            end=[None] * ci.n_ops, late_start_at=[None] * ci.n_ops, batch=[(o,) for o in range(ci.n_ops)],
            worker=[[] for _ in range(ci.n_ops)], worker_on=[None] * n_w, break_until=[0] * n_w,
            pending_breaks=[[] for _ in range(n_w)], break_start=[None] * len(self.breaks),
        )
        for idx, b in sorted(enumerate(self.breaks), key=lambda ib: ib[1].start):
            self.state.pending_breaks[ci.worker_ids.index(b.worker)].append((b.start, idx))
            self._wake(b.start)
        self.duration = [0] * ci.n_ops  # realized durations on the currently planned machines
        self.share_len: list[list[int]] = [[] for _ in range(ci.n_ops)]  # realized share lengths
        self._apply(plan)
        for o in range(ci.n_ops):
            self._set_planned_start(o)

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
                if (m := state.machine[o]) != NO_MACHINE:
                    state.running[m] = None
                    state.next_pos[m] += 1
                state.end[o] = state.t
                self._record("COMPLETE", o)
            elif kind is EventType.SHARE_END:
                o, i = divmod(o, _SHARES)
                w = state.worker[o][i]
                state.worker_on[w] = None
                state.worker_next[w] += 1
                state.share_done.add((o, i))
            elif kind is EventType.SUFFIX_DUE:
                state.suffix_due[o] = state.t
            elif kind is EventType.LATE_START:
                pass  # only marks the time point; the start step starts the operation
            elif kind is EventType.WAKE:
                state.wakes.discard(state.t)
            elif kind is EventType.OVERDUE:
                if state.end[o] is None:  # still running: the snapshot now expects its end at t + 1
                    state.push(state.t + 1, EventType.OVERDUE, o)
            elif state.planned_start_at[o] == state.t:  # PLANNED_START moved by a plan update: stale, skipped
                self._on_planned_start(o)
        return state.t

    def start_operations(self) -> None:
        """Start every released operation that can start now, and every due removal (suffix) whose worker is
        free (a start cannot enable another one: p >= 1).

        A batch is handled by its first operation and starts only when all its operations are ready; a late
        start offset of any of them delays the whole batch (the largest one counts).
        """
        state = self.state
        self._take_breaks()
        for o in sorted(state.suffix_due):
            i = self._suffix(o)
            if self._worker_ready(o, i):
                self._start_share(o, i)
                for q in state.started_batch[o]:
                    state.push(state.t + self.share_len[o][i], EventType.COMPLETE, q)
                if minutes := state.t - state.suffix_due.pop(o):
                    self._record("OVERSTAY", o, minutes=minutes)
        for o in sorted(state.released):
            m, batch = state.machine[o], state.batch[o]
            if (
                o == batch[0]
                and (m == NO_MACHINE or (state.running[m] is None and state.order_on[m][state.next_pos[m]] == o))
                and all(q in state.released and state.t >= self.ci.release[q]
                        and all(state.end[p] is not None for p in self.ci.predecessors[q]) for q in batch)
                and all(self._worker_ready(o, i) for i, s in enumerate(self.ci.shares[o]) if s.kind != "suffix")
            ):
                offset = max(self.offset[q] for q in batch)
                if offset > 0 and state.late_start_at[o] is None:
                    # planned start reached and ready: the worker comes offset minutes later, machine stays reserved
                    state.late_start_at[o] = state.t + offset
                    state.push(state.late_start_at[o], EventType.LATE_START, o)
                if state.late_start_at[o] is not None and state.t < state.late_start_at[o]:
                    continue
                self._start(batch)

    def check_completed(self) -> None:
        if any(e is None for e in self.state.end):
            # cannot happen for a feasible plan: waiting only shifts operations to the right
            raise RuntimeError("operations never completed")

    # --- interface to the planning tool ----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return snapshot(self.ci, self.current_plan(), self.state, self.breaks)

    def current_plan(self) -> list[Assignment]:
        """The plan the factory currently executes (the one last sent to it)."""
        s = self.state
        return [Assignment(order_id=k, op_id=j, machine=self._machine_id(o), start=s.planned_start[o],
                           end=s.planned_end[o], workers=self._worker_ids(o))
                for o, (k, j) in enumerate(self.ci.op_keys)]

    def update_plan(self, plan: Sequence[Assignment]) -> None:
        """Replace the current plan; it must respect the frozen part (C1-C7 against the snapshot)."""
        if violations := check_schedule(self.ci, plan, self.snapshot()):
            raise PlanNotExecutable(_describe(violations))
        self._apply(plan)
        for o in range(self.ci.n_ops):
            pending = self.state.planned_start_at[o]
            if pending is not None and self._planned_start_time(o) != pending:  # released ops are not moved any more
                self._set_planned_start(o)
                if self.state.planned_start_at[o] == self.state.t:
                    self._on_planned_start(o)

    def wake_at(self, t: int) -> None:
        """Make t a time point of the run, so that the planning tool is called then (no effect in the factory)."""
        self.state.push(t, EventType.WAKE, -1)

    def realized_breaks(self) -> tuple[Break, ...]:
        """Breaks as taken (in the order of the planned ones); a break never taken (run ended before) is left out."""
        return tuple(Break(worker=b.worker, start=t) for b, t in zip(self.breaks, self.state.break_start, strict=True)
                     if t is not None)

    @property
    def has_unstarted(self) -> bool:
        return any(s is None for s in self.state.start)

    def realized(self) -> list[Assignment]:
        s = self.state
        return [Assignment(order_id=k, op_id=j, machine=self._machine_id(o), start=s.start[o], end=s.end[o],
                           workers=self._worker_ids(o), share_lengths=tuple(self.share_len[o]))
                for o, (k, j) in enumerate(self.ci.op_keys)]

    # --- internals ---------------------------------------------------------------------------------

    def _apply(self, plan: Sequence[Assignment]) -> None:
        """Machine, workers, planned times, order per machine and per worker, and realized durations of the
        operations not started."""
        ci, s = self.ci, self.state
        worker_index = {w: i for i, w in enumerate(ci.worker_ids)}
        for a in plan:
            o = ci.op_index[a.order_id, a.op_id]
            s.planned_start[o], s.planned_end[o] = a.start, a.end
            if s.start[o] is None:
                s.machine[o] = NO_MACHINE if a.machine is None else ci.machine_index[a.machine]
                s.worker[o] = [worker_index[w] for w in a.workers]
                self.duration[o], self.share_len[o] = self._realized(o)
        s.order_on = [[] for _ in range(ci.n_machines)]
        for o in sorted(range(ci.n_ops), key=lambda o: (s.planned_start[o], o)):
            if s.machine[o] != NO_MACHINE:
                s.order_on[s.machine[o]].append(o)
        s.batch = list(planned_batches(ci, s.machine, s.planned_start, s.start))
        s.next_pos = [sum(s.end[o] is not None for o in ops) for ops in s.order_on]
        # a batch's shares are carried by its first operation (planned, or started)
        carriers = [o for o in range(ci.n_ops) if o not in s.followers and s.batch[o][0] == o]
        planned = sorted((share_interval(sh, s.planned_start[o], s.planned_end[o])[0], o, i)
                         for o in carriers for i, sh in enumerate(ci.shares[o]))
        s.worker_order = [[] for _ in ci.worker_ids]
        for _, o, i in planned:
            s.worker_order[s.worker[o][i]].append((o, i))
        s.worker_next = [sum(share in s.share_done for share in shares) for shares in s.worker_order]

    def _realized(self, o: int) -> tuple[int, list[int]]:
        """Realized duration and share lengths: everything scales with the factor except the rest of a machine-less
        operation (math/22_scenarios.md)."""
        ci, f, shares = self.ci, self.factor[o], self.ci.shares[o]
        if (m := self.state.machine[o]) == NO_MACHINE and not any(sh.kind == "whole" for sh in shares):
            lengths = [realized_duration(sh.length, f) for sh in shares]
            return ci.fixed_duration[o] - sum(sh.length for sh in shares) + sum(lengths), lengths
        p = realized_duration(ci.fixed_duration[o] if m == NO_MACHINE else dict(ci.options[o])[m], f)
        lengths = [p if sh.kind == "whole" else realized_duration(sh.length, f) for sh in shares]
        if (excess := sum(lengths) - p) > 0 and len(lengths) == 2:  # prefix + suffix longer than the operation
            lengths[1] -= excess
        return p, [min(n, p) for n in lengths]

    def _planned_duration(self, o: int) -> int:
        m = self.state.machine[o]
        return self.ci.fixed_duration[o] if m == NO_MACHINE else dict(self.ci.options[o])[m]

    def _suffix(self, o: int) -> int | None:
        return next((i for i, sh in enumerate(self.ci.shares[o]) if sh.kind == "suffix"), None)

    def _worker_ready(self, o: int, i: int) -> bool:
        """Called only when the share is due (the operation can start, or its machine part has ended)."""
        s = self.state
        if s.worker_on[s.worker[o][i]] is not None or s.break_until[s.worker[o][i]] > s.t:
            self._swap(o, i)  # planned worker busy: a free one may step in (swap rule)
        w = s.worker[o][i]
        return (s.worker_on[w] is None and s.worker_order[w][s.worker_next[w]] == (o, i) and self._free_now(w)
                and self._in_shift(self._planned_share_length(o, i)))

    def _swap(self, o: int, i: int) -> None:
        """Swap rule (spec §6, math/13_des.md): a qualified worker who is free now and may work now, and whose next
        planned share starts no earlier than now + the planned share length, takes the share; most room first,
        then the lowest worker index. Judged on planned lengths only (no leakage)."""
        s, length = self.state, self._planned_share_length(o, i)
        planned = s.worker[o][i]
        if self.ci.calendar and not self._fits_shift(length):
            return  # nobody may start it now
        best, best_room = None, -1
        for v in self.ci.shares[o][i].workers:
            if v == planned or s.worker_on[v] is not None or not self._free_now(v):
                continue
            rest = s.worker_order[v][s.worker_next[v]:]
            next_start = self._planned_share_start(*rest[0]) if rest else float("inf")
            if next_start >= s.t + length and next_start - s.t > best_room:
                best, best_room = v, next_start - s.t
        if best is None:
            return
        s.worker_order[planned].remove((o, i))
        s.worker_order[best].insert(s.worker_next[best], (o, i))
        for q in s.started_batch.get(o, s.batch[o]):  # every member of a batch carries the same workers
            s.worker[q][i] = best
        self._record("SWAP", o, share=self.ci.shares[o][i].kind, planned=self.ci.worker_ids[planned],
                     actual=self.ci.worker_ids[best])

    def _planned_share_start(self, o: int, i: int) -> int:
        return share_interval(self.ci.shares[o][i], self.state.planned_start[o], self.state.planned_end[o])[0]

    def _fits_shift(self, length: int) -> bool:
        cal, t = self.ci.calendar, self.state.t
        d = day_index(cal, t)
        return (is_working_day(cal, d) and minute_of_day(cal, t) >= cal.shift_start
                and t + length <= day_start(cal, d) + cal.shift_end + cal.max_overtime)

    def _free_now(self, w: int) -> bool:
        """Not on a break and no break due (a due break is taken first)."""
        s = self.state
        return s.break_until[w] <= s.t and not (s.pending_breaks[w] and s.pending_breaks[w][0][0] <= s.t)

    def _in_shift(self, length: int) -> bool:
        """With a calendar: now is a working day, at or after shift start, and `length` fits before shift end + max
        overtime; otherwise a wake-up is pushed for the next possible start."""
        if (cal := self.ci.calendar) is None:
            return True
        if self._fits_shift(length):
            return True
        t = self.state.t
        d = day_index(cal, t)
        if not (is_working_day(cal, d) and minute_of_day(cal, t) < cal.shift_start):
            d = next(e for e in range(d + 1, d + 8) if is_working_day(cal, e))
        self._wake(day_start(cal, d) + cal.shift_start)
        return False

    def _planned_share_length(self, o: int, i: int) -> int:
        sh = self.ci.shares[o][i]
        return self._planned_duration(o) if sh.kind == "whole" else sh.length

    def _take_breaks(self) -> None:
        s = self.state
        for w, pending in enumerate(s.pending_breaks):
            if pending and pending[0][0] <= s.t and s.worker_on[w] is None and s.break_until[w] <= s.t:
                _, idx = pending.pop(0)
                s.break_start[idx], s.break_until[w] = s.t, s.t + self.ci.calendar.break_length
                self._wake(s.break_until[w])

    def _wake(self, t: int) -> None:
        if t not in self.state.wakes:
            self.state.wakes.add(t)
            self.state.push(t, EventType.WAKE, -1)

    def _start_share(self, o: int, i: int) -> None:
        self.state.worker_on[self.state.worker[o][i]] = (o, i)
        self.state.push(self.state.t + self.share_len[o][i], EventType.SHARE_END, o * _SHARES + i)

    def _start(self, batch: tuple[int, ...]) -> None:
        state, first = self.state, batch[0]
        for q in batch:
            state.released.remove(q)
            if (m := state.machine[q]) != NO_MACHINE:
                state.running[m] = q
            state.start[q] = state.t
            # expected end from the planned duration, never from the scenario (snapshot, no leakage)
            state.push(state.t + self._planned_duration(q), EventType.OVERDUE, q)
            self._record("START", q)
        state.started_batch[first] = batch
        state.followers.update(batch[1:])
        for i, sh in enumerate(self.ci.shares[first]):
            if sh.kind != "suffix":
                self._start_share(first, i)
        if (i := self._suffix(first)) is None:
            for q in batch:
                state.push(state.t + self.duration[q], EventType.COMPLETE, q)
        else:  # the removal starts when the machine part ends, or when its worker is free
            state.push(state.t + self.duration[first] - self.share_len[first][i], EventType.SUFFIX_DUE, first)

    def _machine_id(self, o: int) -> str | None:
        m = self.state.machine[o]
        return None if m == NO_MACHINE else self.ci.machine_ids[m]

    def _worker_ids(self, o: int) -> tuple[str, ...]:
        return tuple(self.ci.worker_ids[w] for w in self.state.worker[o])

    def _planned_start_time(self, o: int) -> int:
        return max(self.state.planned_start[o] + min(self.offset[o], 0), self.state.t)

    def _set_planned_start(self, o: int) -> None:
        """(Re)schedule the PLANNED_START event of a pending operation; earlier ones of it become stale."""
        self.state.planned_start_at[o] = self._planned_start_time(o)
        self.state.push(self.state.planned_start_at[o], EventType.PLANNED_START, o)

    def _on_planned_start(self, o: int) -> None:
        self.state.planned_start_at[o] = None
        self.state.released.add(o)

    def _record(self, kind: str, o: int, **extra) -> None:
        order_id, op_id = self.ci.op_keys[o]
        self.log.append({"t": self.state.t, "type": kind, "order_id": order_id, "op_id": op_id,
                         "machine": self._machine_id(o), **extra})


def planned_batches(
    ci: CompiledInstance, machine: Sequence[int], planned_start: Sequence[int], start: Sequence[int | None]
) -> list[tuple[int, ...]]:
    """Per operation its batch: not started operations of a batch step with the same machine and planned start."""
    groups: dict[tuple[int, int], list[int]] = {}
    for o in range(ci.n_ops):
        if ci.batch_capacity[o] > 1 and start[o] is None:
            groups.setdefault((machine[o], planned_start[o]), []).append(o)
    batch = [(o,) for o in range(ci.n_ops)]
    for ops in groups.values():
        for o in ops:
            batch[o] = tuple(ops)
    return batch


def _describe(violations) -> str:
    return "\n".join(f"[{v.constraint}] {v.message}" for v in violations)


def run(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None, until: int | None = None
) -> tuple[SimState, list[dict]]:
    """Execute the plan without a planning tool up to time point `until`; return state and log."""
    sim = Simulation(ci, plan, scenario)
    sim.run(until)
    return sim.state, sim.log


def replay(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None, breaks: Iterable[Break] = ()
) -> SimResult:
    """Execute the whole plan without a planning tool; without a scenario the realized schedule equals the plan."""
    sim = Simulation(ci, plan, scenario, breaks)
    sim.run()
    return SimResult(sim.realized(), sim.log, sim.realized_breaks())
