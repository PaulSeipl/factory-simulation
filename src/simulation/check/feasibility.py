"""Feasibility checker for the base model (math/01_basic-fjsp.md, C1-C5), revised plans (math/05, C6-C7),
machine runs of carriers (math/03_carriers.md, C8-C9, C10 batches) and workers (math/04_workers.md, C11-C14).

Written independently of every planner and solver: it only reads the compiled
instance and the assignments, and reports every violated constraint. Test oracle
for CP-SAT, the DES, dispatching rules and the GA. Objective-agnostic on purpose.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.calendar import day_index, day_start, is_working_day, minute_of_day
from simulation.model.compiled import CompiledInstance, OpKey, share_interval
from simulation.model.schedule import Assignment, Break

if TYPE_CHECKING:
    from simulation.sim.snapshot import FrozenOperation, Snapshot


@dataclass(frozen=True, slots=True)
class Violation:
    # "C1".."C5" (math/01), "C6", "C7" (math/05), "C8".."C10" (math/03), "C11".."C14" (math/04); "C0" = not in the
    # instance
    constraint: str
    ops: tuple[OpKey, ...]
    message: str


def check_schedule(
    ci: CompiledInstance,
    assignments: Iterable[Assignment],
    snapshot: Snapshot | None = None,
    breaks: Iterable[Break] = (),
) -> list[Violation]:
    """Return all violations; an empty list means the schedule is feasible.

    With a snapshot (a plan revised at time snapshot.t), the frozen operations must appear exactly as in
    the snapshot (C7, realized or expected times, so C2 is not checked for them) and no other operation
    may start before snapshot.t (C6). `breaks`: the planned breaks of the workers (C14, only with a calendar);
    with a snapshot its breaks must appear unchanged (C7) and every other break starts at or after snapshot.t (C6).
    """
    by_op, violations = assigned_exactly_once(ci, assignments)
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    blocked = _frozen_worker_time(ci, snapshot, with_breaks=True) if snapshot else {}
    for o, a in by_op.items():
        key = ci.op_keys[o]
        p_of = {ci.machine_ids[m]: p for m, p in ci.options[o]}
        if (fixed := ci.fixed_duration[o]) is not None:  # operation without machine (math/04)
            on_machine = None if a.machine is None else Violation(
                "C11", (key,), f"{key} has no machine, planned on {a.machine}")
            duration = on_machine or (None if o in frozen else wrong_duration(key, a, fixed))
        else:
            duration = not_eligible(key, a.machine, p_of) or (
                None if o in frozen else wrong_duration(key, a, p_of[a.machine]))
        found = [
            duration,
            *worker_shares_wrong(ci, o, a),
            *starts_before_predecessors(ci, o, a, by_op),
            starts_before_release(key, a.start, ci.release[o]),
            frozen_changed(key, a, frozen[o], forced_end(ci, o, frozen[o], blocked)) if o in frozen else None,
            starts_before_t(key, a.start, snapshot.t) if snapshot and o not in frozen else None,
        ]
        violations += [v for v in found if v]
    breaks = tuple(breaks)
    return (violations + run_on_several_machines(ci, by_op) + machine_overlaps(ci, by_op)
            + worker_overlaps(ci, by_op) + outside_shift(ci, by_op) + break_violations(ci, by_op, breaks, snapshot)
            + breaks_changed(breaks, snapshot))


def assigned_exactly_once(
    ci: CompiledInstance, assignments: Iterable[Assignment]
) -> tuple[dict[int, Assignment], list[Violation]]:
    """C1 (sum_m x_om = 1): every operation exactly once; C0: no unknown operations."""
    by_op: dict[int, Assignment] = {}
    violations = []
    for a in assignments:
        key = (a.order_id, a.op_id)
        o = ci.op_index.get(key)
        if o is None:
            violations.append(Violation("C0", (key,), f"{key} is not an operation of the instance"))
        elif o in by_op:
            violations.append(Violation("C1", (key,), f"{key} assigned more than once"))
        else:
            by_op[o] = a
    violations += [Violation("C1", (key,), f"{key} is not assigned")
                   for o, key in enumerate(ci.op_keys) if o not in by_op]
    return by_op, violations


def not_eligible(key: OpKey, machine: str, p_of: Mapping[str, int]) -> Violation | None:
    """C1: the machine is in M_o (an unknown machine is never in M_o)."""
    if machine not in p_of:
        return Violation("C1", (key,), f"{key} on {machine}, eligible: {sorted(p_of)}")
    return None


def wrong_duration(key: OpKey, a: Assignment, p: int) -> Violation | None:
    """C2: C_o - S_o = p_{o,m} of the assigned machine."""
    if a.end - a.start != p:
        return Violation("C2", (key,), f"{key}: end - start = {a.end - a.start}, p = {p} on {a.machine}")
    return None


def starts_before_predecessors(
    ci: CompiledInstance, o: int, a: Assignment, by_op: Mapping[int, Assignment]
) -> list[Violation]:
    """C3: S_o >= C_q for every predecessor q (a missing q is already reported under C1)."""
    violations = []
    for q in ci.predecessors[o]:
        if (b := by_op.get(q)) is not None and a.start < b.end:
            pred, key = ci.op_keys[q], ci.op_keys[o]
            violations.append(Violation("C3", (pred, key),
                                        f"{key} starts at {a.start} before predecessor {pred} ends at {b.end}"))
    return violations


def starts_before_release(key: OpKey, start: int, release: int) -> Violation | None:
    """C4: S_o >= r_k(o)."""
    if start < release:
        return Violation("C4", (key,), f"{key} starts at {start} before release {release}")
    return None


def frozen_changed(key: OpKey, a: Assignment, f: FrozenOperation, end: int | None = None) -> Violation | None:
    """C7: a frozen operation appears with the machine, times and workers of the started shares of the snapshot.
    `end`: its required end if not the snapshot's (forced overstay, see forced_end)."""
    started = [(i, w) for i, w in enumerate(f.workers) if w is not None]
    end = f.end if end is None else end
    if (a.machine, a.start, a.end) != (f.machine, f.start, end) or any(
            i >= len(a.workers) or a.workers[i] != w for i, w in started):
        forced = f", forced end {end}" if end != f.end else ""
        return Violation("C7", (key,), f"{key} is frozen as {f.machine} [{f.start},{f.end}) {f.workers}{forced}, "
                                       f"planned {a.machine} [{a.start},{a.end}) {a.workers}")
    return None


def forced_end(ci: CompiledInstance, o: int, f: FrozenOperation, blocked: Mapping[str, list[tuple[int, int]]]) -> int:
    """C7 with a forced overstay (math/04_workers.md, C7^o): a running operation whose suffix (removal) has not
    started ends at the snapshot's expected end if a qualified worker is free then; otherwise at the earliest time a
    qualified worker is free of the frozen part (started shares, started breaks) and within the shift window (C13).
    A planner may not delay it on its own; the delay comes only from disturbances."""
    i = next((i for i, sh in enumerate(ci.shares[o]) if sh.kind == "suffix"), None)
    if not f.running or i is None or i >= len(f.workers) or f.workers[i] is not None:
        return f.end
    sh = ci.shares[o][i]
    return min(_free_from(ci, blocked.get(ci.worker_ids[w], ()), f.end - sh.length, sh.length)
               for w in sh.workers) + sh.length


def _free_from(ci: CompiledInstance, busy: Iterable[tuple[int, int]], s: int, n: int) -> int:
    """Earliest s' >= s with [s', s' + n) clear of `busy` and, with a calendar, inside one day's shift window."""
    busy, cal = tuple(busy), ci.calendar
    while True:
        if cal is not None:
            d = day_index(cal, s)
            if not (is_working_day(cal, d) and minute_of_day(cal, s) >= cal.shift_start
                    and s + n <= day_start(cal, d) + cal.shift_end + cal.max_overtime):
                d = d if is_working_day(cal, d) and minute_of_day(cal, s) < cal.shift_start else d + 1
                d = next(e for e in range(d, d + 8) if is_working_day(cal, e))
                s = max(s, day_start(cal, d) + cal.shift_start)
                continue
        if (clash := next((b for a, b in busy if a < s + n and s < b), None)) is None:
            return s
        s = clash


def starts_before_t(key: OpKey, start: int, t: int) -> Violation | None:
    """C6: an operation not started is not planned before the rescheduling point t."""
    if start < t:
        return Violation("C6", (key,), f"{key} starts at {start} before the rescheduling point {t}")
    return None


def run_on_several_machines(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> list[Violation]:
    """C8: setup, main operation and removal of a run on one machine."""
    violations = []
    for group in ci.machine_groups:
        if len(machines := {by_op[o].machine for o in group if o in by_op}) > 1:
            keys = tuple(ci.op_keys[o] for o in group)
            violations.append(Violation("C8", keys, f"run {keys[0][0]} on several machines: {sorted(machines)}"))
    return violations


def machine_overlaps(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> list[Violation]:
    """C5: sweep per machine over half-open intervals [S, C), reporting every overlapping pair.

    C9: a run blocks its machine from the start of its first operation to the end of its last one, also in a gap
    between them (e.g. a print that has finished and waits for its removal); a pair involving such a span is C9.

    C10: operations of a batch step (capacity > 1) on one machine with identical start and end form one machine
    run, holding at most the capacity; they occupy the machine as one interval.
    """
    in_group = {o: g for g in ci.machine_groups for o in g}
    per_machine: dict[str, list[tuple[int, int, tuple[int, ...]]]] = defaultdict(list)
    batches: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    violations = []
    for o, a in by_op.items():
        g = in_group.get(o)
        if a.machine is None:  # operation without machine (C11 if it should have one)
            continue
        if ci.batch_capacity[o] > 1:
            batches[a.machine, a.start, a.end].append(o)
        elif g is None or not all(q in by_op for q in g):
            per_machine[a.machine].append((a.start, a.end, (o,)))
        elif o == g[0]:
            per_machine[a.machine].append((a.start, by_op[g[-1]].end, g))
    for (machine, s, e), ops in batches.items():
        per_machine[machine].append((s, e, tuple(ops)))
        if len(ops) > (cap := min(ci.batch_capacity[o] for o in ops)):
            violations.append(Violation("C10", tuple(ci.op_keys[o] for o in ops),
                                        f"{len(ops)} operations in one run on {machine} [{s},{e}), capacity {cap}"))
    for machine, intervals in per_machine.items():
        running: list[tuple[int, int, tuple[int, ...]]] = []
        for s, e, ops in sorted(intervals):
            running = [iv for iv in running if iv[1] > s]
            violations += [
                Violation("C9" if (len(ops2) > 1 and ops2[0] in in_group) or (len(ops) > 1 and ops[0] in in_group)
                          else "C5",
                          (ci.op_keys[ops2[0]], ci.op_keys[ops[0]]),
                          f"{_label(ci, ops2)} [{s2},{e2}) and {_label(ci, ops)} [{s},{e}) overlap on {machine}")
                for s2, e2, ops2 in running
            ]
            running.append((s, e, ops))
    return violations


def worker_shares_wrong(ci: CompiledInstance, o: int, a: Assignment) -> list[Violation]:
    """C11: one worker per share, known and qualified (W_eta)."""
    key, shares = ci.op_keys[o], ci.shares[o]
    if len(a.workers) != len(shares):
        return [Violation("C11", (key,), f"{key}: {len(a.workers)} workers for {len(shares)} shares")]
    if a.share_lengths and len(a.share_lengths) != len(shares):
        return [Violation("C11", (key,), f"{key}: {len(a.share_lengths)} share lengths for {len(shares)} shares")]
    return [
        Violation("C11", (key,), f"{key}: {w} not qualified for the {s.kind} share, qualified: "
                                 f"{[ci.worker_ids[i] for i in s.workers]}")
        for s, w in zip(shares, a.workers, strict=True)
        if w not in {ci.worker_ids[i] for i in s.workers}
    ]


def worker_intervals(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> dict[str, list[tuple[int, int, int]]]:
    """Worker -> [(from, to, op)] over all shares; a batch (one oven run) counts once, with its first member."""
    seen_batches: set[tuple[str | None, int, int]] = set()
    out: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for o, a in sorted(by_op.items()):
        if len(a.workers) != len(ci.shares[o]) or (a.share_lengths and len(a.share_lengths) != len(ci.shares[o])):
            continue  # reported under C11
        if ci.batch_capacity[o] > 1:
            if (a.machine, a.start, a.end) in seen_batches:
                continue
            seen_batches.add((a.machine, a.start, a.end))
        # a realized schedule carries the realized share lengths (DES), a plan the planned ones
        lengths = a.share_lengths or [s.length for s in ci.shares[o]]
        for s, n, w in zip(ci.shares[o], lengths, a.workers, strict=True):
            if w in ci.worker_ids:  # unknown workers are reported under C11
                out[w].append((*share_interval(s._replace(length=n), a.start, a.end), o))
    return out


def worker_overlaps(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> list[Violation]:
    """C12: a worker does one thing at a time (half-open share intervals). C11: the members of one batch carry the
    same workers (one run, one loading and one removal)."""
    violations = []
    batches: dict[tuple[str | None, int, int], list[int]] = defaultdict(list)
    for o, a in by_op.items():
        if ci.batch_capacity[o] > 1:
            batches[a.machine, a.start, a.end].append(o)
    for ops in batches.values():
        if len({by_op[o].workers for o in ops}) > 1:
            violations.append(Violation("C11", tuple(ci.op_keys[o] for o in ops),
                                        f"{_label(ci, tuple(ops))} with different workers per member"))
    for w, intervals in worker_intervals(ci, by_op).items():
        intervals.sort()
        running: list[tuple[int, int, int]] = []
        for s, e, o in intervals:
            running = [iv for iv in running if iv[1] > s]
            violations += [Violation("C12", (ci.op_keys[o2], ci.op_keys[o]),
                                     f"{w}: {ci.op_keys[o2]} [{s2},{e2}) and {ci.op_keys[o]} [{s},{e}) overlap")
                           for s2, e2, o2 in running]
            running.append((s, e, o))
    return violations


def outside_shift(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> list[Violation]:
    """C13 (only with a calendar): every share lies within one working day in [shift start, shift end + max
    overtime]; machines run at any time."""
    if (cal := ci.calendar) is None:
        return []
    latest = cal.shift_end + cal.max_overtime
    return [
        Violation("C13", (ci.op_keys[o],), f"{w} on {ci.op_keys[o]} [{s},{e}) outside the shift window of day {d}")
        for w, intervals in worker_intervals(ci, by_op).items()
        for s, e, o in intervals
        if not (is_working_day(cal, d := day_index(cal, s)) and minute_of_day(cal, s) >= cal.shift_start
                and e - day_start(cal, d) <= latest)
    ]


def break_violations(ci: CompiledInstance, by_op: Mapping[int, Assignment], breaks: Iterable[Break],
                     snapshot: Snapshot | None = None) -> list[Violation]:
    """C14 (only with a calendar): exactly one break per worker on each day with a share starting before the latest
    break start, starting in [break_earliest, break_latest], at most one break a day, and no share during a break.

    With a snapshot: its breaks are realized history and not checked against the window (like C2 for frozen
    operations); a later break is a forced postponement and allowed only if a frozen share of the worker covers the
    latest break start and the break starts exactly at that share's (expected) end."""
    if (cal := ci.calendar) is None:
        return []
    violations = []
    taken = {(b.worker, b.start) for b in snapshot.breaks} if snapshot else set()
    frozen_time = _frozen_worker_time(ci, snapshot) if snapshot else {}
    per_day: dict[tuple[str, int], list[int]] = defaultdict(list)
    for b in breaks:
        if b.worker not in ci.worker_ids:
            violations.append(Violation("C14", (), f"break of unknown worker {b.worker}"))
            continue
        per_day[b.worker, (d := day_index(cal, b.start))].append(b.start)
        latest = day_start(cal, d) + cal.break_latest
        forced = b.start > latest and any(s < latest < e == b.start for s, e in frozen_time.get(b.worker, ()))
        if (not cal.break_earliest <= (m := minute_of_day(cal, b.start)) <= cal.break_latest
                and (b.worker, b.start) not in taken and not forced):
            why = ", not forced by a frozen share ending then" if snapshot else ""
            violations.append(Violation("C14", (), f"break of {b.worker} at {m // 60:02d}:{m % 60:02d}, outside "
                                                   f"the break window{why}"))
    violations += [Violation("C14", (), f"{w}: {len(starts)} breaks on day {d}")
                   for (w, d), starts in per_day.items() if len(starts) > 1]
    for w, intervals in worker_intervals(ci, by_op).items():
        # a break is owed on a day with a share starting before the latest break start (user 2026-11-09: a worker
        # who only starts after the window needs none; working times per worker will come from the MES)
        owed = {day_index(cal, s) for s, _, _ in intervals if s < day_start(cal, day_index(cal, s)) + cal.break_latest}
        violations += [Violation("C14", (), f"{w}: no break on day {d}") for d in sorted(owed) if (w, d) not in per_day]
        violations += [
            Violation("C14", (ci.op_keys[o],),
                      f"{w} on {ci.op_keys[o]} [{s},{e}) during the break [{b},{b + cal.break_length})")
            for s, e, o in intervals
            for b in per_day.get((w, day_index(cal, s)), [])
            if s < b + cal.break_length and b < e
        ]
    return violations


def breaks_changed(breaks: Iterable[Break], snapshot: Snapshot | None) -> list[Violation]:
    """C7: the breaks started by snapshot.t appear unchanged; C6: every other break starts at or after snapshot.t."""
    if snapshot is None:
        return []
    planned, taken = {(b.worker, b.start) for b in breaks}, {(b.worker, b.start) for b in snapshot.breaks}
    return ([Violation("C7", (), f"break of {w} at {s} started by t = {snapshot.t}, missing from the plan")
             for w, s in sorted(taken - planned)]
            + [Violation("C6", (), f"break of {w} at {s} planned before t = {snapshot.t}")
               for w, s in sorted(planned - taken) if s < snapshot.t])


def _frozen_worker_time(ci: CompiledInstance, snapshot: Snapshot,
                        with_breaks: bool = False) -> dict[str, list[tuple[int, int]]]:
    """Worker -> share intervals of the started shares of the frozen operations, from the snapshot's (expected)
    times and share lengths (what a planner sees); with_breaks: also the started breaks."""
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for f in snapshot.frozen:
        o = ci.op_index.get((f.order_id, f.op_id))
        if o is None:
            continue  # reported under C0/C1
        lengths = f.share_lengths or [sh.length for sh in ci.shares[o]]
        for sh, n, w in zip(ci.shares[o], lengths, f.workers, strict=False):  # a wrong count is reported under C11
            if w is not None:
                out[w].append(share_interval(sh._replace(length=n), f.start, f.end))
    if with_breaks and ci.calendar is not None:
        for b in snapshot.breaks:
            out[b.worker].append((b.start, b.start + ci.calendar.break_length))
    return out


def _label(ci: CompiledInstance, ops: tuple[int, ...]) -> str:
    first, last = ci.op_keys[ops[0]], ci.op_keys[ops[-1]]
    if len(ops) == 1:
        return str(first)
    if ops[0] not in {o for g in ci.machine_groups for o in g}:
        return f"batch {[ci.op_keys[o][0] for o in ops]} ({first[1]})"
    return f"run {first[0]} ({first[1]} to {last[1]})"


def assert_feasible(ci: CompiledInstance, assignments: Iterable[Assignment]) -> None:
    """Raise AssertionError listing all violations (for tests and debugging)."""
    if violations := check_schedule(ci, assignments):
        raise AssertionError(
            f"{len(violations)} violation(s):\n" + "\n".join(f"  [{v.constraint}] {v.message}" for v in violations)
        )
