import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Literal, NamedTuple

from graphlib import CycleError, TopologicalSorter
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from simulation.calendar import next_cutoff

ORDER = "order"  # scope: the operation acts on all parts of the order
CARRIER = "carrier"  # scope: executed by every carrier that holds parts of the order (math/03_carriers.md)


def _duplicates(ids) -> list[str]:
    return sorted(k for k, n in Counter(ids).items() if n > 1)


class WorkerShare(BaseModel):
    """Worker time of an operation (math/04_workers.md): the whole operation, or a prefix and/or a suffix of it
    (e.g. oven: loading and removal around a fixed program); the rest runs without a worker. Prefix and suffix
    may be served by different workers. qualified: allowed workers, None = every worker of the instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    whole: bool = False
    prefix: NonNegativeInt = 0
    suffix: NonNegativeInt = 0
    qualified: tuple[str, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def check_kind(self):
        if self.whole == bool(self.prefix + self.suffix):
            raise ValueError("worker share: either whole, or a prefix and/or suffix > 0")
        return self


class Operation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str  # unique inside an order; globally (order.id, op.id)
    step: str  # process step like "print"; may repeat within and across orders
    # Machine ID -> duration; None for carrier operations (durations from Instance.carrier_steps).
    # shortcut: dict stays mutable despite frozen=True,
    # switch to frozendict once on Python >= 3.15 (pydantic >= 2.14 supports it)
    options: dict[str, PositiveInt] | None = Field(default=None, min_length=1)
    predecessors: tuple[str, ...] = ()  # op IDs of the same order
    scope: str = ORDER  # "order", a part type of the order, or "carrier"
    role: Literal["form", "separate"] | None = None  # carrier operations: binds / releases the parts
    # carrier operations: part type on the carrier that executes it (e.g. "primary" on a blank, "secondary" on a
    # build plate); None: the order's only carrier kind
    carries: str | None = None
    duration: PositiveInt | None = None  # operation without a machine (manual step, rest); exclusive with options
    worker: WorkerShare | None = None  # order operations; carrier operations take it from their carrier step


class Part(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str  # unique inside an order; globally (order.id, part.id)
    type: str  # e.g. "secondary" (printed on a carrier), "primary" (milled)
    times: dict[str, PositiveInt] = {}  # carrier step -> time of this part alone (e.g. print), for the run estimator


class Order(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    # accepted <= arrival <= release (math/07_order-arrivals.md); defaults: known from the start
    accepted: NonNegativeInt = 0  # released for design by sales; the due-date clock starts here
    arrival: NonNegativeInt = 0  # nesting batch done: the planning tool learns the order
    release: NonNegativeInt = 0  # earliest start time
    due_date: NonNegativeInt | None = None  # soft: completing later is tardy, not infeasible
    parts: tuple[Part, ...] = ()
    operations: tuple[Operation, ...]


class RunEstimator(BaseModel):
    """Parameters of estimate_run_duration (an assumption until validated with Fidentis data, math/03_carriers.md)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    fixed: NonNegativeInt = 0  # minutes per run, independent of its content
    share: float = Field(ge=0, le=1)  # share of the summed part times that the run takes in addition


class CarrierStep(BaseModel):
    """Durations of a carrier step; setup and removal only for steps executed in runs (0: no such operation).

    runs: "none" (one operation per carrier), "given" (runs from nesting, Instance.runs) or "per_carrier" (every
    carrier is its own run, e.g. milling the parts of one carrier; math/03_carriers.md).
    The main operation of a run takes, in this order: the duration reported by nesting (Run.duration), the
    estimate from the parts of the run (if an estimator is given), the constant per machine in options.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    options: dict[str, PositiveInt] = Field(min_length=1)
    runs: Literal["none", "given", "per_carrier"] = "none"
    setup: NonNegativeInt = 0
    removal: NonNegativeInt = 0
    estimator: RunEstimator | None = None
    # p-batch decided by the planner (e.g. oven): up to this many carriers share one machine run, starting and
    # ending together; the program fixes the duration (no deviation in scenarios). None: one carrier per operation
    batch_capacity: int | None = Field(default=None, ge=2)
    worker: WorkerShare | None = None  # of the main operation; for a batch step one share per machine run
    setup_attended: bool = False  # setup / removal operations of the runs need a worker for their whole duration
    removal_attended: bool = False


class Carrier(BaseModel):
    """A build plate with its parts, bound from the forming to the separating operation (nesting output)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    parts: tuple[tuple[str, str], ...] = Field(min_length=1)  # (order_id, part_id)


class Run(BaseModel):
    """A machine run whose load is several carriers, e.g. up to four plates in one print (nesting output)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    step: str
    carriers: tuple[str, ...] = Field(min_length=1)
    duration: PositiveInt | None = None  # reported by nesting for this layout; overrides the estimator


class Calendar(BaseModel):
    """Work calendar (math/04_workers.md, section 2): times are minutes of the day, `origin` the minute of the week
    (Monday 00:00 = 0) at t = 0; days 0 = Monday ... 6 = Sunday. Defaults: the dental factory (user, 2026-11-05)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    origin: NonNegativeInt = 480  # t = 0 is Monday 08:00
    shift_start: NonNegativeInt = 480
    shift_end: PositiveInt = 1050
    break_earliest: NonNegativeInt = 720  # break start window [earliest, latest]
    break_latest: NonNegativeInt = 780
    break_length: PositiveInt = 60
    max_overtime: NonNegativeInt = 120  # shift end at most shift_end + max_overtime
    cutoff: NonNegativeInt = 720  # courier pickup on every working day; due dates lie on cutoffs
    working_days: tuple[int, ...] = (0, 1, 2, 3, 4)

    @model_validator(mode="after")
    def check_times(self):
        if not self.shift_start < self.break_earliest <= self.break_latest:
            raise ValueError("calendar: need shift_start < break_earliest <= break_latest")
        if self.break_latest + self.break_length > self.shift_end:
            raise ValueError("calendar: a break starting at break_latest must end within the shift")
        if self.shift_end + self.max_overtime > 1440:
            raise ValueError("calendar: shift_end + max_overtime beyond midnight")
        if self.cutoff >= 1440 or self.origin >= 7 * 1440:
            raise ValueError("calendar: cutoff must be a minute of the day, origin a minute of the week")
        if not self.working_days or _duplicates(self.working_days) or not set(self.working_days) <= set(range(7)):
            raise ValueError(f"calendar: working_days must be distinct days 0..6, got {self.working_days}")
        return self


class Instance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["0.7"]
    name: str
    time_unit: Literal["s", "min", "h"] = "min"
    machines: tuple[str, ...]
    orders: tuple[Order, ...]
    carrier_steps: dict[str, CarrierStep] = {}
    carriers: tuple[Carrier, ...] = ()
    runs: tuple[Run, ...] = ()
    calendar: Calendar | None = None  # without: no shifts, tardiness in minutes
    workers: tuple[str, ...] = ()  # individual workers (math/04_workers.md)

    @model_validator(mode="after")
    def check_references(self):
        if dups := _duplicates(self.machines):
            raise ValueError(f"duplicate machine IDs: {dups}")
        if dups := _duplicates(o.id for o in self.orders):
            raise ValueError(f"duplicate order IDs: {dups}")
        machines = set(self.machines)
        if dups := _duplicates(self.workers):
            raise ValueError(f"duplicate worker IDs: {dups}")
        if clash := sorted(machines & set(self.workers)):
            raise ValueError(f"IDs used for workers and machines: {clash}")
        for step, cs in self.carrier_steps.items():
            if unknown := sorted(set(cs.options) - machines):
                raise ValueError(f"carrier step {step}: unknown machines {unknown}")
            self._check_share(f"carrier step {step}", cs.worker, min(cs.options.values()))
            if cs.setup_attended and not cs.setup:
                raise ValueError(f"carrier step {step}: setup_attended without setup")
            if cs.removal_attended and not cs.removal:
                raise ValueError(f"carrier step {step}: removal_attended without removal")
            if (cs.setup_attended or cs.removal_attended) and not self.workers:
                raise ValueError(f"carrier step {step}: attended setup or removal, but the instance has no workers")
            if cs.batch_capacity is not None and (cs.setup or cs.removal or cs.estimator):
                raise ValueError(f"carrier step {step}: a batch step has no setup, removal or estimator")
            if cs.batch_capacity is not None and (cs.runs != "none" or any(r.step == step for r in self.runs)):
                raise ValueError(f"carrier step {step}: batched by the planner, so no given runs")
            if cs.runs == "none" and (cs.setup or cs.removal or cs.estimator):
                raise ValueError(f"carrier step {step}: setup, removal and estimator need runs ('given' or "
                                 "'per_carrier')")
            if cs.runs != "given" and any(r.step == step for r in self.runs):
                raise ValueError(f"carrier step {step}: runs are given, but the step declares runs={cs.runs!r}")
        if self.calendar is not None and self.time_unit != "min":
            raise ValueError("a calendar needs time_unit 'min' (calendar times are minutes)")
        for order in self.orders:
            if order.arrival > order.release:
                raise ValueError(f"order {order.id}: arrival {order.arrival} after release {order.release}")
            if order.accepted > order.arrival:
                raise ValueError(f"order {order.id}: accepted {order.accepted} after arrival {order.arrival}")
            if order.due_date is not None and order.due_date < order.release:
                raise ValueError(f"order {order.id}: due date {order.due_date} before release {order.release}")
            due = order.due_date
            if self.calendar and due is not None and next_cutoff(self.calendar, due) != due:
                raise ValueError(f"order {order.id}: due date {order.due_date} is not a shipping cutoff")
            if dups := _duplicates(p.id for p in order.parts):
                raise ValueError(f"order {order.id}: duplicate part IDs: {dups}")
            for part in order.parts:
                if unknown := sorted(set(part.times) - set(self.carrier_steps)):
                    raise ValueError(f"order {order.id}, part {part.id}: times for unknown carrier steps {unknown}")
            local = [op.id for op in order.operations]
            if dups := _duplicates(local):
                raise ValueError(f"order {order.id}: duplicate operation IDs: {dups}")
            scopes = {ORDER, CARRIER} | {p.type for p in order.parts}
            for op in order.operations:
                where = f"order {order.id}, op {op.id}"
                if op.scope not in scopes:
                    raise ValueError(f"{where}: unknown scope {op.scope!r}, allowed: {sorted(scopes)}")
                if op.scope == CARRIER:
                    if op.options is not None:
                        raise ValueError(f"{where}: carrier operation with options (durations come from carrier_steps)")
                    if op.duration is not None:
                        raise ValueError(f"{where}: carrier operation with duration (durations come from "
                                         "carrier_steps; machine-less carrier steps are not supported)")
                    if op.worker is not None:
                        raise ValueError(f"{where}: carrier operation with a worker share (set it on the carrier "
                                         "step)")
                    if op.step not in self.carrier_steps:
                        raise ValueError(f"{where}: no carrier step {op.step!r}")
                    if op.carries is not None and op.carries not in {p.type for p in order.parts}:
                        raise ValueError(f"{where}: carries unknown part type {op.carries!r}")
                else:
                    if op.carries is not None:
                        raise ValueError(f"{where}: carries only for carrier operations")
                    if op.options is not None and op.duration is not None:
                        raise ValueError(f"{where}: options and duration are exclusive")
                    if op.options is None and op.duration is None:
                        raise ValueError(f"{where}: options or duration missing")
                    if op.duration is not None and op.worker is None:
                        raise ValueError(f"{where}: an operation without machine needs a worker share")
                    if op.role is not None:
                        raise ValueError(f"{where}: role {op.role!r} only for carrier operations")
                    if unknown := sorted(set(op.options or ()) - machines):
                        raise ValueError(f"{where}: unknown machines {unknown}")
                    self._check_share(where, op.worker, op.duration or min(op.options.values()))
                if dups := _duplicates(op.predecessors):
                    raise ValueError(f"{where}: duplicate predecessors {dups}")
                if unknown := sorted(set(op.predecessors) - set(local)):
                    raise ValueError(f"{where}: unknown predecessors {unknown}"
                                     " (must be operation IDs of the same order)")
            # after the reference check: prepare() would silently add unknown nodes
            graph = {op.id: op.predecessors for op in order.operations}
            try:
                TopologicalSorter(graph).prepare()
            except CycleError as e:
                raise ValueError(f"order {order.id}: cycle in predecessors: {' -> '.join(e.args[1])}") from e
            carrier_chains(order)  # raises if the carrier operations of a kind are not one chain from form to separate
        self._check_carriers()
        try:
            TopologicalSorter({k: n.predecessors for k, n in operation_graph(self).items()}).prepare()
        except CycleError as e:
            raise ValueError(f"cycle across orders and carriers: {' -> '.join(map(str, e.args[1]))}") from e
        return self

    def _check_share(self, where: str, share: WorkerShare | None, shortest: int):
        # shortcut: checked against the shortest machine option; a run main operation whose estimated or reported
        # duration is shorter is caught by the checker (C11), upgrade if that happens in real data
        if share is None:
            return
        if not self.workers:
            raise ValueError(f"{where}: worker share, but the instance has no workers")
        if unknown := sorted(set(share.qualified or ()) - set(self.workers)):
            raise ValueError(f"{where}: unknown workers {unknown}")
        if share.prefix + share.suffix > shortest:
            raise ValueError(f"{where}: prefix + suffix {share.prefix + share.suffix} longer than the operation "
                             f"({shortest})")

    def _check_carriers(self):
        owners = [*(o.id for o in self.orders), *(c.id for c in self.carriers), *(r.id for r in self.runs)]
        if dups := _duplicates(owners):
            raise ValueError(f"duplicate IDs across orders, carriers and runs: {dups}")
        parts = {(o.id, p.id) for o in self.orders for p in o.parts}
        on_carrier: dict[tuple[str, str], str] = {}
        for c in self.carriers:
            for part in c.parts:
                if part not in parts:
                    raise ValueError(f"carrier {c.id}: unknown part {part}")
                if part in on_carrier:
                    raise ValueError(f"part {part} on carriers {on_carrier[part]} and {c.id}")
                on_carrier[part] = c.id
        # a carrier and a run belong to one nesting batch: the planner never sees half of one (math/07)
        arrival = {o.id: o.arrival for o in self.orders}
        carrier_arrival = {}
        for c in self.carriers:
            if len(set((at := {k: arrival[k] for k, _ in c.parts}).values())) > 1:
                raise ValueError(f"carrier {c.id}: orders with different arrivals {at}")
            carrier_arrival[c.id] = arrival[c.parts[0][0]]
        for r in self.runs:
            at = {cid: carrier_arrival[cid] for cid in r.carriers if cid in carrier_arrival}
            if len(set(at.values())) > 1:
                raise ValueError(f"run {r.id}: carriers with different arrivals {at}")
        kind = carrier_kinds(self)
        carried: dict[str, set[str]] = defaultdict(set)  # order -> part types it has on carriers
        for c in self.carriers:
            for k, _ in c.parts:
                carried[k].add(kind[c.id])
        chains = {o.id: carrier_chains(o) for o in self.orders}
        for o in self.orders:
            if None in chains[o.id] and len(carried[o.id]) > 1:
                raise ValueError(f"order {o.id}: parts of types {sorted(carried[o.id])} on carriers, so every carrier "
                                 "operation must name the part type it carries")
            for t in chains[o.id]:
                if not carried[o.id] or t is not None and t not in carried[o.id]:
                    raise ValueError(f"order {o.id} has carrier operations{'' if t is None else f' for {t}'} but no "
                                     "part on a carrier")
            for t in sorted(carried[o.id]):
                if chain_for(chains[o.id], t) is None:
                    raise ValueError(f"order {o.id} has parts on carriers but no carrier operations for {t}")
        steps = {c.id: {k: tuple((op.id, op.step) for op in chain_for(chains[k], kind[c.id])) for k, _ in c.parts}
                 for c in self.carriers}
        for c in self.carriers:
            if len(set(steps[c.id].values())) > 1:
                raise ValueError(f"carrier {c.id}: member orders have different carrier routes")
        chain_of = {c.id: steps[c.id][c.parts[0][0]] for c in self.carriers}  # (op id, step) along its route
        in_run: dict[tuple[str, str], str] = {}
        for r in self.runs:
            if r.step not in self.carrier_steps:
                raise ValueError(f"run {r.id}: no carrier step {r.step!r}")
            for cid in r.carriers:
                if cid not in chain_of:
                    raise ValueError(f"run {r.id}: unknown carrier {cid}")
                if r.step not in {step for _, step in chain_of[cid]}:
                    raise ValueError(f"run {r.id}: carrier {cid} does not pass step {r.step}")
                if (cid, r.step) in in_run:
                    raise ValueError(f"carrier {cid} in runs {in_run[cid, r.step]} and {r.id} of step {r.step}")
                in_run[cid, r.step] = r.id
            if r.duration is None and self.carrier_steps[r.step].estimator is not None:
                times = {(o.id, p.id): p.times for o in self.orders for p in o.parts}
                carriers = {c.id: c for c in self.carriers}
                if missing := [part for cid in r.carriers for part in carriers[cid].parts
                               if r.step not in times[part]]:
                    raise ValueError(f"run {r.id}: no {r.step} time for parts {missing} (needed by the estimator)")
        times = {(o.id, p.id): p.times for o in self.orders for p in o.parts}
        for step, cs in self.carrier_steps.items():
            for c in self.carriers:
                if step not in {s for _, s in chain_of[c.id]}:
                    continue
                if cs.runs == "given" and (c.id, step) not in in_run:
                    raise ValueError(f"carrier {c.id} passes step {step} but is in no run of it")
                if cs.runs == "per_carrier" and cs.estimator is not None and (
                        missing := [part for part in c.parts if step not in times[part]]):
                    raise ValueError(f"carrier {c.id}: no {step} time for parts {missing} (needed by the estimator)")


def visible_instance(inst: Instance, t: int) -> Instance:
    """The orders the planning tool knows at t (arrival <= t), with their carriers and runs (math/07_order-arrivals.md).
    Valid on its own: carriers and runs never span arrivals (Instance validation)."""
    known = {o.id for o in inst.orders if o.arrival <= t}
    carriers = tuple(c for c in inst.carriers if c.parts[0][0] in known)
    ids = {c.id for c in carriers}
    return inst.model_copy(update={"orders": tuple(o for o in inst.orders if o.id in known), "carriers": carriers,
                                   "runs": tuple(r for r in inst.runs if r.carriers[0] in ids)})


def carrier_kinds(inst: Instance) -> dict[str, str]:
    """Kind of every carrier: the type of its parts (all parts on a carrier share one type)."""
    ptype = {(o.id, p.id): p.type for o in inst.orders for p in o.parts}
    kind = {}
    for c in inst.carriers:
        if len(types := {ptype[part] for part in c.parts}) > 1:
            raise ValueError(f"carrier {c.id}: parts of different types {sorted(types)}")
        kind[c.id] = types.pop()
    return kind


def carrier_chains(order: Order) -> dict[str | None, list[Operation]]:
    """The order's carrier operations per carrier kind (Operation.carries) in route order."""
    kinds = list(dict.fromkeys(op.carries for op in order.operations if op.scope == CARRIER))
    if None in kinds and len(kinds) > 1:
        raise ValueError(f"order {order.id}: with several carrier kinds every carrier operation names the part type "
                         "it carries")
    return {t: _chain(order, t) for t in kinds}


def chain_for(chains: dict[str | None, list[Operation]], kind: str) -> list[Operation] | None:
    """The chain executed by a carrier of `kind`; an unnamed chain is the order's only one."""
    return chains.get(kind, chains.get(None))


def _chain(order: Order, kind: str | None) -> list[Operation]:
    """Carrier operations of one kind; they must form one chain from 'form' to 'separate'."""
    ops = {op.id: op for op in order.operations if op.scope == CARRIER and op.carries == kind}
    error = ValueError(f"order {order.id}: carrier operations{'' if kind is None else f' carrying {kind}'} must form "
                       "one chain from a forming to a separating operation")
    prev = {j: [q for q in op.predecessors if q in ops] for j, op in ops.items()}
    heads = [j for j, ps in prev.items() if not ps]
    nxt = {q: j for j, ps in prev.items() for q in ps}
    if len(heads) != 1 or any(len(ps) > 1 for ps in prev.values()) or len(nxt) != len(ops) - 1:
        raise error
    chain = [ops[heads[0]]]
    while chain[-1].id in nxt:
        chain.append(ops[nxt[chain[-1].id]])
    roles = [op.role for op in chain]
    if len(chain) != len(ops) or roles[0] != "form" or roles[-1] != "separate" or len(chain) < 2 or any(roles[1:-1]):
        raise error
    return chain


def estimate_run_duration(part_times: Sequence[int], fixed: int, share: float) -> int:
    """Duration of a run from the times of its parts processed alone (math/03_carriers.md, step 4).

    Neither a p-batch (max) nor an s-batch (sum): fixed + share * sum, rounded half up and clamped to
    [max, sum]. The form and its parameters are assumptions until validated with Fidentis data.
    """
    return min(sum(part_times), max(max(part_times), fixed + math.floor(share * sum(part_times) + 0.5)))


def run_duration(inst: Instance, run: Run) -> int | None:
    """Main operation of a run: nesting's duration, else the estimate, else None (constant per machine)."""
    if run.duration is not None:
        return run.duration
    return _estimate(inst, run.step, [part for c in inst.carriers if c.id in run.carriers for part in c.parts])


def _estimate(inst: Instance, step: str, parts: Sequence[tuple[str, str]]) -> int | None:
    """Estimated main operation of a run of `step` holding `parts`; None without an estimator."""
    if (est := inst.carrier_steps[step].estimator) is None:
        return None
    times = {(o.id, p.id): p.times for o in inst.orders for p in o.parts}
    return estimate_run_duration([times[part][step] for part in parts], est.fixed, est.share)


class Node(NamedTuple):
    options: dict[str, int]
    predecessors: list[tuple[str, str]]
    orders: list[str]  # orders the operation serves
    # run operations: one machine, blocked from the first start to the last end
    group: tuple[tuple[str, str], ...] | None
    shares: tuple[WorkerShare, ...] = ()  # worker shares (math/04_workers.md)
    duration: int | None = None  # operations without machine (options empty)


def _shares(share: WorkerShare | None) -> tuple[WorkerShare, ...]:
    return () if share is None else (share,)


def operation_graph(inst: Instance) -> dict[tuple[str, str], Node]:
    """All operations keyed by (owner, op_id); owners are orders, carriers and runs (math/03_carriers.md).

    One rule derives every synchronization: a carrier operation of an order is executed by the corresponding
    operation of every carrier that holds parts of the order (for a run step: by the carrier's run), and the
    order's edges into and out of it are mapped to those operations.
    """
    members = {c.id: list(dict.fromkeys(k for k, _ in c.parts)) for c in inst.carriers}
    kind = carrier_kinds(inst)
    carriers_of: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))  # order -> kind -> ids
    for cid, orders in members.items():
        for k in orders:
            carriers_of[k][kind[cid]].append(cid)
    chains = {o.id: carrier_chains(o) for o in inst.orders}
    run_of = {(cid, r.step): r for r in inst.runs for cid in r.carriers}
    route = {o.id: {op.id: op for op in o.operations} for o in inst.orders}

    def keys_of(owner: str, step_id: str, main: str, prefix: str = "") -> list[tuple[str, str]]:
        """Setup, main operation, removal of a run (those with duration > 0); a carrier owns runs of several steps,
        so its setup and removal carry the operation id as prefix."""
        step = inst.carrier_steps[step_id]
        return [(owner, j) for j, t in ((f"{prefix}setup", step.setup), (main, 1), (f"{prefix}removal", step.removal))
                if t]

    def run_keys(r: Run) -> list[tuple[str, str]]:
        return keys_of(r.id, r.step, r.step)

    def ends(cid: str, op: Operation) -> tuple[tuple[str, str], tuple[str, str]]:
        """First and last operation executing carrier operation op for carrier cid."""
        if r := run_of.get((cid, op.step)):
            keys = run_keys(r)
        elif inst.carrier_steps[op.step].runs == "per_carrier":
            keys = keys_of(cid, op.step, op.id, f"{op.id}/")
        else:
            keys = [(cid, op.id)]
        return keys[0], keys[-1]

    def add_run(keys: list[tuple[str, str]], step: CarrierStep, main: int | None, entry: list, orders: list,
                main_key: tuple[str, str]) -> None:
        for i, key in enumerate(keys):
            if key != main_key:
                options = dict.fromkeys(step.options, step.setup if i == 0 else step.removal)
                attended = step.setup_attended if i == 0 else step.removal_attended
                shares = (WorkerShare(whole=True),) if attended else ()
            else:  # same estimate on every eligible machine (assumption: identical printers)
                options = dict(step.options) if main is None else dict.fromkeys(step.options, main)
                shares = _shares(step.worker)
            ps = list(dict.fromkeys(entry)) if i == 0 else [keys[i - 1]]
            nodes[key] = Node(options, ps, list(dict.fromkeys(orders)), tuple(keys), shares)

    def preds(k: str, op: Operation, cid: str | None = None) -> list[tuple[str, str]]:
        out = []
        for q in op.predecessors:
            qop = route[k][q]
            if qop.scope == CARRIER:  # on one carrier stay on it; otherwise wait for all carriers of that kind
                t = qop.carries or next(iter(carriers_of[k]))  # unnamed: the order's only carrier kind
                out += [ends(c, qop)[1] for c in ([cid] if cid and kind[cid] == t else carriers_of[k][t])]
            else:
                out.append((k, q))
        return out

    nodes: dict[tuple[str, str], Node] = {}
    for o in inst.orders:
        for op in o.operations:
            if op.scope != CARRIER:
                nodes[o.id, op.id] = Node(dict(op.options or {}), preds(o.id, op), [o.id], None,  # {}: no machine
                                          _shares(op.worker), op.duration)
    runs: dict[str, tuple[list, list]] = {r.id: ([], []) for r in inst.runs}  # entry predecessors, orders
    for c in inst.carriers:
        # same IDs and steps for all orders on a carrier
        chain = {k: chain_for(chains[k], kind[c.id]) for k in members[c.id]}
        for i, op in enumerate(chain[members[c.id][0]]):
            ps = list(dict.fromkeys(p for k in members[c.id] for p in preds(k, chain[k][i], c.id)))
            step = inst.carrier_steps[op.step]
            if (r := run_of.get((c.id, op.step))) is not None:
                runs[r.id][0].extend(ps)
                runs[r.id][1].extend(members[c.id])
            elif step.runs == "per_carrier":  # the carrier is the run's load: no nesting needed
                add_run(keys_of(c.id, op.step, op.id, f"{op.id}/"), step, _estimate(inst, op.step, c.parts), ps,
                        members[c.id], (c.id, op.id))
            else:
                nodes[c.id, op.id] = Node(dict(step.options), ps, members[c.id], None, _shares(step.worker))
    for r in inst.runs:
        entry, orders = runs[r.id]
        add_run(run_keys(r), inst.carrier_steps[r.step], run_duration(inst, r), entry, orders, (r.id, r.step))
    return nodes
