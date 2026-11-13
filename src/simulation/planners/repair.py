"""Shift repair (math/05_rescheduling-frozen-part.md): re-time the operations not yet started.

Machine, workers and the order per machine and per worker stay as planned; a batch (math/03_carriers.md) moves as
one: its operations start together at the latest start any of them needs. An operation whose planned start was
tight (equal to the end of a predecessor, of the previous operation on its machine, of the previous share of one
of its workers, or to its release) moves with its blocker, earlier or later; an operation with a gap keeps its
planned start unless its blocker now ends later. Only what a planner may know at time t is used: realized times of
finished operations, starts of running operations and planned durations, never the scenario.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from simulation.calendar import WEEK, day_index, day_start, shift_window
from simulation.model.compiled import CompiledInstance, share_interval
from simulation.model.schedule import Assignment, Break, Plan
from simulation.sim.des import planned_batches

if TYPE_CHECKING:
    from simulation.sim.snapshot import FrozenOperation, Snapshot


def shift_repair(
    ci: CompiledInstance,
    t: int,
    machine: Sequence[int | None],
    order_on: Sequence[Sequence[int]],
    planned_start: Sequence[int],
    planned_end: Sequence[int],
    start: Sequence[int | None],
    end: Sequence[int | None],
    workers: Sequence[Sequence[int]] = (),
    share_len: Sequence[Sequence[int]] = (),
    fit: Callable[[int, int], int] | None = None,
) -> tuple[list[int], list[int]]:
    """New planned start and end per operation.

    machine[o] (None: no machine), order_on[m]: machine and order per machine of the current plan;
    planned_start, planned_end: the current plan (the one sent to the MES);
    start, end: realized start and realized or expected end of a started operation (end None: running, expected
    from the planned duration, at least t + 1), None if not started;
    workers[o]: worker idx per share (empty: no workers); share_len[o]: share lengths of a started operation as in
    the snapshot (empty: the planned ones); fit(o, s): earliest start >= s at which the shares of o (a batch's
    first member) lie in the shift and outside the breaks of their workers (None: no calendar).
    """
    p = [ci.fixed_duration[o] if machine[o] is None else dict(ci.options[o])[machine[o]] for o in range(ci.n_ops)]
    prev: list[int | None] = [None] * ci.n_ops  # previous operation on the same machine
    for ops in order_on:
        for a, b in zip(ops, ops[1:], strict=False):
            prev[b] = a

    new_start, new_end = list(planned_start), [0] * ci.n_ops  # end 0 for the not started: blocks nobody yet
    for o in range(ci.n_ops):
        if start[o] is not None:  # end None: running, expected end from the planned duration, at least t + 1
            new_start[o], new_end[o] = start[o], end[o] if end[o] is not None else max(start[o] + p[o], t + 1)

    batch = planned_batches(ci, machine, planned_start, start)
    for ops in set(batch):
        for b in ops[1:]:  # within a batch nobody waits for a fellow member
            prev[b] = prev[ops[0]]

    lengths = [list(share_len[o]) if share_len and share_len[o] else [sh.length for sh in ci.shares[o]]
               for o in range(ci.n_ops)]

    def interval(o: int, i: int, s: int, e: int) -> tuple[int, int]:  # with the snapshot's length
        return share_interval(ci.shares[o][i], s, e, lengths[o][i])

    def planned_interval(o: int, i: int) -> tuple[int, int]:
        return share_interval(ci.shares[o][i], planned_start[o], planned_end[o])

    # per share (start, end) - operation start, fixed for an operation not started; [0] is the share's offset
    rel = [[share_interval(sh, 0, p[o]) for sh in ci.shares[o]] for o in range(ci.n_ops)]

    # per worker its shares in planned order (a not started batch once, with its first member). A new share is
    # blocked by the previous share of another operation, and by the previous one not started (a frozen share may
    # end out of the planned order); it never overlaps a share of a started operation (e.g. a pending removal).
    chain: dict[int, list[tuple[int, int, int]]] = defaultdict(list)  # worker -> [(planned from, op, share)]
    for o in range(ci.n_ops):
        if workers and (start[o] is not None or batch[o][0] == o):
            for i, w in enumerate(workers[o]):
                chain[w].append((planned_interval(o, i)[0], o, i))
    worker_blockers: dict[int, set[tuple[int, int, int]]] = defaultdict(set)  # op -> {(op, its share, own offset)}
    frozen_shares: dict[int, list[tuple[int, int]]] = defaultdict(list)  # worker -> [(started op, share)]
    for w, shares in chain.items():
        shares.sort()
        for j, (_, o, i) in enumerate(shares):
            if start[o] is not None:
                frozen_shares[w].append((o, i))
                continue
            first = new_before = None  # the share directly before of another op; the nearest one not started
            for jj in range(j - 1, -1, -1):
                _, q, k = shares[jj]
                if q != o:
                    first = first or (q, k)
                    if start[q] is None:
                        new_before = q, k
                        break
            worker_blockers[o].update((q, k, rel[o][i][0]) for q, k in {first, new_before} - {None})
    # a started operation keeps its times in this call: its worker time once. A share of an operation not started
    # lies from s + offset >= t + min offset on (s >= t), so a frozen share ending before cannot overlap it
    min_offset = min((r[0] for rs in rel for r in rs), default=0)
    frozen_time = {w: [iv for q, k in shares if (iv := interval(q, k, new_start[q], new_end[q]))[1] > t + min_offset]
                   for w, shares in frozen_shares.items()}

    old_blocks: dict[int, int] = {}  # from the plan only: the same in every pass

    def candidate(o: int) -> int:
        blockers = [*ci.predecessors[o], *([prev[o]] if prev[o] is not None else [])]
        own = worker_blockers.get(o, ())
        if (old_block := old_blocks.get(o)) is None:
            old_block = old_blocks[o] = max([ci.release[o], *(planned_end[q] for q in blockers),
                                             *(planned_interval(q, k)[1] - off for q, k, off in own)])
        new_block = max([t, ci.release[o], *(new_end[q] for q in blockers),
                         *(interval(q, k, new_start[q], new_end[q])[1] - off for q, k, off in own)])
        # tight: planned at the blocker's end, or at the earliest start the calendar allows after it (behind a break,
        # the next morning; user 2026-11-11): such a share comes back when its blocker ends earlier; else a gap
        tight = planned_start[o] == old_block or (fit is not None and planned_start[o] == fit(o, old_block))
        return new_block if tight else max(planned_start[o], new_block)

    def clear_of_frozen(o: int, s: int) -> int:
        """Earliest s' >= s at which no share of o (a batch's first member) overlaps a share of a started op."""
        while True:
            ends = [hi - rel[o][i][0] for i, w in enumerate(workers[o] if workers else ())
                    for lo, hi in frozen_time.get(w, ()) if s + rel[o][i][0] < hi and lo < s + rel[o][i][1]]
            if not ends:
                return s
            s = max(ends)

    # the planned share order is acyclic per worker but not across workers (the prefix of one operation before the
    # suffix of another on one worker, the other way round on a second one): iterate to the least fixpoint from
    # below (not started ends at 0), each pass in planned order; one pass without workers, as blockers come first
    todo = sorted((o for o in range(ci.n_ops) if start[o] is None and batch[o][0] == o),
                  key=lambda o: (planned_start[o], o))
    for _ in range(len(todo) + 1):
        changed = False
        for o in todo:
            s = clear_of_frozen(o, max(candidate(q) for q in batch[o]))
            while fit is not None and (moved := clear_of_frozen(o, fit(o, s))) != s:
                s = moved
            if s != new_start[o] or new_end[o] != s + p[o]:
                changed = True
                for q in batch[o]:
                    new_start[q], new_end[q] = s, s + p[q]
        if not changed:
            return new_start, new_end
    raise ValueError("shift repair does not converge: the orders per machine and worker contain a cycle")


def repair(ci: CompiledInstance, snapshot: Snapshot, plan: Sequence[Assignment],
           breaks: Sequence[Break] = ()) -> list[Assignment]:
    """The repaired plan's assignments; `repair_plan` also returns its breaks."""
    return repair_plan(ci, snapshot, plan, breaks).assignments


def repair_plan(ci: CompiledInstance, snapshot: Snapshot, plan: Sequence[Assignment],
                breaks: Sequence[Break] = (), overtime: bool = False) -> Plan:
    """Shift repair with the planner interface: (ci, snapshot, current plan, its breaks) -> repaired plan.

    A pending removal of a running operation ends as the checker requires (C7^o, math/04_workers.md): at the
    snapshot's expected end if a qualified worker is free of the frozen part then, otherwise at the earliest time
    one is (forced overstay); its planned worker if free then, otherwise the first free qualified one (forced).
    With a calendar (`breaks`: the current ones, taken with their realized start): a share moved by the repair
    goes to the next time inside its worker's shift (no overtime beyond what the plan has for that worker and day;
    with `overtime` up to shift end + max overtime, as the factory itself would start it) and outside the worker's
    break; a pending break stays unless it is overdue or clashes with the frozen part,
    then it starts at the earliest time from max(planned, t) clear of it (C14^f if after the window); a day on
    which a moved share now starts before the latest break start gets a break where the rule would place it.
    """
    w_index = {w: z for z, w in enumerate(ci.worker_ids)}
    machine: list[int | None] = [None] * ci.n_ops
    planned_start, planned_end, workers = [0] * ci.n_ops, [0] * ci.n_ops, [[] for _ in range(ci.n_ops)]
    for a in plan:
        o = ci.op_index[a.order_id, a.op_id]
        machine[o] = None if a.machine is None else ci.machine_index[a.machine]
        planned_start[o], planned_end[o], workers[o] = a.start, a.end, [w_index[w] for w in a.workers]
    start: list[int | None] = [None] * ci.n_ops
    end: list[int | None] = [None] * ci.n_ops
    share_len: list[tuple[int, ...]] = [()] * ci.n_ops
    frozen = [(ci.op_index[f.order_id, f.op_id], f) for f in snapshot.frozen]
    for o, f in frozen:
        start[o], end[o], share_len[o] = f.start, f.end, f.share_lengths
    cal = ci.calendar if ci.worker_ids else None
    busy = _frozen_worker_time(ci, frozen)  # started shares; with a calendar also the taken breaks (as the checker)
    if cal is not None:
        for b in snapshot.breaks:
            busy[w_index[b.worker]].append((b.start, b.start + cal.break_length))
    # pending removals as C7^o orders them, each by its planned worker if free then (one entry per batch)
    planned_worker = {o: workers[o][i] for o, f in frozen if (i := _pending_removal(ci, o, f)) is not None}
    removals = forced_removals(ci, snapshot,
                               lambda o, free: planned_worker[o] if planned_worker.get(o) in free else free[0])
    for o, (i, s, _, z) in removals.items():
        workers[o] = list(workers[o])  # a batch's members: own lists, the same worker
        workers[o][i], end[o] = z, s + ci.shares[o][i].length
        if (s, end[o]) not in busy[z]:  # a batch: one removal
            busy[z].append((s, end[o]))
    order_on: list[list[int]] = [[] for _ in range(ci.n_machines)]
    for o in sorted(range(ci.n_ops), key=lambda o: (planned_start[o], o)):
        if machine[o] is not None:
            order_on[machine[o]].append(o)
    args = (ci, snapshot.t, machine, order_on, planned_start, planned_end, start, end,
            workers if ci.worker_ids else (), share_len)
    brk: dict[tuple[int, int], int | None] = {}
    if cal is None:
        new_start, new_end = shift_repair(*args)
    else:
        brk, fit, owe = _calendar(ci, snapshot, plan, breaks, workers, machine, busy, overtime)
        while True:  # a break created on a new day may need another round for shares placed before it
            n_breaks = len(brk)
            new_start, new_end = shift_repair(*args, fit=fit)
            owe(new_start, new_end, share_len)
            if len(brk) == n_breaks:
                break
    # a started share as in the snapshot (the checker reads it from the plan), but only if it differs from the
    # planned length (a whole share has none): an unchanged plan compares equal to the one sent to the factory
    kept = [share_len[o] if any(sh.kind != "whole" and n != sh.length for sh, n in zip(ci.shares[o], share_len[o],
                                                                                         strict=False)) else ()
            for o in range(ci.n_ops)]
    assignments = [
        Assignment(order_id=k, op_id=j, machine=None if machine[o] is None else ci.machine_ids[machine[o]],
                   start=new_start[o], end=new_end[o], workers=tuple(ci.worker_ids[z] for z in workers[o]),
                   share_lengths=kept[o])
        for o, (k, j) in enumerate(ci.op_keys)]
    return Plan(assignments, tuple(sorted((Break(worker=ci.worker_ids[z], start=b) for (z, _), b in brk.items()
                                           if b is not None), key=lambda b: (b.start, b.worker))))


def _calendar(ci: CompiledInstance, snapshot: Snapshot, plan: Sequence[Assignment], breaks: Sequence[Break],
              workers: Sequence[Sequence[int]], machine: Sequence[int | None],
              fixed: dict[int, list[tuple[int, int]]], overtime: bool = False,
              ) -> tuple[dict[tuple[int, int], int | None], Callable[[int, int], int], Callable[..., None]]:
    """Breaks per (worker, day) and the shift fit of an operation for the repair. `fixed`: per worker the started
    shares, taken breaks and pending removals."""
    cal, t = ci.calendar, snapshot.t
    w_index = {w: z for z, w in enumerate(ci.worker_ids)}
    p = [ci.fixed_duration[o] if machine[o] is None else dict(ci.options[o])[machine[o]] for o in range(ci.n_ops)]

    def latest_break(d: int) -> int:
        return day_start(cal, d) + cal.break_latest

    def clear(z: int, s: int) -> int:
        return _free_from(fixed.get(z, ()), s, cal.break_length)

    # the plan's overtime per worker and day: a moved share may end as late as the worker's last planned share that
    # day, otherwise not after the shift end (the repair creates no overtime); with `overtime` up to the window
    latest_end: dict[tuple[int, int], int] = {}
    for a in plan:
        o = ci.op_index[a.order_id, a.op_id]
        for sh, w in zip(ci.shares[o], a.workers, strict=True):
            lo, hi = share_interval(sh, a.start, a.end)
            d = day_index(cal, lo)
            latest_end[w_index[w], d] = max(latest_end.get((w_index[w], d), cal.shift_end),
                                            min(hi - day_start(cal, d), cal.shift_end + cal.max_overtime))

    taken = {(b.worker, b.start) for b in snapshot.breaks}
    brk: dict[tuple[int, int], int | None] = {}
    for b in breaks:
        z, d = w_index[b.worker], day_index(cal, b.start)
        if (b.worker, b.start) in taken:
            brk[z, d] = b.start
            continue
        s = clear(z, max(b.start, t))  # overdue (the worker was busy) or clashing with the frozen part: later
        if s > latest_break(d):  # no room left in the window: the earliest clear start from the window (C14^f)
            s = clear(z, max(day_start(cal, d) + cal.break_earliest, t))
        brk[z, d] = s
    snap_day = day_index(cal, t)

    def break_at(z: int, d: int) -> int | None:
        """The break of z on day d; a new one where the rule places it: from the earliest break start (on the
        snapshot's day not before t) clear of the frozen part, after the window only if nothing fits in it (C14^f);
        None for a day before the snapshot's (history: no break can be planned there any more)."""
        if (z, d) not in brk:
            brk[z, d] = None if d < snap_day else clear(z, max(day_start(cal, d) + cal.break_earliest, t))
        return brk[z, d]

    def fit(o: int, s: int) -> int:
        limit = s + 2 * WEEK
        while True:
            need = s
            for i, z in enumerate(workers[o]):
                lo, hi = share_interval(ci.shares[o][i], s, s + p[o])
                a, n = lo, hi - lo
                while True:
                    d = day_index(cal, a)
                    last = cal.shift_end + cal.max_overtime if overtime else latest_end.get((z, d), cal.shift_end)
                    if (moved := shift_window(cal, a, n, last)) != a:
                        a = moved  # possibly another day: check it against that day's limit
                        continue
                    b = brk.get((z, d)) if a >= latest_break(d) else break_at(z, d)  # owed if before the latest
                    if b is not None and a < b + cal.break_length and b < a + n:
                        a = b + cal.break_length
                        continue
                    break
                need = max(need, a - (lo - s))
            if need == s:
                return s
            if need > limit:
                raise ValueError(f"{ci.op_keys[o]}: its shares never lie within the shifts at the same time")
            s = need

    def owe(new_start: Sequence[int], new_end: Sequence[int], share_len: Sequence[Sequence[int]]) -> None:
        """A break on every (worker, day) with a share starting before the latest break start (C14), also for a
        frozen share: e.g. a removal planned at 13:00 that starts earlier because its machine part ended early."""
        for o in range(ci.n_ops):
            for i, z in enumerate(workers[o]):
                n = share_len[o][i] if share_len[o] else ci.shares[o][i].length
                a = share_interval(ci.shares[o][i], new_start[o], new_end[o], n)[0]
                if a < latest_break(d := day_index(cal, a)):
                    break_at(z, d)

    return brk, fit, owe


def forced_removals(ci: CompiledInstance, snapshot: Snapshot,
                    choose: Callable[[int, list[int]], int] | None = None,
                    ) -> dict[int, tuple[int, int, list[int], int]]:
    """Per running operation with a pending removal: (share index, forced start, qualified workers free then, the
    booked worker), as C7^o requires (math/04_workers.md): the removals are booked one at a time, always the one
    with the earliest possible start next (ties: earliest due date of its orders, then operation index), each at
    the earliest start from the expected one at which a qualified worker is free of the frozen part (started
    shares, taken breaks) and of the removals booked before it, inside the shift window with overtime. The booked
    worker is choose(o, free workers), by default the first free one. The starts come out in booking order, so the
    checker (its own copy) recomputes them from the plan's order. Members of a batch share the entry of their run."""
    cal = ci.calendar if ci.worker_ids else None
    frozen = [(ci.op_index[f.order_id, f.op_id], f) for f in snapshot.frozen]
    busy = _frozen_worker_time(ci, frozen)
    if cal is not None:
        for b in snapshot.breaks:
            busy[ci.worker_ids.index(b.worker)].append((b.start, b.start + cal.break_length))
    lead_of: dict[tuple[str | None, int, int], int] = {}
    pending, members = {}, defaultdict(list)
    for o, f in frozen:
        if (i := _pending_removal(ci, o, f)) is None:
            continue
        lead = lead_of.setdefault((f.machine, f.start, f.end), o) if ci.batch_capacity[o] > 1 else o
        members[lead].append(o)
        if lead == o:
            pending[o] = (i, f)
    due = {o: min((d for k in ci.op_orders[o] if (d := ci.due_date[k]) is not None), default=float("inf"))
           for o in pending}
    out = {}
    while pending:
        free_at = {o: {z: _free_from(busy[z], f.end - ci.shares[o][i].length, ci.shares[o][i].length, cal)
                       for z in ci.shares[o][i].workers} for o, (i, f) in pending.items()}
        o = min(pending, key=lambda o: (min(free_at[o].values()), due[o], o))
        i, _ = pending.pop(o)
        s = min(free_at[o].values())
        free = [z for z, v in free_at[o].items() if v == s]
        z = choose(o, free) if choose else free[0]
        busy[z].append((s, s + ci.shares[o][i].length))
        out |= dict.fromkeys(members[o], (i, s, free, z))
    return out


def _pending_removal(ci: CompiledInstance, o: int, f: FrozenOperation) -> int | None:
    """Index of the suffix share of a running operation if it has not started (no worker in the snapshot)."""
    i = next((i for i, sh in enumerate(ci.shares[o]) if sh.kind == "suffix"), None)
    return i if f.running and i is not None and i < len(f.workers) and f.workers[i] is None else None


def _frozen_worker_time(ci: CompiledInstance, frozen) -> dict[int, list[tuple[int, int]]]:
    """Worker idx -> intervals of the started shares, from the snapshot's times and share lengths. Computed here
    and not taken from the checker, which has to verify the result independently."""
    out: dict[int, list[tuple[int, int]]] = defaultdict(list)
    w_index = {w: z for z, w in enumerate(ci.worker_ids)}
    for o, f in frozen:
        lengths = f.share_lengths or [sh.length for sh in ci.shares[o]]
        for sh, n, w in zip(ci.shares[o], lengths, f.workers, strict=True):
            if w is not None:
                out[w_index[w]].append(share_interval(sh, f.start, f.end, n))
    return out


def _free_from(busy: Sequence[tuple[int, int]], s: int, n: int, cal=None) -> int:
    """Earliest s' >= s with [s', s' + n) clear of `busy` and, with a calendar, inside one day's shift window with
    overtime (C13)."""
    while True:
        if cal is not None:
            s = shift_window(cal, s, n, cal.shift_end + cal.max_overtime)
        if (clash := next((b for a, b in busy if a < s + n and s < b), None)) is None:
            return s
        s = clash
