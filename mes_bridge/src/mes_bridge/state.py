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

from dataclasses import dataclass
from datetime import datetime

from simulation.model.compiled import CompiledInstance
from simulation.sim.snapshot import FrozenOperation, Snapshot

from mes_bridge.api import ProblemOperationOut, ProblemOut, ProblemTaskOut
from mes_bridge.instance import LEFT_OUT, MILL, PRINT, MappingError, at, carrier_id, mill_run, print_run

OpKey = tuple[str, str]


@dataclass(frozen=True)
class IdMap:
    ops: dict[str, tuple[OpKey, ...]]  # MES key -> its instance operations, in time order

    def key_of(self) -> dict[OpKey, str]:
        return {k: key for key, ks in self.ops.items() for k in ks}


def _candidates(o: ProblemOperationOut) -> list[OpKey] | None:
    tt = o.task_type
    if tt in LEFT_OUT:
        return None
    kind, _, rest = o.key.partition(":")
    if kind == "order":
        return [(rest.split(":", 1)[0], tt)]
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
    """The snapshot at `as_of`. Breaks: none until the MES has break settings (task 4.3)."""
    t = at(problem.as_of, epoch)
    tasks = {task.key: task for task in problem.snapshot.tasks}
    frozen: list[FrozenOperation] = []
    for o in problem.instance.operations:
        if o.key not in ids.ops:
            continue
        task = tasks.get(o.key)
        if task is None:
            if o.done:
                raise MappingError(f"{o.key}: done, but the MES has no start time for it")
            continue
        frozen += _freeze(ci, task, ids.ops[o.key], t, epoch)
    return Snapshot(instance=ci.name, t=t, frozen=tuple(frozen))


def _freeze(ci: CompiledInstance, task: ProblemTaskOut, keys: tuple[OpKey, ...], t: int, epoch: datetime):
    start = at(task.started_at, epoch)
    finished = None if task.finished_at is None else at(task.finished_at, epoch)
    handoff = None if task.handoff_at is None else at(task.handoff_at, epoch)
    if len(keys) == 2:  # setup, then the unattended main operation from the handoff on
        setup, main = keys
        if handoff is None and finished is None:  # still setting up
            end = _expected(ci, task, setup, task.expected_attended_end, start, t, epoch)
            return [_frozen(ci, task, setup, start, end, running=True, t=t)]
        cut = handoff if handoff is not None else finished
        out = [_frozen(ci, task, setup, start, cut, running=False, t=t)]
        if finished is not None:
            return out + [_frozen(ci, task, main, cut, max(cut, finished), running=False, t=t)]
        end = _expected(ci, task, main, task.expected_end, cut, t, epoch)
        return out + [_frozen(ci, task, main, cut, end, running=True, t=t)]
    if len(keys) == 1:
        (key,) = keys
        if finished is not None:
            return [_frozen(ci, task, key, start, max(start, finished), running=False, t=t, handoff=handoff)]
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
                lengths.append(handoff - start)
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
