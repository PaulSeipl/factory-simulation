"""Instances with order arrivals (math/07_order-arrivals.md §4–5, math/21_instance-generator.md §4b).

Orders are accepted on working days (Poisson count per weekday, uniform time within the shift), wait for the next
nesting batch (given weekdays, fixed minute) and arrive with it; every nesting batch is nested on its own (a package,
V21). One call of the carrier generator draws all orders, so every package shares the same carrier steps. Due dates:
the n-th shipping cutoff after the acceptance, or the lead-time bound (math/06). A backlog of orders is known at
t = 0; its due dates are spread as if it had been accepted over the n working days before.
"""

import math
import random
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from simulation.calendar import DAY, cutoffs, day_index, day_start, is_working_day, next_cutoff
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance, nest
from simulation.due_dates import lead_time_bound
from simulation.model.instance import Instance

WEEKDAYS = range(7)


class ArrivalParams(BaseModel):
    """Generation half of an experiment configuration (the experiment itself follows in step 5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    name: str | None = None
    base: CarrierGeneratorParams  # route, machines, workers, calendar; n_orders is overwritten
    rates: dict[int, NonNegativeFloat]  # weekday (0 = Monday) -> mean number of orders accepted that day
    window_days: PositiveInt = 14  # acceptances in [0, window_days days); arrivals may come later (next batch)
    nesting_days: tuple[int, ...] = (0, 1, 2, 3, 4)  # weekdays with a nesting batch
    nesting_minute: NonNegativeInt = Field(default=720, lt=DAY)  # minute of the day of the nesting batch
    due_working_days: PositiveInt | None = 4  # due date: the n-th shipping cutoff after the acceptance
    due_tightness: tuple[PositiveFloat, ...] = ()  # or: lead-time bound times a factor (math/06)
    backlog: NonNegativeInt = 0  # orders known at t = 0
    # backlog due dates: k-th cutoff after 0, k uniform from here to due_working_days; not the first cutoff (4 h after
    # t = 0), which a backlog order starting from scratch cannot meet (user 2026-11-12: from the third)
    backlog_earliest_cutoff: PositiveInt = 3

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        cal = self.base.calendar
        if cal is None:
            raise ValueError("arrivals need a calendar in base (working days, shifts, cutoffs)")
        if self.base.release_range != (0, 0) or self.base.due_date_tightness:
            raise ValueError("release and due dates come from the arrivals: base needs release_range (0, 0) and no "
                             "due_date_tightness")
        if unknown := sorted(set(self.rates) - set(WEEKDAYS)):
            raise ValueError(f"rates for unknown weekdays {unknown} (0 = Monday ... 6 = Sunday)")
        if not self.nesting_days or not set(self.nesting_days) <= set(cal.working_days):
            raise ValueError(f"nesting_days {list(self.nesting_days)} must be non-empty working days "
                             f"{list(cal.working_days)}")
        if (self.due_working_days is None) == (not self.due_tightness):
            raise ValueError("exactly one due-date rule: due_working_days or due_tightness")
        if self.due_working_days is not None and (late := _worst_wait(self)) is not None:
            raise ValueError(f"due_working_days {self.due_working_days} too short for the nesting cycle: an order "
                             f"accepted at {late[0]} arrives at {late[1]} with no shipping day left before its due "
                             "date")
        if self.due_working_days is not None and self.backlog_earliest_cutoff > self.due_working_days:
            raise ValueError(f"backlog_earliest_cutoff {self.backlog_earliest_cutoff} after due_working_days "
                             f"{self.due_working_days}")
        return self

    def default_name(self) -> str:
        return f"gen-arrivals-s{self.seed}"


def nth_cutoff(cal, t: int, n: int) -> int:
    """The n-th shipping cutoff strictly after t."""
    return cutoffs(cal, t + (n // len(cal.working_days) + 2) * 7 * DAY)[sum(c <= t for c in cutoffs(cal, t)) + n - 1]


def nesting_times(params: ArrivalParams, until: int) -> list[int]:
    """Times of the nesting batches in (0, until]."""
    cal = params.base.calendar
    return [t for d in range(day_index(cal, 0), day_index(cal, until) + 1)
            if d % 7 in params.nesting_days and 0 < (t := day_start(cal, d) + params.nesting_minute) <= until]


def _worst_wait(params: ArrivalParams) -> tuple[int, int] | None:
    """An acceptance right after a nesting batch whose due date leaves no shipping day after the next batch, if any
    (checked over three weeks: the cycle repeats weekly)."""
    cal, n = params.base.calendar, params.due_working_days
    times = nesting_times(params, 4 * 7 * DAY)
    for a, b in zip(times, times[1:], strict=False):
        if nth_cutoff(cal, a, n) < next_cutoff(cal, b + 1):  # accepted at a + 0, arrives at b
            return a, b
    return None


def sample_arrivals(params: ArrivalParams) -> list[tuple[int, int]]:
    """(accepted, arrival) per order, backlog first, then by acceptance. Own random stream `arrival-{seed}`."""
    rng, cal = random.Random(f"arrival-{params.seed}"), params.base.calendar
    end = params.window_days * DAY
    accepted = []
    for d in range(day_index(cal, 0), day_index(cal, end - 1) + 1):
        if not is_working_day(cal, d):
            continue
        lo, hi = max(0, day_start(cal, d) + cal.shift_start), min(end, day_start(cal, d) + cal.shift_end)
        if lo < hi:
            accepted += sorted(rng.randrange(lo, hi) for _ in range(_poisson(rng, params.rates.get(d % 7, 0.0))))
    batches = nesting_times(params, end + 8 * DAY)
    return [(0, 0)] * params.backlog + [(a, next(b for b in batches if b >= a)) for a in accepted]


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth's method (fine for the small daily means here)."""
    k, p, limit = 0, rng.random(), math.exp(-mean)
    while p > limit:
        k, p = k + 1, p * rng.random()
    return k


def generate_arrival_instance(params: ArrivalParams) -> Instance:
    """The hindsight instance: every order with its acceptance, arrival (= release) and due date, each nesting batch
    nested separately (IDs prefixed P<batch>)."""
    if not (times := sample_arrivals(params)):
        raise ValueError("no order sampled: raise the rates, the window or the backlog")
    base = params.base.model_copy(update={"n_orders": len(times)})
    inst = generate_carrier_instance(base)
    data = inst.model_dump()
    cal, due_rng = params.base.calendar, random.Random(f"due-{params.seed}")
    counted = {o.id: sum(p.type == base.counted_type for p in o.parts) for o in inst.orders}
    for i, (raw, order, (acc, arr)) in enumerate(zip(data["orders"], inst.orders, times, strict=True)):
        raw |= {"accepted": acc, "arrival": arr, "release": arr}
        if params.due_working_days is None:
            due = arr + math.floor(due_rng.choice(params.due_tightness) * lead_time_bound(order, inst.carrier_steps)
                                   + 0.5)
            raw["due_date"] = next_cutoff(cal, due)
        elif i < params.backlog:  # as if accepted n - k working days before t = 0: the k-th cutoff, k uniform
            raw["due_date"] = nth_cutoff(cal, 0, due_rng.randint(params.backlog_earliest_cutoff,
                                                                params.due_working_days))
        else:
            raw["due_date"] = nth_cutoff(cal, acc, params.due_working_days)
    carriers, runs = [], []
    for p, arr in enumerate(sorted({o["arrival"] for o in data["orders"]}), start=1):
        batch = [o | {"size": counted[o["id"]]} for o in data["orders"] if o["arrival"] == arr]
        c, r = nest(batch, base, prefix=f"P{p}")
        carriers += c
        runs += r
    data |= {"name": params.name or params.default_name(), "carriers": carriers, "runs": runs}
    return Instance.model_validate(data)
