"""Dispatching with a sequencing rule and an optional assignment rule (math/11_dispatching-rules.md).

With an assignment rule:
  when an operation becomes ready (all predecessors scheduled), the assignment rule fixes its
  machine; at every step the earliest possible start t over all ready operations on their
  assigned machines is computed, and among those that can start at t the sequencing rule picks one.
Without an assignment rule ("joint"):
  the earliest possible start t is taken over all (ready operation, eligible machine) pairs, and
  the sequencing rule ranks the pairs that can start at t, i.e. it chooses operation and machine.

Both variants are non-delay: a machine never stays idle while a candidate could start on it. With a delay per
scheduling iteration (the GA's decoder, math/14_genetic-algorithm.md), iteration ζ ranks every candidate that can
start by t + D_ζ, and the chosen one starts at its own earliest start: parameterized active schedules (Gonçalves et
al. 2005). A later lead lets operations ready by its start join its batch.

A batch step (e.g. oven) is batched greedily: when an operation of it is chosen at time t on machine m, the
other operations of a batch step that are ready by t and may use m with the same duration join it, in the order of
the sequencing rule, up to the capacity.

A run (setup, main operation, removal; math/03_carriers.md) is dispatched as one unit: its first operation stands for
the whole run, and when it is chosen the run's operations are placed back to back on one machine (C8, C9).

Workers (math/04_workers.md): every share (whole, prefix, suffix) gets one qualified worker. The
earliest start of a candidate also waits until every share finds a worker free for its interval (gap search in the
worker's busy intervals: an oven removal planned later leaves its worker free in between); per share the free
worker with the least worker load wins, then the lowest index. A batch's shares are planned once and all members
carry the same workers; the parts of a run are placed one after the other on its machine, each part as soon as its
workers allow (the machine stays blocked in between, C9). Operations without machine wait only for their workers.
With a calendar, shares lie within the shift without overtime (the GA's decoder may give an operation an overtime
allowance, math/14_genetic-algorithm.md) and outside the worker's break that day; the break
starts at the earliest break start, or later if the frozen part forces it (snapshot's day: not before t, after a
running share; a pending removal comes first), and dispatch_plan returns these breaks. Machines run at any time,
so a print may run overnight and its removal waits until the morning.

From a snapshot (rescheduling, math/05_rescheduling-frozen-part.md): the frozen operations are kept as
they are, their machines are busy until their (expected) end, and nothing new starts before snapshot.t. Their
started shares keep their workers and occupy them (C7); a pending share of a frozen operation (the removal of a
running oven) gets a worker by the rule above, the same for the whole batch, at its expected time, or, if no
qualified worker is free then (a disturbance), at the earliest time one is: the operation then ends later (forced
overstay; computed as the checker does, with overtime and blocked only by the frozen part, C7^o). The breaks
started by t are kept (C7^b); a break of the snapshot's day not yet started is planned anew.
"""

from bisect import bisect_left, insort
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from simulation.calendar import WEEK, day_index, day_start, shift_window
from simulation.model.compiled import CompiledInstance, Share, batch_key, s_batch_length, share_interval
from simulation.model.schedule import Assignment, Break, Plan
from simulation.objectives import MAKESPAN, Objective
from simulation.planners.repair import forced_removals

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
    """The rule plan's assignments; `dispatch_plan` also returns its breaks."""
    return dispatch_plan(ci, sequencing, assignment, snapshot).assignments


def dispatch_plan(
    ci: CompiledInstance,
    sequencing: SequencingRule,
    assignment: AssignmentRule | None = None,
    snapshot: Snapshot | None = None,
    delay: Sequence[int] | None = None,
    overtime: Sequence[int] | None = None,
) -> Plan:
    """The rule plan with the breaks it booked (empty without a calendar or without workers). `delay[ζ]`: minutes
    iteration ζ may look past the earliest start (one entry per operation is enough: an iteration places at least
    one); None: non-delay. `overtime[o]`: minutes past shift end that o's new shares may use (at most the calendar's
    maximum overtime; an s-batch uses its chosen operation's); None: no overtime, as for the rules."""
    if overtime is not None and ci.calendar is not None and max(overtime, default=0) > ci.calendar.max_overtime:
        raise ValueError(f"overtime allowance {max(overtime)} exceeds the maximum overtime "
                         f"{ci.calendar.max_overtime}")
    own =[dict(opts) or {None: ci.fixed_duration[o]} for o, opts in enumerate(ci.options)]  # machine None: no machine
    min_p = [min(d.values()) for d in own]
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
    duration = [dict(d) for d in own]
    run_of = {g[0]: g for g in ci.machine_groups}  # first operation -> the whole run
    for head, group in run_of.items():  # the head stands for the run: duration of the run on each machine
        duration[head] = {m: sum(duration[q][m] for q in group) for m in duration[head]}
    ready: dict[int, tuple[tuple[int, int], ...]] = {}  # ready operation -> machines it may still use

    busy: list[list[tuple[int, int]]] = [[] for _ in ci.worker_ids]  # per worker: everything booked, sorted
    fixed: list[list[tuple[int, int]]] = [[] for _ in ci.worker_ids]  # frozen shares, started breaks, removals
    frozen_time: list[list[tuple[int, int]]] = [[] for _ in ci.worker_ids]  # started shares of the frozen part only
    worker_load = [0] * len(ci.worker_ids)
    longest = [0] * len(ci.worker_ids)  # per worker: longest interval in busy, bounds the clash search
    max_end = 0  # latest end in busy over all workers (worker_start's give-up limit)
    log: list[tuple[int, int, int]] = []  # every booking (w, s, e) in order: what a cached earliest start has seen

    cal = ci.calendar
    snap_day = day_index(cal, t0) if cal is not None and snapshot else None
    taken = ({(ci.worker_ids.index(b.worker), day_index(cal, b.start)): b.start for b in snapshot.breaks}
             if cal is not None and snapshot else {})

    def clash_end(intervals, s: int, n: int) -> int | None:
        return next((e for a, e in intervals if a < s + n and s < e), None)

    @cache
    def break_at(w: int, d: int) -> int | None:
        """Break start of worker w on day d: the started one; otherwise the earliest start from the earliest break
        start (on the snapshot's day not before t) clear of the frozen part and the pending removals. Depends only on
        (w, d) and the frozen part, never on new shares, which avoid it. None: no break possible that day (the
        snapshot's day after the window, no share of the worker started before it): none is owed (C14), since every
        new share starts after the window."""
        if (w, d) in taken:
            return taken[w, d]
        s = day_start(cal, d) + cal.break_earliest
        if d == snap_day:
            s = max(s, t0)
        while (e := clash_end(fixed[w], s, cal.break_length)) is not None:
            s = e
        latest = day_start(cal, d) + cal.break_latest
        # after the window: nothing fits in it next to the frozen part and the pending removals (C14^f). None if no
        # break can be owed: the snapshot's day after the window (new shares start later) and no frozen share before
        if s > latest and d == snap_day and t0 >= latest and not any(
                day_start(cal, d) <= a < latest for a, _ in frozen_time[w]):
            return None
        return s

    def ot_of(o: int) -> int:
        """Overtime allowance of o's new shares: minutes past shift end (0 for the rules)."""
        return overtime[o] if overtime is not None else 0

    @cache  # pure in (n, ot); free_from asks it on every call
    def part_fits(n: int, ot: int) -> bool:
        """A share of n minutes fits one part of the shift, the second extended by ot minutes of overtime."""
        return any(n <= b - a for a, b in ((cal.shift_start, cal.break_earliest),
                                           (cal.break_earliest + cal.break_length, cal.shift_end + ot)))

    def busy_clash(w: int, s: int, n: int) -> int | None:
        """End of an interval of busy[w] that overlaps [s, s + n), None if none: bisect to the intervals starting
        before s + n, then back while a start lies within the longest interval of s (only those can reach past s).
        Any clashing interval does: free_from may jump to the end of any, no start before it is free."""
        iv, lo = busy[w], s - longest[w]
        i = bisect_left(iv, (s + n,)) - 1
        while i >= 0 and iv[i][0] > lo:
            if iv[i][1] > s:
                return iv[i][1]
            i -= 1
        return None

    def free_from(w: int, s: int, n: int, ot: int = 0) -> int:
        """Earliest s' >= s at which a new share [s', s' + n) is free for worker w: clear of its bookings and, with a
        calendar, inside the shift extended by ot minutes of overtime and outside that day's break."""
        if cal is not None and not part_fits(n, ot):
            raise ValueError(f"share of {n} minutes longer than both parts of the shift")
        while True:
            b = None
            if cal is not None:
                s = shift_window(cal, s, n, cal.shift_end + ot)
                b = break_at(w, day_index(cal, s))
            if (e := busy_clash(w, s, n)) is None and b is not None and b < s + n and s < b + cal.break_length:
                e = b + cal.break_length
            if e is None:
                return s
            s = e

    def worker_start(o: int, t: int, p: int) -> int:
        """Earliest start >= t of o (duration p) at which every share finds a qualified worker free."""
        spans, limit = _spans(ci.shares[o], p), t + 2 * WEEK + max_end
        while (later := max((min(free_from(w, t + off, n, ot_of(o)) for w in sh.workers) - off
                             for sh, off, n in spans),
                            default=t)) > t:
            if later > limit:  # the calendar repeats weekly: no fit within two weeks after all bookings, none ever
                raise ValueError(f"{ci.op_keys[o]}: its shares never lie within the shifts at the same time")
            t = later
        return t

    def book(w: int, s: int, e: int, part_of_fixed: bool = False, load: bool = True) -> None:
        nonlocal max_end
        insort(busy[w], (s, e))
        longest[w], max_end = max(longest[w], e - s), max(max_end, e)
        log.append((w, s, e))
        if part_of_fixed:
            insort(fixed[w], (s, e))
        if load:
            worker_load[w] += e - s

    def pick(o: int, sh: Share, s: int, n: int, ot: int) -> str:
        """Book the free qualified worker for [s, s + n) with the least worker load, then the lowest index."""
        free = [w for w in sh.workers if free_from(w, s, n, ot) == s]
        if not free:  # cannot happen: every caller passes a time at which a qualified worker is free
            raise ValueError(f"{ci.op_keys[o]}: no qualified worker free for its {sh.kind} [{s},{s + n})")
        w = min(free, key=lambda w: (worker_load[w], w))
        book(w, s, s + n)
        return ci.worker_ids[w]

    def take_workers(o: int, t: int, p: int, ot: int | None = None) -> tuple[str, ...]:
        """Book a worker for every share of o started at t (overtime allowance: o's unless given)."""
        ot = ot_of(o) if ot is None else ot
        return tuple(pick(o, sh, t + off, n, ot) for sh, off, n in _spans(ci.shares[o], p))

    out: list[Assignment] = []
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    # worker time of the frozen part: the started shares as in the snapshot (C7), a batch's shares once; then a
    # worker for every pending share (e.g. the removal of a running oven), the same for all members of a batch
    workers_of: dict[int, list[str | None]] = {}
    batch_lead: dict[tuple, int] = {}
    for o, f in frozen.items():
        if (key := batch_key(ci, o, f)) is not None and (lead := batch_lead.setdefault(key, o)) != o:
            workers_of[o] = workers_of[lead]  # the same list: filled once for the whole batch
            continue
        workers_of[o] = list(f.workers)
        for sh, n, w in zip(ci.shares[o], f.share_lengths or [sh.length for sh in ci.shares[o]], f.workers,
                            strict=True):
            if w is not None:  # realized or expected share length from the snapshot
                z, interval = ci.worker_ids.index(w), share_interval(sh._replace(length=n), f.start, f.end)
                book(z, *interval, part_of_fixed=True)
                insort(frozen_time[z], interval)
    for (z, _), s in taken.items():  # started breaks block their worker like the frozen part
        book(z, s, s + cal.break_length, part_of_fixed=True, load=False)
    # pending removals in the order of C7^o (forced_removals): before any break and any new share, so only the
    # frozen part and the removals before block them; each by the free qualified worker with the least load
    def least_load(o: int, free: list[int]) -> int:
        w = min(free, key=lambda w: (worker_load[w], w))
        worker_load[w] += next(sh.length for sh in ci.shares[o] if sh.kind == "suffix")
        return w

    end_of: dict[int, int] = {}
    for o, (i, s, _, z) in (forced_removals(ci, snapshot, least_load) if snapshot else {}).items():
        if workers_of[o][i] is None:  # once per batch: the members share the list
            workers_of[o][i] = ci.worker_ids[z]
            book(z, s, s + ci.shares[o][i].length, part_of_fixed=True, load=False)  # load counted in least_load
        end_of[o] = s + ci.shares[o][i].length

    def lead(o: int, f) -> int:
        return o if (key := batch_key(ci, o, f)) is None else batch_lead[key]

    for o, f in frozen.items():  # the frozen part: kept unchanged, occupies its machine until its end
        end = end_of.get(lead(o, f), f.end)
        out.append(Assignment(order_id=f.order_id, op_id=f.op_id, machine=f.machine, start=f.start, end=end,
                              workers=tuple(workers_of[o]), share_lengths=f.share_lengths, batch=f.batch))
        if f.machine is not None:
            m = ci.machine_index[f.machine]
            state.machine_free[m] = max(state.machine_free[m], end)
            state.load[m] += duration[o][m]
        for k in ci.op_orders[o]:
            state.work_left[k] -= min_p[o]
        for s in ci.successors[o]:
            state.ready_at[s] = max(state.ready_at[s], end)
            open_preds[s] -= 1

    for g in ci.machine_groups:  # a partly started run continues on its machine (C8, C9), parts wait for workers
        if (rest := [q for q in g if q not in frozen]) and len(rest) < len(g):
            m = ci.machine_index[frozen[g[0]].machine]
            start = max(t0, state.machine_free[m])
            for q in rest:
                start = worker_start(q, start, own[q][m])
                end = start + own[q][m]
                owner, op_id = ci.op_keys[q]
                out.append(Assignment(order_id=owner, op_id=op_id, machine=ci.machine_ids[m], start=start, end=end,
                                      workers=take_workers(q, start, own[q][m])))
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
        if assignment is None or not ci.options[o]:  # an operation without machine has nothing to assign
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

    # cached earliest start r of a candidate (o, m), computed from base time b: worker_start is the least fixpoint >= b
    # of a map monotone in t and in the bookings (they only grow), so r stays exact while the base lies in [b, r]
    # (ready_at is fixed once o is ready, machine_free only grows) and no later booking of a qualified worker overlaps
    # a share of o started at r (each share keeps a free worker at r); otherwise recomputed from the base (same plan)
    cached: dict[tuple[int, int | None], list] = {}  # (o, m) -> [b, r, bookings seen, spans]

    def earliest(o: int, m: int | None) -> int:
        base = max(state.ready_at[o], state.machine_free[m] if m is not None else 0)
        if not ci.shares[o]:  # no worker to wait for: worker_start gives the base
            return base
        c = cached.get((o, m))
        if c is not None and c[0] <= base <= c[1]:
            r, spans = c[1], c[3]
            if all(not (w in sh.workers and a < r + off + n and r + off < e)
                   for i in range(c[2], len(log)) for w, a, e in (log[i],) for sh, off, n in spans):
                c[2] = len(log)
                return r
        # a run's head (setup) waits for its own workers: own[o][m] is its own duration
        r = worker_start(o, base, own[o][m])
        cached[o, m] = [base, r, len(log), _spans(ci.shares[o], own[o][m])]
        return r

    zeta = 0  # scheduling iteration
    while ready:
        candidates = [(earliest(o, m), o, m, p) for o, mps in ready.items() for m, p in mps]
        reach = min(c[0] for c in candidates) + (delay[zeta] if delay is not None else 0)
        zeta += 1
        t, o, m, p = min(
            (c for c in candidates if c[0] <= reach),
            key=lambda c: (*sequencing(ci, state, c[1], c[2], c[3]), c[1], c[2] is None, c[2] or 0),
        )
        batch = [o]
        if ci.batch_capacity[o] > 1:  # greedy: the ready operations of its step on m with the same duration join
            mates = [(q, mp) for q, mps in ready.items() for mp in mps if q != o and ci.batch_capacity[q] > 1
                     and ci.step[q] == ci.step[o] and mp == (m, p) and state.ready_at[q] <= t]
            mates.sort(key=lambda qm: (*sequencing(ci, state, qm[0], m, p), qm[0]))
            batch += [q for q, _ in mates[:ci.batch_capacity[o] - 1]]
        elif ci.s_setup[o] is not None:  # s-batch (math/08): ready ops of its step on m join while units, shift allow
            mates = sorted(((q, mp) for q, mps in ready.items() for mp in mps if q != o and ci.step[q] == ci.step[o]
                            and mp[0] == m and state.ready_at[q] <= t),
                           key=lambda qm: (*sequencing(ci, state, qm[0], m, qm[1]), qm[0]))
            units = ci.units[o]
            for q, _ in mates:
                if (cap := ci.s_capacity[o]) is not None and units + ci.units[q] > cap:
                    continue
                # the worker must be free for the longer batch at t, inside one shift part (with o's overtime
                # allowance, none for the rules; free_from rejects longer shares) and clear of its break
                n = s_batch_length(ci, sorted([*batch, q]), m)
                if (cal is None or part_fits(n, ot_of(o))) and worker_start(o, t, n) == t:
                    batch.append(q)
                    units += ci.units[q]
            batch.sort()  # the first member (smallest index) carries the shares, as in the DES
            p = s_batch_length(ci, batch, m)
        for q in batch:
            del ready[q]
            if m is None:
                continue
            if assignment is None:
                state.load[m] += duration[q][m]  # each member's own work (a batch's length would count it n times)
            else:
                state.backlog[m] -= duration[q][m]

        if m is not None:  # before placing: ECT in make_ready reads it
            state.machine_free[m] = t + p
        group = run_of.get(o)
        s_batch = len(batch) > 1 and ci.s_setup[o] is not None
        lead = batch[0]
        # a batch's shares once, for all members, with the allowance its join was checked with (o's)
        workers = take_workers(lead, t, p if s_batch else own[o][m], ot_of(o))
        start = end = t
        for i, q in enumerate(group or batch):  # a run part after part on one machine; a batch (or one op) at t
            if group:
                if i:  # the next part of the run as soon as its workers are free
                    start = worker_start(q, start, own[q][m])
                    workers = take_workers(q, start, own[q][m])
                end = start + own[q][m]
            else:
                start, end = t, t + p
            owner, op_id = ci.op_keys[q]
            out.append(Assignment(order_id=owner, op_id=op_id, machine=None if m is None else ci.machine_ids[m],
                                  start=start, end=end, workers=workers,
                                  batch="/".join(ci.op_keys[lead]) if s_batch else None))  # unique: lead not frozen
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
        if group:
            state.machine_free[m] = end  # later than t + p if a part waited for its workers (C9: blocked until then)

    if cal is None or not ci.worker_ids:
        return Plan(out)
    # C14: a break for every worker and day with one of its shares, the one the shares avoided (break_at); days
    # before the snapshot's day are history (the snapshot's breaks, taken or none)
    days = {(ci.worker_ids.index(z), day_index(cal, share_interval(sh, a.start, a.end)[0]))
            for a in out for sh, z in zip(ci.shares[ci.op_index[a.order_id, a.op_id]], a.workers, strict=True)}
    starts = {(ci.worker_ids[w], b) for w, d in days
              if (snap_day is None or d >= snap_day) and (b := break_at(w, d)) is not None}
    starts |= {(b.worker, b.start) for b in snapshot.breaks} if snapshot else set()
    # shortcut: a day-0 break before t = 0 (origin after the break) is left out and reported by C14; fine while
    # instances start in the morning
    return Plan(out, tuple(Break(worker=z, start=s) for z, s in sorted(starts) if s >= 0))


def _spans(shares: tuple[Share, ...], p: int) -> list[tuple[Share, int, int]]:
    """(share, offset from the start, length) of every share of an operation of duration p, in time order."""
    return [(sh, p - sh.length if sh.kind == "suffix" else 0, p if sh.kind == "whole" else sh.length) for sh in shares]


def best_dispatch(ci: CompiledInstance, objective: Objective = MAKESPAN) -> tuple[str, list[Assignment]]:
    """Best schedule over all sequencing rules x (assignment rules + joint) under the objective."""
    runs = (
        (f"{s}/{a or 'joint'}", dispatch_plan(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None))
        for s in SEQUENCING_RULES
        for a in [*ASSIGNMENT_RULES, None]
    )
    name, plan = min(runs, key=lambda run: objective.evaluate(ci, run[1].assignments, run[1].breaks))
    return name, plan.assignments


def dispatch_planner(sequencing: SequencingRule, assignment: AssignmentRule | None = None):
    """Rescheduling planner for the DES: planner(ci, snapshot, current_plan) -> new complete plan."""

    def planner(ci: CompiledInstance, snapshot: Snapshot, _current: Sequence[Assignment]) -> Plan:
        return dispatch_plan(ci, sequencing, assignment, snapshot)

    return planner

