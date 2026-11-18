"""Random instances with carriers (math/21_instance-generator.md §6, math/03_carriers.md).

Every order follows one route template and has one carried part (printed on a carrier) whose size is the number
of its counted parts (dental case: one secondary part with one telescope per primary part). Nesting is external
in the real process; here it is emulated: orders in due-date order (then release, then index), carriers filled
one after another up to their capacity, consecutive carriers grouped into runs of the run step. If the route has
carrier operations carrying the counted type, the counted parts go on blanks (a second carrier kind), filled in
the same order up to the blank capacity (an order may span two blanks). Deterministic per seed.
"""

import math
import random
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_serializer,
    model_validator,
)

from simulation.calendar import next_cutoff
from simulation.due_dates import lead_time_bound
from simulation.io.json_loader import resolve_reference
from simulation.model.instance import CARRIER, ORDER, Calendar, CarrierStep, Instance, Order, RunEstimator, WorkerShare


class RouteOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    step: str
    scope: str = ORDER  # "order", a part type, or "carrier"
    role: Literal["form", "separate"] | None = None
    carries: str | None = None  # carrier operations: part type of the carrier (Operation.carries)
    predecessors: tuple[str, ...] = ()
    # worker share of the step (math/04_workers.md); for a carrier operation it goes to the carrier step
    worker: WorkerShare | None = None
    attended: tuple[Literal["setup", "removal"], ...] = ()  # carrier steps in runs: setup / removal need a worker


class PerCarrierStep(BaseModel):
    """A carrier step in which every carrier is its own run (CarrierStep.runs = "per_carrier"); the main operation
    takes the sum of the part times (estimator 0 + 1 * sum: s-batch), a part's time is part_base plus its size times
    unit_time, plus base once per carrier (a worker's setup inside the main operation: one share, no gap)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    setup: NonNegativeInt = 0
    removal: NonNegativeInt = 0
    unit_time: NonNegativeInt  # per size unit (dental: per telescope on a plate, per primary part on a blank)
    part_base: NonNegativeInt = 0  # per part on the carrier, independent of its size (e.g. sawing per secondary part)
    base: NonNegativeInt = 0  # once per carrier, inside the main operation (e.g. QM 15 + 15 per telescope)

    @model_validator(mode="after")
    def check_part_time(self) -> Self:
        if self.part_base + self.unit_time == 0:
            raise ValueError("per_carrier: part_base + unit_time must be > 0 (a part time is positive)")
        return self

    @model_serializer(mode="wrap")
    def _omit_later_defaults(self, handler):
        # added 2026-11-17: left out at their default, so configuration hashes from before stay valid (as below)
        data = handler(self)
        for name in ("part_base", "base"):
            if getattr(self, name) == 0:
                data.pop(name, None)
        return data


class CarrierGeneratorParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    name: str | None = None
    n_orders: PositiveInt
    release_range: tuple[NonNegativeInt, NonNegativeInt] = (0, 0)
    # the route of every order, or the path of a route file (data/routes/), relative to the file being read
    route: tuple[RouteOperation, ...] = Field(min_length=1)
    machines: dict[str, PositiveInt]  # machine pool (default: the step) -> number of identical machines
    machine_pool: dict[str, str] = {}  # step -> pool it runs on, e.g. two milling steps on the same mills
    # step -> duration range; per part for operations scoped to a part type (s-batch without setup: n * p)
    durations: dict[str, tuple[PositiveInt, PositiveInt]]
    carried_type: str = "secondary"  # one part of this type per order, on a carrier
    counted_type: str = "primary"  # its count is the size of the carried part (dental: telescopes)
    count_range: tuple[PositiveInt, PositiveInt] = (1, 7)  # uniform; (1, 7) has median 4
    # instead of uniform: log-normal with this median and sigma of ln n, rounded and clipped to count_range
    count_lognormal: tuple[PositiveFloat, PositiveFloat] | None = None
    carrier_capacity: PositiveInt = 12  # size units per carrier
    carriers_per_run: PositiveInt = 4
    run_capacity: PositiveInt | None = None  # size units per run (dental: telescopes per print); None: no limit
    run_step: str = "print"  # carrier step executed in runs
    setup: NonNegativeInt = 0  # per run
    removal: NonNegativeInt = 0
    setup_per_carrier: NonNegativeInt = 0  # per carrier of the run on top (CarrierStep.setup_per_carrier)
    removal_per_carrier: NonNegativeInt = 0
    unit_time: PositiveInt | None = None  # run-step time per size unit of a carried part, for the estimator
    unit_base: NonNegativeInt = 0  # run-step time per carried part on top of its size times unit_time
    no_machine: tuple[str, ...] = ()  # steps without a machine (worker only or rest): a duration
    # order or part step -> time once per operation on top of the per-part time (setup per order: base + n * p)
    base_durations: dict[str, NonNegativeInt] = {}
    estimator: RunEstimator | None = None
    # carrier step -> carriers per machine run decided by the planner (p-batch)
    batch_capacity: dict[str, Annotated[int, Field(ge=2)]] = {}
    per_carrier: dict[str, PerCarrierStep] = {}  # carrier step -> every carrier its own run
    blank_capacity: PositiveInt | None = None  # counted parts per blank; needed iff carrier operations carry them
    due_date_tightness: tuple[PositiveFloat, ...] = ()  # theta per order (lead-time bound); () = no due dates
    workers: tuple[str, ...] = ()  # individual workers; shares in the route (math/04_workers.md)
    calendar: Calendar | None = None  # work calendar; due dates then lie on shipping cutoffs

    @field_validator("route", mode="before")
    @classmethod
    def route_reference(cls, value, info):
        return resolve_reference(value, info)

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        for lo, hi, what in ((*self.release_range, "release_range"), (*self.count_range, "count_range"),
                             *((*r, f"durations[{s}]") for s, r in self.durations.items())):
            if lo > hi:
                raise ValueError(f"{what}: min {lo} > max {hi}")
        steps = {op.step for op in self.route}
        for op in self.route:
            if op.attended and op.scope != CARRIER:
                raise ValueError(f"attended {list(op.attended)} on {op.id}: only for carrier operations")
        if unknown := sorted(set(self.machine_pool) - steps):
            raise ValueError(f"machine_pool for steps {unknown} not in the route")
        if unknown := sorted(set(self.base_durations) - steps):
            raise ValueError(f"base_durations for steps {unknown} not in the route")
        if carrier := sorted({op.step for op in self.route if op.scope == CARRIER} & set(self.base_durations)):
            raise ValueError(f"base_durations for carrier steps {carrier}: use per_carrier setup")
        if unknown := sorted(set(self.no_machine) - steps):
            raise ValueError(f"no_machine for steps {unknown} not in the route")
        if blocked := sorted(({self.run_step} | set(self.batch_capacity)) & set(self.no_machine)):
            raise ValueError(f"no_machine for {blocked}: the run step and batch steps need machines")
        if both := sorted(s for s in self.no_machine if s in self.machine_pool or s in self.machines):
            raise ValueError(f"no_machine steps {both} also have machines")
        if missing := sorted(s for s in steps - set(self.no_machine)
                             if self.machine_pool.get(s, s) not in self.machines):
            raise ValueError(f"no machines for steps {missing}")
        lo, hi = self.count_range
        if self.count_lognormal is not None and not lo <= self.count_lognormal[0] <= hi:
            raise ValueError(f"count_lognormal median {self.count_lognormal[0]} outside count_range "
                             f"{list(self.count_range)}")
        if self.run_capacity is not None and self.run_capacity < self.carrier_capacity:
            raise ValueError(f"run_capacity {self.run_capacity} below carrier_capacity {self.carrier_capacity}: a full "
                             "carrier would fit no run")
        if self.unit_base and self.unit_time is None:
            raise ValueError("unit_base needs unit_time (run-step time per size unit)")
        if missing := sorted(steps - set(self.durations)):
            raise ValueError(f"no durations for steps {missing}")
        if self.count_range[1] > self.carrier_capacity:
            raise ValueError(f"a carried part of size {self.count_range[1]} exceeds the carrier capacity "
                             f"{self.carrier_capacity}")
        if self.run_step not in {op.step for op in self.route if op.scope == CARRIER}:
            raise ValueError(f"run step {self.run_step!r} is not a carrier step of the route")
        if self.estimator is not None and self.unit_time is None:
            raise ValueError("the estimator needs unit_time (run-step time per size unit)")
        carrier_steps = {op.step for op in self.route if op.scope == CARRIER} - {self.run_step}
        if unknown := sorted(set(self.batch_capacity) - carrier_steps):
            raise ValueError(f"batch_capacity for {unknown}: only carrier steps other than the run step")
        if unknown := sorted(set(self.per_carrier) - (carrier_steps - set(self.batch_capacity))):
            raise ValueError(f"per_carrier for {unknown}: only carrier steps other than the run step and batch steps")
        kinds = {op.carries for op in self.route if op.scope == CARRIER}
        if unknown := sorted(kinds - {None, self.carried_type, self.counted_type}):
            raise ValueError(f"carrier operations carry {unknown}: only {self.carried_type!r} or {self.counted_type!r}")
        if (self.counted_type in kinds) != (self.blank_capacity is not None):
            raise ValueError(f"blank_capacity is needed exactly when carrier operations carry {self.counted_type!r}")
        if any(op.step == self.run_step and op.carries == self.counted_type for op in self.route):
            raise ValueError(f"run step {self.run_step!r} must not carry {self.counted_type!r} (runs hold plates)")
        return self

    @model_serializer(mode="wrap")
    def _omit_later_defaults(self, handler):
        # parameters added on 2026-11-16 are left out at their default, so the configuration hashes of experiments
        # from before (math/07 §5) stay valid
        data = handler(self)
        for name, default in _LATER_DEFAULTS.items():
            if getattr(self, name) == default:
                data.pop(name, None)
        return data

    def default_name(self) -> str:
        return f"gen-carriers-k{self.n_orders}-s{self.seed}"


_LATER_DEFAULTS = {"count_lognormal": None, "run_capacity": None, "unit_base": 0, "no_machine": (),
                   "base_durations": {}, "setup_per_carrier": 0, "removal_per_carrier": 0}


def generate_carrier_instance(params: CarrierGeneratorParams) -> Instance:
    rng = random.Random(params.seed)
    machines = {s: [f"{s}{i}" for i in range(1, n + 1)] for s, n in params.machines.items()}
    pool = {op.step: machines[params.machine_pool.get(op.step, op.step)] for op in params.route
            if op.step not in params.no_machine}

    def step_kwargs(op: RouteOperation) -> dict:
        return _run_kwargs(op.step) | ({"worker": op.worker} if op.worker else {}) | {
            f"{part}_attended": True for part in op.attended}

    def _run_kwargs(step: str) -> dict:
        if step == params.run_step:
            return {"runs": "given", "setup": params.setup, "removal": params.removal, "estimator": params.estimator,
                    "setup_per_carrier": params.setup_per_carrier, "removal_per_carrier": params.removal_per_carrier}
        if (pc := params.per_carrier.get(step)) is not None:
            return {"runs": "per_carrier", "setup": pc.setup, "removal": pc.removal,
                    "estimator": RunEstimator(fixed=0, share=1, base=pc.base)}
        return {"batch_capacity": params.batch_capacity.get(step)}

    carrier_steps = {  # d: the constant per machine (or without a machine) of the step
        op.step: CarrierStep(**({"duration": d} if op.step in params.no_machine else
                                {"options": dict.fromkeys(pool[op.step], d)}), **step_kwargs(op))
        for op in params.route if op.scope == CARRIER for d in (rng.randint(*params.durations[op.step]),)
    }
    kind = {op.step: op.carries or params.carried_type for op in params.route if op.scope == CARRIER}
    per_part = {t: {s: pc for s, pc in params.per_carrier.items() if kind[s] == t}
                for t in (params.carried_type, params.counted_type)}  # part type -> per-carrier step -> times

    orders: list[dict] = []
    for i in range(1, params.n_orders + 1):
        if params.count_lognormal is None:
            n = rng.randint(*params.count_range)
        else:
            median, sigma = params.count_lognormal
            n = min(max(math.floor(rng.lognormvariate(math.log(median), sigma) + 0.5), params.count_range[0]),
                    params.count_range[1])
        times = {params.run_step: params.unit_base + n * params.unit_time} if params.unit_time else {}
        times |= {s: pc.part_base + n * pc.unit_time for s, pc in per_part[params.carried_type].items()}
        counted = {s: pc.part_base + pc.unit_time for s, pc in per_part[params.counted_type].items()}
        parts = [{"id": "c", "type": params.carried_type, "times": times},
                 *({"id": f"n{j}", "type": params.counted_type, "times": dict(counted)} for j in range(1, n + 1))]
        count = {params.carried_type: 1, params.counted_type: n}
        ops = []
        for op in params.route:
            raw = op.model_dump(exclude_none=True, exclude={"attended"})
            if op.scope == CARRIER:
                raw.pop("worker", None)  # on the carrier step
            else:
                d = params.base_durations.get(op.step, 0) + rng.randint(*params.durations[op.step]) * count.get(
                    op.scope, 1)
                if op.step in params.no_machine:
                    raw["duration"] = d
                else:
                    raw["options"] = dict.fromkeys(pool[op.step], d)
            ops.append(raw)
        orders.append({"id": f"O{i}", "release": rng.randint(*params.release_range), "parts": parts,
                       "operations": ops, "size": n})

    if params.due_date_tightness:  # own random stream, like assign_due_dates
        due_rng = random.Random(f"due-{params.seed}")
        for o in orders:
            bound = lead_time_bound(Order.model_validate({k: v for k, v in o.items() if k != "size"}), carrier_steps)
            o["due_date"] = o["release"] + math.floor(due_rng.choice(params.due_date_tightness) * bound + 0.5)
            if params.calendar:  # a shipping date: the next cutoff (math/04_workers.md), as assign_due_dates
                o["due_date"] = next_cutoff(params.calendar, o["due_date"])

    carriers, runs = nest(orders, params)

    return Instance.model_validate({
        "schema_version": "0.8",
        "name": params.name or params.default_name(),
        "machines": [m for ms in machines.values() for m in ms],
        "orders": [{k: v for k, v in o.items() if k != "size"} for o in orders],
        "carrier_steps": carrier_steps,
        "carriers": carriers,
        "runs": runs,
        "workers": params.workers,
        "calendar": params.calendar,
    })


def nest(orders: list[dict], params: CarrierGeneratorParams, prefix: str = "") -> tuple[list[dict], list[dict]]:
    """Nesting emulation (math/21_instance-generator.md §4a): earliest due date first (then release, then index),
    carriers filled in sequence up to the capacity, consecutive carriers form a run; with blanks the counted parts
    next fit in the same order (an order may span two blanks). `orders`: dicts with id, size, release and maybe
    due_date; `prefix` keeps IDs unique when several nesting batches are nested separately (math/07).
    Returns carriers (plates, then blanks) and runs."""
    nesting = [o for _, o in sorted(enumerate(orders), key=lambda io: (io[1].get("due_date", 0), io[1]["release"],
                                                                         io[0]))]
    carriers: list[dict] = []
    load = params.carrier_capacity
    for o in nesting:
        if load + o["size"] > params.carrier_capacity:
            carriers.append({"id": f"{prefix}C{len(carriers) + 1}", "parts": []})
            load = 0
        carriers[-1]["parts"].append([o["id"], "c"])
        load += o["size"]
    size = {o["id"]: o["size"] for o in nesting}
    groups: list[list[dict]] = []
    run_load = 0
    for c in carriers:  # consecutive carriers, at most carriers_per_run and run_capacity size units per run
        c_load = sum(size[k] for k, _ in c["parts"])
        if (not groups or len(groups[-1]) == params.carriers_per_run
                or (params.run_capacity is not None and run_load + c_load > params.run_capacity)):
            groups.append([])
            run_load = 0
        groups[-1].append(c)
        run_load += c_load
    runs = [{"id": f"{prefix}R{j}", "step": params.run_step, "carriers": [c["id"] for c in g]}
            for j, g in enumerate(groups, start=1)]
    blanks: list[dict] = []
    if params.blank_capacity is not None:
        for o in nesting:
            for j in range(1, o["size"] + 1):
                if not blanks or len(blanks[-1]["parts"]) == params.blank_capacity:
                    blanks.append({"id": f"{prefix}B{len(blanks) + 1}", "parts": []})
                blanks[-1]["parts"].append([o["id"], f"n{j}"])
    return carriers + blanks, runs
