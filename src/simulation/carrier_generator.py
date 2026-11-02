"""Random instances with carriers (math/21_instance-generator.md §6, math/03_loads.md).

Every order follows one route template and has one carried part (printed on a carrier) whose size is the number
of its counted parts (dental case: one secondary part with one telescope per primary part). Nesting is external
in the real process; here it is emulated: orders in due-date order (then release, then index), carriers filled
one after another up to their capacity, consecutive carriers grouped into runs of the run step. Deterministic per
seed.
"""

import math
import random
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from simulation.due_dates import lead_time_bound
from simulation.model.instance import CARRIER, ORDER, CarrierStep, Instance, Order, RunEstimator


class RouteOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    step: str
    scope: str = ORDER  # "order", a part type, or "carrier"
    role: Literal["form", "separate"] | None = None
    predecessors: tuple[str, ...] = ()


class CarrierGeneratorParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    name: str | None = None
    n_orders: PositiveInt
    release_range: tuple[NonNegativeInt, NonNegativeInt] = (0, 0)
    route: tuple[RouteOperation, ...] = Field(min_length=1)  # the route of every order
    machines: dict[str, PositiveInt]  # step -> number of identical machines
    # step -> duration range; per part for operations scoped to a part type (s-batch without setup: n * p)
    durations: dict[str, tuple[PositiveInt, PositiveInt]]
    carried_type: str = "secondary"  # one part of this type per order, on a carrier
    counted_type: str = "primary"  # its count is the size of the carried part (dental: telescopes)
    count_range: tuple[PositiveInt, PositiveInt] = (1, 7)  # uniform; (1, 7) has median 4
    carrier_capacity: PositiveInt = 12  # size units per carrier
    carriers_per_run: PositiveInt = 4
    run_step: str = "print"  # carrier step executed in runs
    setup: NonNegativeInt = 0  # per run
    removal: NonNegativeInt = 0
    unit_time: PositiveInt | None = None  # run-step time per size unit of a carried part, for the estimator
    estimator: RunEstimator | None = None
    due_date_tightness: tuple[PositiveFloat, ...] = ()  # theta per order (lead-time bound); () = no due dates

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        for lo, hi, what in ((*self.release_range, "release_range"), (*self.count_range, "count_range"),
                             *((*r, f"durations[{s}]") for s, r in self.durations.items())):
            if lo > hi:
                raise ValueError(f"{what}: min {lo} > max {hi}")
        steps = {op.step for op in self.route}
        if missing := sorted(steps - set(self.machines)):
            raise ValueError(f"no machines for steps {missing}")
        if missing := sorted(steps - set(self.durations)):
            raise ValueError(f"no durations for steps {missing}")
        if self.count_range[1] > self.carrier_capacity:
            raise ValueError(f"a carried part of size {self.count_range[1]} exceeds the carrier capacity "
                             f"{self.carrier_capacity}")
        if self.run_step not in {op.step for op in self.route if op.scope == CARRIER}:
            raise ValueError(f"run step {self.run_step!r} is not a carrier step of the route")
        if self.estimator is not None and self.unit_time is None:
            raise ValueError("the estimator needs unit_time (run-step time per size unit)")
        return self

    def default_name(self) -> str:
        return f"gen-carriers-k{self.n_orders}-s{self.seed}"


def generate_carrier_instance(params: CarrierGeneratorParams) -> Instance:
    rng = random.Random(params.seed)
    machines = {s: [f"{s}{i}" for i in range(1, n + 1)] for s, n in params.machines.items()}
    carrier_steps = {
        op.step: CarrierStep(
            options=dict.fromkeys(machines[op.step], rng.randint(*params.durations[op.step])),
            **({"setup": params.setup, "removal": params.removal, "estimator": params.estimator}
               if op.step == params.run_step else {}),
        )
        for op in params.route if op.scope == CARRIER
    }

    orders: list[dict] = []
    for i in range(1, params.n_orders + 1):
        n = rng.randint(*params.count_range)
        times = {params.run_step: n * params.unit_time} if params.unit_time else {}
        parts = [{"id": "c", "type": params.carried_type, "times": times},
                 *({"id": f"n{j}", "type": params.counted_type} for j in range(1, n + 1))]
        count = {params.carried_type: 1, params.counted_type: n}
        ops = []
        for op in params.route:
            raw = op.model_dump(exclude_none=True)
            if op.scope != CARRIER:
                d = rng.randint(*params.durations[op.step]) * count.get(op.scope, 1)
                raw["options"] = dict.fromkeys(machines[op.step], d)
            ops.append(raw)
        orders.append({"id": f"O{i}", "release": rng.randint(*params.release_range), "parts": parts,
                       "operations": ops, "size": n})

    if params.due_date_tightness:  # own random stream, like assign_due_dates
        due_rng = random.Random(f"due-{params.seed}")
        for o in orders:
            bound = lead_time_bound(Order.model_validate({k: v for k, v in o.items() if k != "size"}), carrier_steps)
            o["due_date"] = o["release"] + math.floor(due_rng.choice(params.due_date_tightness) * bound + 0.5)

    # nesting emulation: earliest due date first, carriers filled in sequence, consecutive carriers form a run
    carriers: list[dict] = []
    load = params.carrier_capacity
    for _, o in sorted(enumerate(orders), key=lambda io: (io[1].get("due_date", 0), io[1]["release"], io[0])):
        if load + o["size"] > params.carrier_capacity:
            carriers.append({"id": f"C{len(carriers) + 1}", "parts": []})
            load = 0
        carriers[-1]["parts"].append([o["id"], "c"])
        load += o["size"]
    runs = [{"id": f"R{j // params.carriers_per_run + 1}", "step": params.run_step,
             "carriers": [c["id"] for c in carriers[j:j + params.carriers_per_run]]}
            for j in range(0, len(carriers), params.carriers_per_run)]

    return Instance.model_validate({
        "schema_version": "0.4",
        "name": params.name or params.default_name(),
        "machines": [m for ms in machines.values() for m in ms],
        "orders": [{k: v for k, v in o.items() if k != "size"} for o in orders],
        "carrier_steps": carrier_steps,
        "carriers": carriers,
        "runs": runs,
    })
