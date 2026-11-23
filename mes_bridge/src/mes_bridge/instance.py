"""MES problem → thesis `Instance` (task 1.5b, slice 1: the SECONDARY lane).

Mapping (Blocked B1, answered 2026-11-23):
- an MES carrier (one plate of one print) is a `Carrier`; the print is a given `Run` per AM job over its plates,
  AM_PREP its setup and main operation, PART_POWDER_REMOVAL its removal; the secondary mill chain is a given
  `Run` per plate (one mill job per plate), MILL_PREP_SECONDARY its setup and main, SECONDARY_PLATE_REMOVAL its
  removal; cleaning, heat treatment and blasting are carrier steps without runs; DATA_PREP_SEC_MILL is an order
  operation.
- The step shape (setup = base + per plate, removal likewise, s-batch setup) comes from the MES `params`; minutes
  that the format holds per instance come from the operations: `Run.duration` (the job's entered minutes, else
  the MES estimate) and `Operation.duration`.
- Time (decision 17): integer minutes from Monday 00:00 of the bridge's start week in the MES time zone
  (`Calendar.origin = 0`), MES minutes rounded up, instants before the epoch clamped to 0.

What the format cannot hold raises `MappingError`, never a silent approximation. The `Instance` validation is
the second line: an inconsistency the mapping lets through fails there.
"""

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from simulation.calendar import next_cutoff
from simulation.model.instance import (
    CARRIER,
    Calendar,
    Carrier,
    CarrierStep,
    Instance,
    Operation,
    Order,
    Part,
    Run,
    SBatchStep,
    WorkerShare,
)

from mes_bridge.api import ProblemInstanceOut, ProblemOperationOut, ProblemOut, ProblemParamsOut


class MappingError(ValueError):
    """The problem holds something the slice-1 mapping cannot express."""


PRINT, MILL = "AM_PRINT", "MILL_SECONDARY"  # instance steps of the two run kinds
# MES task type -> instance operation (= step); the other task types keep their name
OP_OF = {"AM_PREP": PRINT, "PART_POWDER_REMOVAL": PRINT, "MILL_PREP_SECONDARY": MILL, "SECONDARY_PLATE_REMOVAL": MILL}
PLATE_STEPS = ("PART_CLEANING", "HEAT_TREATMENT", "SAND_BLASTING")  # carrier steps without runs
CARRIER_TASKS = {*OP_OF, *PLATE_STEPS}
LEFT_OUT = {"REWORK"}  # its predecessor QM is out of scope until slice 3 (decision 8: it comes with the verdict)
LANE = "SECONDARY"
# shortcut: today's MES break 12:00, 60 min (decision 21), hard-coded until the break settings exist (task 4.3)
BREAK_START, BREAK_LENGTH = 720, 60


def epoch_of(t: datetime, tz: ZoneInfo) -> datetime:
    """Monday 00:00 (local time in `tz`) of the week holding `t`."""
    local = t.astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).date()
    return datetime(monday.year, monday.month, monday.day, tzinfo=tz)


def at(t: datetime, epoch: datetime) -> int:
    """Instant -> minutes since the epoch, rounded up, clamped to 0 (aware subtraction: absolute time)."""
    return max(0, math.ceil((t - epoch).total_seconds() / 60 - 1e-9))


def span(minutes: float) -> int:
    """MES minutes -> a positive integer duration, rounded up; a 0-minute step takes 1 (the format needs > 0)."""
    return max(1, math.ceil(round(minutes, 6)))


class _Params:
    def __init__(self, rows: list[ProblemParamsOut]):
        self._rows = {(r.task_type, r.part_type): r for r in rows if r.task_type is not None}

    def __call__(self, task_type: str) -> ProblemParamsOut:
        row = self._rows.get((task_type, LANE)) or self._rows.get((task_type, None))
        if row is None:
            raise MappingError(f"no planning params for {task_type}")
        return row


def build_instance(problem: ProblemOut, *, epoch: datetime, name: str = "mes") -> Instance:
    inst = problem.instance
    ops = [o for o in inst.operations if o.task_type not in LEFT_OUT]
    for o in ops:
        if o.lane != LANE:
            raise MappingError(f"{o.key}: lane {o.lane} is not mapped in slice 1")
        if (
            o.task_type in CARRIER_TASKS
            and o.task_type not in ("AM_PREP", "PART_POWDER_REMOVAL")
            and not (o.key.startswith("carrier:"))
        ):
            raise MappingError(
                f"{o.key}: a plate step on a job key (a print without quadrants), its plates are unknown"
            )
    params = _Params(inst.params)
    cal = _calendar(inst)
    by_type: dict[str, list[ProblemOperationOut]] = defaultdict(list)
    for o in ops:
        by_type[o.task_type].append(o)

    carrier_steps: dict[str, CarrierStep] = {}
    s_batches: dict[str, SBatchStep] = {}
    machines: set[str] = set()
    runs: list[Run] = []
    carrier_of = {c.key: f"C:{c.key}" for c in inst.carriers}
    carriers_of_job: dict[UUID, list[str]] = defaultdict(list)
    for c in inst.carriers:
        carriers_of_job[c.am_job_id].append(c.key)
    jobs = {j.id: j for j in inst.jobs}

    if prints := by_type.get("AM_PREP", []):
        am = sorted({str(m) for o in prints for m in o.machine_options})
        if not am:
            raise MappingError("the print has no plannable machine")
        machines |= set(am)
        mains = {}
        for o in prints:
            job = jobs[o.job_id] if o.job_id in jobs else None
            if job is None:
                raise MappingError(f"{o.key}: the AM job is not in the problem")
            entered = job.estimated_duration_minutes
            mains[job.id] = span(entered if entered is not None else o.unattended_minutes)
            runs.append(
                Run(
                    id=f"R:{job.id}",
                    step=PRINT,
                    carriers=tuple(carrier_of[k] for k in sorted(carriers_of_job[job.id])),
                    duration=mains[job.id],
                )
            )
        carrier_steps[PRINT] = _run_step(params("AM_PREP"), params("PART_POWDER_REMOVAL"), am, max(mains.values()))

    if mills := by_type.get("MILL_PREP_SECONDARY", []):
        ms = sorted({str(m) for o in mills for m in o.machine_options})
        if not ms:
            raise MappingError("the secondary mill has no plannable machine")
        machines |= set(ms)
        mains = {}
        for o in mills:
            key = _carrier_key(o)
            mains[key] = span(o.unattended_minutes)  # the mill job's entered minutes, else its params (MES)
            runs.append(Run(id=f"M:{key}", step=MILL, carriers=(carrier_of[key],), duration=mains[key]))
        carrier_steps[MILL] = _run_step(
            params("MILL_PREP_SECONDARY"), params("SECONDARY_PLATE_REMOVAL"), ms, max(mains.values())
        )

    for tt in PLATE_STEPS:
        if group := by_type.get(tt):
            carrier_steps[tt], sb = _plate_step(tt, group, params(tt))
            if sb is not None:
                s_batches[tt] = sb

    orders = _orders(problem, ops, cal, epoch)
    return Instance(
        schema_version="0.8",
        name=name,
        machines=tuple(sorted(machines)),
        orders=orders,
        carrier_steps=carrier_steps,
        carriers=tuple(
            Carrier(id=carrier_of[c.key], parts=tuple((str(_order_of(inst, p)), str(p)) for p in c.part_ids))
            for c in sorted(inst.carriers, key=lambda c: c.key)
        ),
        runs=tuple(runs),
        calendar=cal,
        workers=tuple(str(w.id) for w in inst.workers),
        s_batch_steps=s_batches,
    )


def _carrier_key(o: ProblemOperationOut) -> str:
    return o.key.removeprefix("carrier:").rsplit(":", 1)[0]


def _order_of(inst: ProblemInstanceOut, part: UUID) -> UUID:
    return next(p.order_id for p in inst.parts if p.id == part)


def _run_step(prep: ProblemParamsOut, removal: ProblemParamsOut, machines: list[str], main: int) -> CarrierStep:
    """A step in given runs: setup = prep's attended minutes, removal = removal's, each base + per plate."""
    for row in (prep, removal):
        if row.unit_kind != "PLATE" and row.per_unit_minutes_attended:
            raise MappingError(f"{row.task_type}: attended minutes per {row.unit_kind} vary per run within a plate")
    if prep.base_minutes_unattended or prep.per_unit_minutes_unattended:
        raise MappingError(f"{prep.task_type}: unattended setup minutes besides the run are not mapped")
    if removal.base_minutes_unattended or removal.per_unit_minutes_unattended:
        raise MappingError(f"{removal.task_type}: an unattended removal is not mapped")
    return CarrierStep(
        # every run carries its own duration (Run.duration); the constant is a placeholder the runs override
        options=dict.fromkeys(machines, main),
        runs="given",
        setup=span(prep.base_minutes_attended),
        setup_per_carrier=_per_plate(prep) if prep.unit_kind == "PLATE" else 0,
        removal=span(removal.base_minutes_attended),
        removal_per_carrier=_per_plate(removal) if removal.unit_kind == "PLATE" else 0,
        setup_attended=True,
        removal_attended=True,
    )


def _per_plate(row: ProblemParamsOut) -> int:
    return span(row.per_unit_minutes_attended) if row.per_unit_minutes_attended else 0


def _plate_step(
    tt: str, group: list[ProblemOperationOut], row: ProblemParamsOut
) -> tuple[CarrierStep, SBatchStep | None]:
    """A carrier step without runs: one duration for every carrier (the format's), so the MES minutes must agree."""
    minutes = {(o.attended_minutes, o.unattended_minutes) for o in group}
    if len(minutes) > 1:
        raise MappingError(f"{tt}: minutes differ between carriers {sorted(minutes)}; one per step in the format")
    if any(o.machine_options for o in group):
        raise MappingError(f"{tt}: a plate step on a machine is not mapped in slice 1")
    ((att, unatt),) = minutes
    duration = span(att + unatt)
    # shortcut: the oven (resource OVEN) has no machine in the export (_MACHINE_TYPE maps only AM and MILL), so it
    # is a worker step with an unattended rest and no p-batch (no machine, V22); give it the oven once mapped
    worker = WorkerShare(rest=duration - span(att)) if unatt else WorkerShare(whole=True)
    step = CarrierStep(duration=duration, worker=worker)
    # the MES's linear form base + per_unit x plates is an s-batch: setup once, every further plate per_unit
    batch = (
        SBatchStep(setup=span(row.base_minutes_attended), capacity=row.max_batch_size)
        if not unatt and row.unit_kind == "PLATE" and row.per_unit_minutes_attended and (row.max_batch_size or 2) > 1
        else None
    )
    return step, batch


def _calendar(inst: ProblemInstanceOut) -> Calendar:
    """Decision 20: global; the most common daily minutes and workdays; no overtime. The shift is the daily minutes
    plus the break, so a worker keeps the capacity the MES plans with (fill.py has no break yet)."""
    if not inst.workers:
        raise MappingError("no workers")
    daily = Counter(w.daily_minutes for w in inst.workers).most_common(1)[0][0]
    days = Counter(tuple(sorted(w.workdays)) for w in inst.workers).most_common(1)[0][0]
    start = inst.calendar.day_start.hour * 60 + inst.calendar.day_start.minute
    return Calendar(
        origin=0,
        shift_start=start,
        shift_end=start + daily + BREAK_LENGTH,
        break_earliest=BREAK_START,
        break_latest=BREAK_START,
        break_length=BREAK_LENGTH,
        max_overtime=0,
        working_days=tuple(d - 1 for d in days),  # ISO 1 = Monday -> 0
    )


def _orders(problem: ProblemOut, ops: list[ProblemOperationOut], cal: Calendar, epoch: datetime) -> tuple[Order, ...]:
    inst = problem.instance
    exported = {o.key: o for o in ops}
    op_id = {o.key: OP_OF.get(o.task_type, o.task_type) for o in ops}
    parts_of: dict[UUID, list[UUID]] = defaultdict(list)
    for p in inst.parts:
        if p.carrier is not None:
            parts_of[p.order_id].append(p.id)
        elif p.part_type == LANE:
            raise MappingError(f"part {p.id}: a secondary part on no known plate")

    out = []
    for order in inst.orders:
        mine = [o for o in ops if order.id in o.order_ids]
        preds: dict[str, set[str]] = defaultdict(set)
        for o in mine:
            a = op_id[o.key]
            preds[a]  # every operation, also one without predecessors
            for d in o.predecessors:
                if d in exported and order.id in exported[d].order_ids and op_id[d] != a:
                    preds[a].add(op_id[d])
        operations = []
        for o in sorted({op_id[o.key]: o for o in mine}.values(), key=lambda o: op_id[o.key]):
            a = op_id[o.key]
            if o.key.startswith("order:"):
                if o.machine_options:
                    raise MappingError(f"{o.key}: an order step on a machine is not mapped in slice 1")
                d = span(o.attended_minutes + o.unattended_minutes)
                worker = (
                    WorkerShare(rest=d - span(o.attended_minutes)) if o.unattended_minutes else WorkerShare(whole=True)
                )
                operations.append(
                    Operation(id=a, step=a, duration=d, predecessors=tuple(sorted(preds[a])), worker=worker)
                )
            else:
                operations.append(
                    Operation(
                        id=a,
                        step=a,
                        scope=CARRIER,
                        carries=LANE.lower(),
                        role="form" if a == PRINT else None,
                        predecessors=tuple(sorted(preds[a])),
                    )
                )
        # shortcut: the format needs the carrier chain to end in a separating operation (V14), but the slice-1
        # scope ends before SAWING; the last carrier operation in scope takes the role, which only shapes validation
        # (nothing in the instance follows it). Slice 3 maps SAWING as the real separation.
        carrier_ops = {o.id for o in operations if o.scope == CARRIER}
        tails = carrier_ops - {q for o in operations if o.id in carrier_ops for q in o.predecessors}
        operations = [
            o.model_copy(update={"role": "separate"}) if o.id in tails and o.id != PRINT else o for o in operations
        ]
        arrival = at(order.arrival or problem.as_of, epoch)
        due = None
        if order.due_date is not None:
            raw = (order.due_date - epoch.date()).days * 1440 + cal.cutoff
            # shortcut: an overdue order gets the first cutoff at or after its release (V10, V11), so its tardiness
            # is understated; keep the real due date once the format allows a due date before the release
            due = next_cutoff(cal, max(raw, arrival))
        out.append(
            Order(
                id=str(order.id),
                accepted=arrival,
                arrival=arrival,
                release=arrival,
                due_date=due,
                parts=tuple(Part(id=str(p), type=LANE.lower()) for p in sorted(parts_of[order.id])),
                operations=tuple(_topological(operations)),
            )
        )
    return tuple(out)


def _topological(operations: list[Operation]) -> list[Operation]:
    """Predecessors first (readable files; the format does not need it)."""
    done: set[str] = set()
    out = []
    pending = list(operations)
    while pending:
        ready = [o for o in pending if set(o.predecessors) <= done] or pending[:1]  # a cycle: let validation say so
        for o in ready:
            out.append(o)
            done.add(o.id)
            pending.remove(o)
    return out
