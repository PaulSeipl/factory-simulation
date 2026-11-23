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

import logging
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
    RunEstimator,
    SBatchStep,
    WorkerShare,
)

from mes_bridge.api import ProblemInstanceOut, ProblemOperationOut, ProblemOut, ProblemParamsOut

log = logging.getLogger(__name__)

# a machine in these MES statuses takes no new work (IDLE and RUNNING do; a busy machine is still planned on)
UNAVAILABLE = frozenset({"DOWN", "DECOMMISSIONED"})


class MappingError(ValueError):
    """The problem holds something the slice-1 mapping cannot express."""


PRINT, MILL = "AM_PRINT", "MILL_SECONDARY"  # instance steps of the run kinds on plates
MILL_BLANK, MILL_FLIPPED = "MILL_BLANK", "MILL_FLIPPED"  # and on blanks
# MES task type -> instance operation (= step); the other task types keep their name
OP_OF = {
    "AM_PREP": PRINT,
    "PART_POWDER_REMOVAL": PRINT,
    "MILL_PREP_SECONDARY": MILL,
    "SECONDARY_PLATE_REMOVAL": MILL,
    "MILL_PREP_PRIMARY": MILL_BLANK,
    "REMOVE_MOUNT": MILL_BLANK,
    "PREP_MILL_FLIPPED": MILL_FLIPPED,
}
BLANK_TASKS = {"MILL_PREP_PRIMARY", "REMOVE_MOUNT", "GEGENBETTEN", "PREP_MILL_FLIPPED", "PART_REMOVAL_FROM_BLANK"}
PLATE_STEPS = ("PART_CLEANING", "HEAT_TREATMENT", "SAND_BLASTING")  # carrier steps without runs
# carrier steps whose minutes vary with the carrier's parts: per-carrier runs over part times (math/21 §4: QM and
# sawing pay their base once per carrier inside the main operation, then the per-part time)
PER_CARRIER_STEPS = ("REWORK_CHECKOUT", "SAWING", "GEGENBETTEN", "PART_REMOVAL_FROM_BLANK")
CARRIER_TASKS = {*OP_OF, *PLATE_STEPS, *PER_CARRIER_STEPS}
MAPPED = {  # every route step after the arrival (slice 3)
    "DATA_PREP_SEC_MILL",
    "AM_PREP",
    "PART_POWDER_REMOVAL",
    "PART_CLEANING",
    "HEAT_TREATMENT",
    "SAND_BLASTING",
    "MILL_PREP_SECONDARY",
    "SECONDARY_PLATE_REMOVAL",
    "REWORK_CHECKOUT",
    "SAWING",
    "SUPPORT_REMOVAL",
    "GRIND_CLEAN",
    "STEAM_CLEAN",
    "POLISH",
    "INSPECTION",
    "DOCUMENTATION",
    "PACKAGING_SHIPPING",
    "DATA_PREP_PRIMARY",
    *BLANK_TASKS,
    "PRIMARY_POLISHING",
    "FINISHING_PRIMARY",
    "REWORK",
}
LEFT_OUT: set[str] = set()
# A rework round (decision 8: it comes with the QM verdict, an instance change): while a plate's rework request is
# open the MES has REWORK open and its QM done (suppressed); the re-check reopens the same QM key afterwards. The bridge
# plans the thesis route rework -> recheck (math/21 §4): QM (done) -> REWORK (a mill run) -> RECHECK -> sawing; RECHECK
# has no MES key until QM reopens, so it is planned but not published.
REWORK, RECHECK = "REWORK", "RECHECK"
LANE = "SECONDARY"


def carrier_id(key: str) -> str:
    """Instance id of the MES carrier `<am job>:<quadrant>`."""
    return f"C:{key}"


def blank_id(owner: UUID | str) -> str:
    """Instance id of a blank: its primary mill job's, or the order's before DATA_PREP_PRIMARY formed it (B2 (1) A:
    one assumed blank per order)."""
    return f"B:{owner}"


def blank_run(blank: str) -> str:
    return f"MB:{blank}"


def flip_run(blank: str) -> str:
    return f"MF:{blank}"


def rework_run(carrier_key: str) -> str:
    return f"RW:{carrier_key}"


def blank_of_key(key: str) -> str:
    """The blank a primary blank step's MES key names: `order:<order>:<task>` before data prep, `job:<mill job>:...`."""
    return blank_id(key.split(":")[1])


def print_run(am_job: UUID | str) -> str:
    return f"R:{am_job}"


def mill_run(carrier_key: str) -> str:
    return f"M:{carrier_key}"


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

    def __call__(self, task_type: str, lane: str = LANE) -> ProblemParamsOut:
        row = self._rows.get((task_type, lane)) or self._rows.get((task_type, None))
        if row is None:
            raise MappingError(f"no planning params for {task_type}")
        return row


def build_instance(problem: ProblemOut, *, epoch: datetime, name: str = "mes") -> Instance:
    inst = problem.instance
    ops = [o for o in inst.operations if o.task_type in MAPPED and o.task_type not in LEFT_OUT]
    for o in ops:
        if (
            o.task_type in CARRIER_TASKS - BLANK_TASKS
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
    carrier_of = {c.key: carrier_id(c.key) for c in inst.carriers}
    carriers_of_job: dict[UUID, list[str]] = defaultdict(list)
    for c in inst.carriers:
        carriers_of_job[c.am_job_id].append(c.key)
    jobs = {j.id: j for j in inst.jobs}

    if prints := by_type.get("AM_PREP", []):
        am = _options(problem, prints)
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
                    id=print_run(job.id),
                    step=PRINT,
                    carriers=tuple(carrier_of[k] for k in sorted(carriers_of_job[job.id])),
                    duration=mains[job.id],
                )
            )
        carrier_steps[PRINT] = _run_step(params("AM_PREP"), params("PART_POWDER_REMOVAL"), am, max(mains.values()))

    if mills := by_type.get("MILL_PREP_SECONDARY", []):
        ms = _options(problem, mills)
        if not ms:
            raise MappingError("the secondary mill has no plannable machine")
        machines |= set(ms)
        mains = {}
        for o in mills:
            key = _carrier_key(o)
            mains[key] = span(o.unattended_minutes)  # the mill job's entered minutes, else its params (MES)
            runs.append(Run(id=mill_run(key), step=MILL, carriers=(carrier_of[key],), duration=mains[key]))
        carrier_steps[MILL] = _run_step(
            params("MILL_PREP_SECONDARY"), params("SECONDARY_PLATE_REMOVAL"), ms, max(mains.values())
        )

    for tt in PLATE_STEPS:
        if group := by_type.get(tt):
            carrier_steps[tt], sb = _plate_step(tt, group, params(tt))
            if sb is not None:
                s_batches[tt] = sb

    blanks = _blanks(inst)
    for setup_tt, removal_tt, step, run_of in (
        ("MILL_PREP_PRIMARY", "REMOVE_MOUNT", MILL_BLANK, blank_run),
        ("PREP_MILL_FLIPPED", None, MILL_FLIPPED, flip_run),
    ):
        if group := by_type.get(setup_tt):
            ms = _options(problem, group)
            if not ms:
                raise MappingError(f"{setup_tt}: no plannable mill")
            machines |= set(ms)
            removal = {blank_of_key(o.key): o.attended_minutes for o in by_type.get(removal_tt or "", [])}
            row = params(removal_tt, "PRIMARY") if removal_tt else None
            mains = {}
            for o in group:
                b = blank_of_key(o.key)
                # shortcut: the run's removal is one value per step (the base); the per-part rest of the MES removal
                # (REMOVE_MOUNT 10 + 2 per part) is added to the unattended run, so the mill's time stays exact and
                # the worker misses that rest; lift with per-carrier setups and removals in the format
                extra = span(removal[b]) - span(row.base_minutes_attended) if b in removal and row else 0
                mains[b] = span(o.unattended_minutes) + max(0, extra)
                runs.append(Run(id=run_of(b), step=step, carriers=(b,), duration=mains[b]))
            carrier_steps[step] = _run_step(
                params(setup_tt, "PRIMARY"), row, ms, max(mains.values()), per_part_removal_folded=True
            )

    part_times: dict[UUID, dict[str, int]] = defaultdict(dict)
    parts_on = {carrier_id(c.key): c.part_ids for c in inst.carriers} | blanks
    for tt in PER_CARRIER_STEPS:
        if group := by_type.get(tt):
            row = params(tt, group[0].lane)
            carrier_steps[tt] = _per_carrier_step(problem, tt, group, parts_on, part_times, row)
            machines |= set(carrier_steps[tt].options)

    if reworks := by_type.get(REWORK):
        ms = _options(problem, reworks)
        if not ms:
            raise MappingError("REWORK: no plannable mill")
        if "REWORK_CHECKOUT" not in carrier_steps:
            raise MappingError("REWORK without its plate's QM in the problem")
        machines |= set(ms)
        row = params(REWORK)
        setup = span(row.base_minutes_attended)
        mains = {}
        for o in reworks:
            key = _carrier_key(o)
            # shortcut: a run's setup is one value per step (the base); the per-telescope attended minutes of REWORK
            # (20 + 10 per telescope) go into the unattended run: the mill's time stays exact, the worker misses them
            mains[key] = max(1, span(o.attended_minutes + o.unattended_minutes) - setup)
            runs.append(Run(id=rework_run(key), step=REWORK, carriers=(carrier_of[key],), duration=mains[key]))
            for part in parts_on[carrier_id(key)]:
                part_times[part][RECHECK] = part_times[part]["REWORK_CHECKOUT"]
        carrier_steps[REWORK] = CarrierStep(
            options=dict.fromkeys(ms, max(mains.values())), runs="given", setup=setup, setup_attended=True
        )
        carrier_steps[RECHECK] = carrier_steps["REWORK_CHECKOUT"]

    orders = _orders(problem, ops, cal, epoch, part_times, blanks)
    # a blank is a carrier while a blank step still acts on it (a separated blank has none, V15)
    used_blanks = {blank_of_key(o.key) for o in ops if o.task_type in BLANK_TASKS}
    return Instance(
        schema_version="0.8",
        name=name,
        machines=tuple(sorted(machines)),
        orders=orders,
        carrier_steps=carrier_steps,
        carriers=(
            *(
                Carrier(id=carrier_of[c.key], parts=tuple((str(_order_of(inst, p)), str(p)) for p in c.part_ids))
                for c in sorted(inst.carriers, key=lambda c: c.key)
            ),
            *(
                Carrier(id=b, parts=tuple((str(_order_of(inst, p)), str(p)) for p in ps))
                for b, ps in sorted(blanks.items())
                if b in used_blanks
            ),
        ),
        runs=tuple(runs),
        calendar=cal,
        workers=tuple(str(w.id) for w in inst.workers),
        s_batch_steps=s_batches,
    )


def _carrier_key(o: ProblemOperationOut) -> str:
    return o.key.removeprefix("carrier:").rsplit(":", 1)[0]


def _carrier_of_op(o: ProblemOperationOut) -> str:
    """Instance id of the carrier a carrier operation of the export acts on."""
    return blank_of_key(o.key) if o.task_type in BLANK_TASKS else carrier_id(_carrier_key(o))


def _blanks(inst: ProblemInstanceOut) -> dict[str, list[UUID]]:
    """blank -> its primary parts: the mill job's once DATA_PREP_PRIMARY formed it, else one blank per order."""
    out: dict[str, list[UUID]] = defaultdict(list)
    for p in inst.parts:
        if p.part_type == "PRIMARY":
            out[blank_id(p.mill_job_id or p.order_id)].append(p.id)
    return {b: sorted(ps) for b, ps in out.items()}


def _order_of(inst: ProblemInstanceOut, part: UUID) -> UUID:
    return next(p.order_id for p in inst.parts if p.id == part)


def _options(problem: ProblemOut, group: list[ProblemOperationOut]) -> list[str]:
    """The machines a step of `group` may use: the operations' options without machines that are DOWN or
    DECOMMISSIONED (the export lists every plannable machine with its status). Options are per step in the format, so
    the filter is on the union. Kept regardless: a machine a started task runs on (the snapshot freezes that
    operation there, `state._machine_name` needs it as an option), and all of them if none would be left (the only
    machine is down: plan on it anyway, a repair follows)."""
    options = {str(m) for o in group for m in o.machine_options}
    out_of_service = {str(m.id) for m in problem.instance.machines if m.status in UNAVAILABLE}
    in_use = {str(t.equipment_id) for t in problem.snapshot.tasks if t.equipment_id is not None}
    usable = {m for m in options if m not in out_of_service or m in in_use}
    if options and not usable:
        log.warning(
            "%s: every machine is down or decommissioned (%s), keeping them as options",
            sorted({o.task_type for o in group}),
            sorted(options),
        )
        return sorted(options)
    return sorted(usable)


def _run_step(
    prep: ProblemParamsOut,
    removal: ProblemParamsOut | None,
    machines: list[str],
    main: int,
    per_part_removal_folded: bool = False,
) -> CarrierStep:
    """A step in given runs: setup = prep's attended minutes, removal = removal's (none without), each base + per
    plate. The unattended minutes of the setup row are the run itself (Run.duration), not a separate operation.
    `per_part_removal_folded`: the removal's per-part minutes are in Run.duration (the caller added them)."""
    if prep.unit_kind != "PLATE" and prep.per_unit_minutes_attended:
        raise MappingError(f"{prep.task_type}: attended minutes per {prep.unit_kind} vary per run within a plate")
    if removal is not None:
        if removal.unit_kind != "PLATE" and removal.per_unit_minutes_attended and not per_part_removal_folded:
            raise MappingError(f"{removal.task_type}: attended minutes per {removal.unit_kind} vary per run")
        if removal.base_minutes_unattended or removal.per_unit_minutes_unattended:
            raise MappingError(f"{removal.task_type}: an unattended removal is not mapped")
    return CarrierStep(
        # every run carries its own duration (Run.duration); the constant is a placeholder the runs override
        options=dict.fromkeys(machines, main),
        runs="given",
        setup=span(prep.base_minutes_attended),
        setup_per_carrier=_per_plate(prep) if prep.unit_kind == "PLATE" else 0,
        removal=span(removal.base_minutes_attended) if removal else 0,
        removal_per_carrier=_per_plate(removal) if removal and removal.unit_kind == "PLATE" else 0,
        setup_attended=True,
        removal_attended=removal is not None,
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


def _per_carrier_step(
    problem: ProblemOut,
    tt: str,
    group: list[ProblemOperationOut],
    parts_on: dict[str, list[UUID]],
    part_times: dict[UUID, dict[str, int]],
    row: ProblemParamsOut,
) -> CarrierStep:
    """A carrier step whose minutes vary per carrier: one run per carrier (`per_carrier`) whose main operation is the
    params' base once per carrier (estimator base: attended base + unattended minutes, math/21 §4) plus its parts'
    times (fixed 0, share 1: no clamp effect), the rest of the carrier's MES minutes split over its parts (whole
    minutes, the remainder to the first parts). Unattended minutes are a rest at the end (no machine), e.g. curing.
    On the step's machine if the MES names one."""
    options = _options(problem, group)
    unattended = {span(o.unattended_minutes) if o.unattended_minutes else 0 for o in group}
    if len(unattended) > 1:
        raise MappingError(f"{tt}: unattended minutes differ between carriers {sorted(unattended)}")
    (rest,) = unattended
    if rest and options:
        raise MappingError(f"{tt}: unattended minutes on a machine are not mapped")
    base = span(row.base_minutes_attended) + rest if row.base_minutes_attended or rest else 0
    longest = 1
    for o in group:
        minutes, parts = span(o.attended_minutes + o.unattended_minutes), sorted(parts_on[_carrier_of_op(o)])
        if minutes - base < len(parts):
            raise MappingError(f"{o.key}: {minutes} min for {len(parts)} parts, below one minute per part")
        each, extra = divmod(minutes - base, len(parts))
        for i, part in enumerate(parts):
            part_times[part][tt] = each + (1 if i < extra else 0)
        longest = max(longest, minutes)
    estimator = RunEstimator(fixed=0, share=1.0, base=base)
    worker = WorkerShare(rest=rest) if rest else WorkerShare(whole=True)
    if options:
        return CarrierStep(
            options=dict.fromkeys(options, longest), runs="per_carrier", estimator=estimator, worker=worker
        )
    return CarrierStep(duration=longest, runs="per_carrier", estimator=estimator, worker=worker)


def _calendar(inst: ProblemInstanceOut) -> Calendar:
    """Decision 20: global; the most common daily minutes and workdays; overtime is the MES setting
    `max_overtime_minutes` (global, default 0). The break window and length are the MES's settings (decision 21); the
    shift is the daily minutes plus the break, as fill.py lengthens the day."""
    if not inst.workers:
        raise MappingError("no workers")
    daily = Counter(w.daily_minutes for w in inst.workers).most_common(1)[0][0]
    days = Counter(tuple(sorted(w.workdays)) for w in inst.workers).most_common(1)[0][0]
    c = inst.calendar
    start = c.day_start.hour * 60 + c.day_start.minute
    return Calendar(
        origin=0,
        shift_start=start,
        shift_end=start + daily + c.break_minutes,
        break_earliest=c.break_earliest.hour * 60 + c.break_earliest.minute,
        break_latest=c.break_latest.hour * 60 + c.break_latest.minute,
        break_length=c.break_minutes,
        max_overtime=c.max_overtime_minutes,
        working_days=tuple(d - 1 for d in days),  # ISO 1 = Monday -> 0
    )


def _orders(
    problem: ProblemOut,
    ops: list[ProblemOperationOut],
    cal: Calendar,
    epoch: datetime,
    part_times: dict[UUID, dict[str, int]],
    blanks: dict[str, list[UUID]],
) -> tuple[Order, ...]:
    inst = problem.instance
    exported = {o.key: o for o in ops}
    op_id = {o.key: OP_OF.get(o.task_type, o.task_type) for o in ops}
    parts_of: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
    for p in inst.parts:
        if p.carrier is not None or p.part_type == "PRIMARY":
            parts_of[p.order_id].append((p.id, p.part_type.lower()))
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
            if o.key.startswith("order:") and o.task_type not in BLANK_TASKS:
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
                        carries=o.lane.lower(),
                        role="form" if a in (PRINT, MILL_BLANK) else None,
                        predecessors=tuple(sorted(preds[a])),
                    )
                )
        # the carrier chain ends in a separating operation (V14): SAWING once the plate reaches it; the last carrier
        # operation in the instance takes the role, so a chain cut short (sawing done, or not in the export) still
        # validates (the role only shapes validation)
        operations = _rework_round(order.id, operations)
        tails = set()
        for kind in {o.carries for o in operations if o.scope == CARRIER}:
            chain = {o.id for o in operations if o.scope == CARRIER and o.carries == kind}
            tails |= chain - {q for o in operations if o.id in chain for q in o.predecessors}
        operations = [
            o.model_copy(update={"role": "separate"}) if o.id in tails and o.role != "form" else o for o in operations
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
                parts=tuple(
                    Part(id=str(p), type=t, times=part_times.get(p, {})) for p, t in sorted(parts_of[order.id])
                ),
                operations=tuple(_topological(operations)),
            )
        )
    return tuple(out)


def _rework_round(order_id: UUID, operations: list[Operation]) -> list[Operation]:
    """QM (done) -> REWORK -> RECHECK -> what followed QM, when the order's plate is in a rework round."""
    ids = {o.id for o in operations}
    if REWORK not in ids:
        return operations
    out = []
    for o in operations:
        if o.id == REWORK:
            out.append(o.model_copy(update={"predecessors": ("REWORK_CHECKOUT",)}))
        elif "REWORK_CHECKOUT" in o.predecessors:
            preds = tuple(sorted({RECHECK if q == "REWORK_CHECKOUT" else q for q in o.predecessors}))
            out.append(o.model_copy(update={"predecessors": preds}))
        else:
            out.append(o)
    qm = next(o for o in operations if o.id == "REWORK_CHECKOUT")
    out.append(qm.model_copy(update={"id": RECHECK, "step": RECHECK, "predecessors": (REWORK,), "role": None}))
    return out


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
