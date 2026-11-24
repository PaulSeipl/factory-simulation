"""MES snapshot → thesis `Snapshot`, and the id map MES keys ↔ instance operations (task 1.5c).

An MES step is one or more instance operations, in time order:
- AM_PREP: the print run's setup and its main operation (the handoff ends the setup, starts the print);
- PART_POWDER_REMOVAL: the print run's removal;
- MILL_PREP_SECONDARY / SECONDARY_PLATE_REMOVAL: the plate's mill run, likewise;
- every other step: one operation (an order operation, or a carrier operation of the plate).
Operations of 0 minutes are not in the compiled instance (`operation_graph` skips them) and drop out of the map.

A started MES task freezes its operations (math/13_des.md §6): finished ones with their real times, running ones
with the MES's expected end (at least t + 1). The planner never sees anything else of the MES's past.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from simulation.calendar import day_index, day_start, is_working_day
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Break
from simulation.sim.snapshot import FrozenOperation, Snapshot

from mes_bridge.api import ProblemOperationOut, ProblemOut, ProblemTaskOut
from mes_bridge.instance import (
    BLANK_TASKS,
    MILL,
    MILL_BLANK,
    MILL_FLIPPED,
    PRINT,
    MappingError,
    at,
    blank_of_key,
    blank_run,
    carrier_id,
    flip_run,
    is_mapped,
    mill_run,
    print_run,
    rework_run,
)

OpKey = tuple[str, str]


@dataclass(frozen=True)
class IdMap:
    ops: dict[str, tuple[OpKey, ...]]  # MES key -> its instance operations, in time order

    def key_of(self) -> dict[OpKey, str]:
        return {k: key for key, ks in self.ops.items() for k in ks}


def _candidates(o: ProblemOperationOut) -> list[OpKey] | None:
    tt = o.task_type
    if not is_mapped(o):
        return None
    kind, _, rest = o.key.partition(":")
    if tt in BLANK_TASKS:  # on the order's assumed blank before DATA_PREP_PRIMARY, the mill job's after
        b = blank_of_key(o.key)
        return {
            "MILL_PREP_PRIMARY": [(blank_run(b), "setup"), (blank_run(b), MILL_BLANK)],
            "REMOVE_MOUNT": [(blank_run(b), "removal")],
            "PREP_MILL_FLIPPED": [(flip_run(b), "setup"), (flip_run(b), MILL_FLIPPED)],
        }.get(tt, [(b, tt)])
    if kind == "order":
        return [(rest.split(":", 1)[0], tt)]
    if tt == "REWORK":
        run = rework_run(rest.rsplit(":", 1)[0])
        return [(run, "setup"), (run, "REWORK")]
    if kind == "job":
        run = print_run(rest.split(":", 1)[0])
        return {"AM_PREP": [(run, "setup"), (run, PRINT)], "PART_POWDER_REMOVAL": [(run, "removal")]}[tt]
    carrier = rest.rsplit(":", 1)[0]
    if tt == "MILL_PREP_SECONDARY":
        return [(mill_run(carrier), "setup"), (mill_run(carrier), MILL)]
    if tt == "SECONDARY_PLATE_REMOVAL":
        return [(mill_run(carrier), "removal")]
    return [(carrier_id(carrier), tt)]


def id_map(problem: ProblemOut, ci: CompiledInstance) -> IdMap:
    """Every mapped MES key with the compiled operations it stands for."""
    out = {}
    for o in problem.instance.operations:
        if (cand := _candidates(o)) is not None:
            out[o.key] = tuple(k for k in cand if k in ci.op_index)
    return IdMap(out)


def build_snapshot(problem: ProblemOut, ci: CompiledInstance, ids: IdMap, *, epoch: datetime) -> Snapshot:
    """The snapshot at `as_of`, with today's break as taken where its window has begun (`taken_breaks`)."""
    t = at(problem.as_of, epoch)
    tasks = {task.key: task for task in problem.snapshot.tasks}
    frozen: list[FrozenOperation] = []
    for o in problem.instance.operations:
        if not ids.ops.get(o.key):  # not mapped (or of 0 minutes)
            continue
        task = tasks.get(o.key)
        if task is None:
            if o.done:
                raise MappingError(f"{o.key}: done, but the MES has no start time for it")
            continue
        frozen += _freeze(ci, task, ids.ops[o.key], t, epoch)
    return _consistent(ci, _one_task_one_worker(ci, frozen, problem, ids, t), t)


def _one_task_one_worker(
    ci: CompiledInstance, frozen: list[FrozenOperation], problem: ProblemOut, ids: IdMap, t: int
) -> list[FrozenOperation]:
    """One MES task can stand for several single-operation steps of the instance (a DATA_PREP_PRIMARY over two
    orders' primary parts, found in 3.1c): frozen as is, they would put its worker on all of them at once (C12). Its
    time is split into consecutive pieces of at least a minute, one per step (the worker did them one after another),
    in key order; only the last piece of a running task runs, the others finish at or before t."""
    by_task: dict[object, list[OpKey]] = {}
    for task in problem.snapshot.tasks:
        keys = ids.ops.get(task.key, ())
        if len(keys) == 1:
            by_task.setdefault(task.task_id, []).append(keys[0])
    pieces: dict[OpKey, FrozenOperation] = {}
    by = {(f.order_id, f.op_id): f for f in frozen}
    for keys in by_task.values():
        group = [by[k] for k in sorted(set(keys)) if k in by]
        if len(group) < 2:
            continue
        start, end, running = group[0].start, group[0].end, group[0].running
        done_until = min(end, t) if running else end  # the finished pieces fit before t
        n = len(group)
        step = max(1, (done_until - start) // n) if running else max(1, (end - start) // n)
        cursor = start
        for i, f in enumerate(group):
            last = i == n - 1
            s, e = cursor, (end if last else cursor + step)
            e = max(e, s + 1)
            lengths = tuple(
                e - s if sh.kind == "whole" else n_
                for sh, n_ in zip(ci.shares[ci.op_index[(f.order_id, f.op_id)]], f.share_lengths, strict=True)
            )
            pieces[(f.order_id, f.op_id)] = f.model_copy(
                update={
                    "start": s,
                    "end": e,
                    "running": running and last,
                    "share_lengths": lengths,
                }
            )
            cursor = e
    return [pieces.get((f.order_id, f.op_id), f) for f in frozen]


def _consistent(ci: CompiledInstance, frozen: list[FrozenOperation], t: int) -> Snapshot:
    """Facts in whole minutes can break the model's rules where the MES has seconds: a step that starts in the minute
    its predecessor finished, a predecessor stretched to the one-minute floor. In topological order, every frozen
    operation starts no earlier than its frozen predecessors end (found by the end-to-end run, 2.4); the snapshot time
    is at least every finished end, and a running operation ends after it. Moves a fact by at most the rounding."""
    by = {(f.order_id, f.op_id): f for f in frozen}
    for o in ci.topo_order:
        f = by.get(ci.op_keys[o])
        if f is None:
            continue
        after = max((by[ci.op_keys[p]].end for p in ci.predecessors[o] if ci.op_keys[p] in by), default=f.start)
        if after > f.start:
            start = after
            end = max(f.end, start + 1)
            lengths = tuple(
                end - start if sh.kind == "whole" else n for sh, n in zip(ci.shares[o], f.share_lengths, strict=True)
            )
            by[ci.op_keys[o]] = f.model_copy(update={"start": start, "end": end, "share_lengths": lengths})
    t = max([t, *(f.end for f in by.values() if not f.running), *(f.start for f in by.values() if f.running)])
    for k, f in by.items():
        if f.running and f.end <= t:
            end = t + 1
            lengths = tuple(
                end - f.start if sh.kind == "whole" else n
                for sh, n in zip(ci.shares[ci.op_index[k]], f.share_lengths, strict=True)
            )
            by[k] = f.model_copy(update={"end": end, "share_lengths": lengths})
    ordered = tuple(by[(f.order_id, f.op_id)] for f in frozen)
    return Snapshot(instance=ci.name, t=t, frozen=ordered, breaks=taken_breaks(ci, ordered, t))


def taken_breaks(ci: CompiledInstance, frozen: Sequence[FrozenOperation], t: int) -> tuple[Break, ...]:
    """Today's break per worker as a fact, once its window has begun by `t`.

    Shortcut (assumption): the MES records no breaks (task 4.3, finding rr), but the thesis snapshot carries every
    break started by t, as the DES does. Without them CP-SAT owes a worker the break of a day whose window is past
    and postpones it beyond the day (C14^f), which the night makes infeasible. So each worker took today's break at
    the earliest start in its window that is clear of their frozen work and has begun by t; a worker without such a
    start gets none (the planner then places it). Earlier days are history the model does not need."""
    cal = ci.calendar
    if cal is None or not ci.worker_ids:
        return ()
    d = day_index(cal, t)
    if not is_working_day(cal, d):
        return ()
    lo = day_start(cal, d) + cal.break_earliest
    hi = min(day_start(cal, d) + cal.break_latest, t)
    if lo > hi:
        return ()
    busy: dict[str, list[tuple[int, int]]] = {w: [] for w in ci.worker_ids}
    o_of = {key: o for o, key in enumerate(ci.op_keys)}
    for f in frozen:
        o = o_of[f.order_id, f.op_id]
        lengths = f.share_lengths or [sh.length for sh in ci.shares[o]]
        for sh, n, w in zip(ci.shares[o], lengths, f.workers, strict=False):
            if w is None:
                continue
            a = f.start if sh.kind == "prefix" else f.end - n if sh.kind == "suffix" else f.start
            e = a + n if sh.kind in ("prefix", "suffix") else f.end
            busy[w].append((a, e))
    out = []
    for w in ci.worker_ids:
        for b in sorted({lo, *(e for _, e in busy[w] if lo <= e <= hi)}):
            if all(e <= b or s >= b + cal.break_length for s, e in busy[w]):
                out.append(Break(worker=w, start=b))
                break
    return tuple(out)


def _freeze(ci: CompiledInstance, task: ProblemTaskOut, keys: tuple[OpKey, ...], t: int, epoch: datetime):
    start = at(task.started_at, epoch)
    finished = None if task.finished_at is None else at(task.finished_at, epoch)
    handoff = None if task.handoff_at is None else at(task.handoff_at, epoch)
    if len(keys) == 2:  # setup, then the unattended main operation from the handoff on
        setup, main = keys
        if handoff is None and finished is None:  # still setting up
            end = _expected(ci, task, setup, task.expected_attended_end, start, t, epoch)
            return [_frozen(ci, task, setup, start, end, running=True, t=t)]
        # every frozen operation lasts at least a minute (the format's end > start), also a setup handed off or a
        # task finished within the minute it started
        cut = max(start + 1, handoff if handoff is not None else finished)
        out = [_frozen(ci, task, setup, start, cut, running=False, t=t)]
        if finished is not None:
            return out + [_frozen(ci, task, main, cut, max(cut + 1, finished), running=False, t=t)]
        end = _expected(ci, task, main, task.expected_end, cut, t, epoch)
        return out + [_frozen(ci, task, main, cut, end, running=True, t=t)]
    if len(keys) == 1:
        (key,) = keys
        if finished is not None:
            return [_frozen(ci, task, key, start, max(start + 1, finished), running=False, t=t, handoff=handoff)]
        end = _expected(ci, task, key, task.expected_end, start, t, epoch)
        return [_frozen(ci, task, key, start, end, running=True, t=t, handoff=handoff)]
    return []  # a step of 0 minutes: nothing to freeze


def _planned(ci: CompiledInstance, key: OpKey, machine: str | None) -> int:
    o = ci.op_index[key]
    if machine is None:
        return ci.fixed_duration[o] or 1
    return dict(ci.options[o])[ci.machine_index[machine]]


def _expected(
    ci: CompiledInstance,
    task: ProblemTaskOut,
    key: OpKey,
    expected: datetime | None,
    start: int,
    t: int,
    epoch: datetime,
) -> int:
    """A running operation's end: the MES's expected end, else start + planned; never before t + 1 (snapshot())."""
    if expected is not None:
        return max(at(expected, epoch), t + 1)
    equipment = None if task.equipment_id is None else str(task.equipment_id)
    return max(start + _planned(ci, key, _machine_name(ci, key, equipment)), t + 1)


def _machine_name(ci: CompiledInstance, key: OpKey, equipment: str | None) -> str | None:
    """The machine of a frozen operation: the task's, or the only one the operation can run on."""
    options = ci.options[ci.op_index[key]]
    if not options:
        return None
    if equipment is not None and equipment in ci.machine_index:
        if ci.machine_index[equipment] not in {m for m, _ in options}:
            raise MappingError(f"{key}: ran on {equipment}, which it cannot run on in the instance")
        return equipment
    if len(options) == 1:
        return ci.machine_ids[options[0][0]]
    raise MappingError(f"{key}: started without a recorded machine and has {len(options)} options")


def _frozen(
    ci, task: ProblemTaskOut, key: OpKey, start: int, end: int, *, running: bool, t: int, handoff: int | None = None
) -> FrozenOperation:
    o = ci.op_index[key]
    worker = None if task.worker_id is None else str(task.worker_id)
    if worker is not None and worker not in ci.worker_ids:
        raise MappingError(f"{task.key}: worker {worker} is not in the instance (retired?)")
    if ci.shares[o] and worker is None:
        raise MappingError(f"{task.key}: started without a worker, but {key} needs one")
    lengths, workers = [], []
    for sh in ci.shares[o]:
        workers.append(worker)
        if sh.kind == "whole":
            lengths.append(end - start)
        elif sh.kind == "prefix":  # e.g. the oven: attended until the handoff, then its program
            if handoff is not None:
                lengths.append(max(1, handoff - start))
            elif running:
                lengths.append(max(sh.length, t + 1 - start))
            else:
                lengths.append(end - start)
        else:
            lengths.append(sh.length)
    machine = _machine_name(ci, key, None if task.equipment_id is None else str(task.equipment_id))
    return FrozenOperation(
        order_id=key[0],
        op_id=key[1],
        machine=machine,
        start=start,
        end=end,
        running=running,
        workers=tuple(workers),
        share_lengths=tuple(lengths),
    )


def group_started(group: Sequence[int], started: set[int]) -> bool:
    return any(o in started for o in group)


@dataclass(frozen=True)
class Pins:
    ci: CompiledInstance  # the instance with the pins
    pinned: tuple[OpKey, ...]  # operations restricted by an assignment
    skipped: tuple[str, ...]  # assignments that cannot hold, why (a machine or worker the step cannot use)


def pin(ci: CompiledInstance, problem: ProblemOut, ids: IdMap, started: set[OpKey]) -> Pins:
    """The BOUND variant (spec decision 4): an assignment pins every operation of its MES step that has not started:
    the assigned machine becomes its only option, the assigned worker the only qualified one of each of its worker
    shares. A started step keeps its facts (the task's worker and machine replace the assignment, as in the MES
    fill). Applied to the compiled instance, where options and qualified workers are per operation: in the format
    they are per step, shared by every carrier. An assignment naming a machine or worker the operation cannot use
    is skipped and reported, not an error: the MES lets a planner assign before data prep fixes the machine."""
    options, shares = list(ci.options), list(ci.shares)
    pinned, skipped = [], []
    machine_of = {m: i for i, m in enumerate(ci.machine_ids)}
    worker_of = {w: i for i, w in enumerate(ci.worker_ids)}
    # a run's setup, main operation and removal share one machine but may come from different MES steps: a machine
    # pin holds for the whole run, unless one of its operations started (then the facts fix the machine)
    group_of = {o: g for g in ci.machine_groups for o in g}
    started_idx = {ci.op_index[k] for k in started if k in ci.op_index}
    for a in problem.instance.assignments:
        for key in ids.ops.get(a.key, ()):
            if key in started:
                continue
            o = ci.op_index[key]
            if a.equipment_id is not None and options[o]:
                m = machine_of.get(str(a.equipment_id))
                group = group_of.get(o, (o,))
                keep = {g: tuple(opt for opt in options[g] if opt[0] == m) for g in group}
                if not group_started(group, started_idx) and all(keep.values()):
                    for g, opts in keep.items():
                        options[g] = opts
                else:
                    skipped.append(f"{a.key}: machine {a.equipment_id} cannot be pinned on {key}")
            if shares[o]:
                z = worker_of.get(str(a.worker_id))
                if z is not None and all(z in sh.workers for sh in shares[o]):
                    shares[o] = tuple(sh._replace(workers=(z,)) for sh in shares[o])
                else:
                    skipped.append(f"{a.key}: worker {a.worker_id} is not qualified for {key}")
            pinned.append(key)
    return Pins(replace(ci, options=tuple(options), shares=tuple(shares)), tuple(pinned), tuple(skipped))


def out_of_service(ci: CompiledInstance, problem: ProblemOut, started: set[OpKey]) -> CompiledInstance:
    """No new work on a machine that is DOWN or DECOMMISSIONED. `instance._options` already drops such a machine from
    a step unless a started task runs on it (the snapshot needs it there); options are per step in the format, so
    this removes it per operation from every other one, as `pin` does. A run with a started operation keeps its
    machine (the facts fix it); an operation left without an option keeps its options (a repair follows)."""
    from mes_bridge.instance import UNAVAILABLE  # noqa: PLC0415  (instance imports state)

    down = {ci.machine_index.get(str(m.id)) for m in problem.instance.machines if m.status in UNAVAILABLE} - {None}
    if not down:
        return ci
    options = list(ci.options)
    grouped = {o for g in ci.machine_groups for o in g}
    groups = [*ci.machine_groups, *((o,) for o in range(len(options)) if o not in grouped)]
    started_idx = {ci.op_index[k] for k in started if k in ci.op_index}
    for group in groups:  # a run's operations share one machine: filter them together
        if group_started(group, started_idx):
            continue
        keep = {o: tuple(opt for opt in options[o] if opt[0] not in down) for o in group}
        if all(keep.values()):
            for o, opts in keep.items():
                options[o] = opts
    return replace(ci, options=tuple(options))


def with_frozen_horizon(snapshot: Snapshot, current: Sequence[Assignment], minutes: int) -> Snapshot:
    """The snapshot with the frozen horizon (spec decision 19): every operation of the current plan that has not
    started and is planned to start before t + `minutes` is fixed with its planned machine, times and workers, as
    if it ran (Shiau, Chen & Fan 2026, Zotero F5VQRD7Z: machine and start time kept; math/05 lists the frozen horizon
    as an open point of the thesis, so it lives here). The planner plans the rest around them."""
    if minutes <= 0:
        return snapshot
    until = snapshot.t + minutes
    done = {(f.order_id, f.op_id) for f in snapshot.frozen}
    extra = tuple(
        FrozenOperation(
            order_id=a.order_id,
            op_id=a.op_id,
            machine=a.machine,
            start=a.start,
            end=a.end,
            running=True,
            workers=a.workers,
            share_lengths=a.share_lengths,
            batch=a.batch,
        )
        for a in current
        if (a.order_id, a.op_id) not in done and a.start < until
    )
    return snapshot.model_copy(update={"frozen": snapshot.frozen + extra}) if extra else snapshot
