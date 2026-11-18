"""Nesting during the run (math/33_order-release-interface.md, step B3).

The orders of an experiment are known with acceptance and due date from the start (the generator), but an order
joins the factory only when nesting binds it: at each nesting time the pool (accepted, not yet bound) is released by
the rule of `release.release`. With a norm (N5) the budget is the norm minus the minutes the bound orders still need
on the gated machines minus the reserve for the orders forecast for the next nesting; without one every accepted
order is bound (the reference that must equal the static arrivals). The planning tool never sees the pool.
"""

from collections.abc import Sequence

from simulation.arrival_generator import ArrivalParams, _nesting_stream, arrival_orders, assemble
from simulation.calendar import day_index, day_start, is_working_day
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.model.compiled import compile_instance
from simulation.model.instance import Calendar, Instance
from simulation.model.schedule import Assignment
from simulation.release import PoolOrder, release
from simulation.sim.snapshot import Snapshot


class Nesting:
    """The release process of one run: which orders are bound so far, and the next nesting time."""

    def __init__(self, params: ArrivalParams):
        self.params = params
        self.data, self.size = arrival_orders(params.model_copy(update={"quota": None}))
        orders = self.data["orders"]
        self.arrival = {o["id"]: 0 for o in orders[:params.backlog]}  # bound orders -> arrival
        self.waiting = [PoolOrder(o["id"], o["accepted"], o["due_date"], i) for i, o in enumerate(orders)
                        if i >= params.backlog]
        self._times = _nesting_stream(params)
        self.next = next(self._times)  # the next nesting time

    @property
    def done(self) -> bool:
        return not self.waiting

    def instance(self) -> Instance:
        """The orders bound so far, each package nested on its own (math/07, V21)."""
        orders = [o | {"arrival": self.arrival[o["id"]], "release": self.arrival[o["id"]]}
                  for o in self.data["orders"] if o["id"] in self.arrival]
        return assemble(self.params, self.data | {"orders": orders}, self.size)

    def budget(self, t: int, after: int, plan: Sequence[Assignment], snap: Snapshot) -> tuple[float, float] | None:
        """(budget, capacity) in telescopes at nesting time t (N5); None without a norm (bind all)."""
        if (norm := self.params.norm) is None:
            return None
        frozen = {(f.order_id, f.op_id): f for f in snap.frozen}
        wip = 0
        for a in plan:  # minutes still to process on the gated machines: planned, or the rest of a running one
            if a.machine in norm.machines:
                f = frozen.get((a.order_id, a.op_id))
                wip += (a.end - a.start) if f is None else max(0, f.end - t) if f.running else 0
        reserve = norm.forecast.get(day_index(self.params.base.calendar, after) % 7, 0.0) * norm.default_load
        capacity = norm.window_days * norm.capacity_per_day - reserve
        per_telescope = norm.default_load / self.params.quota_size
        return (capacity - wip) / per_telescope, capacity / per_telescope

    def bind(self, t: int, plan: Sequence[Assignment], snap: Snapshot) -> Instance | None:
        """Nesting at t (must be `self.next`): bind orders of the pool; the grown instance, or None if none."""
        if t != self.next:
            raise ValueError(f"nesting at {t}, but the next nesting time is {self.next}")
        after = self.next = next(self._times)
        if not (pool := [o for o in self.waiting if o.accepted <= t]):
            return None
        limits = self.budget(t, after, plan, snap)
        budget, capacity = limits if limits is not None else (None, None)
        bound = set(release(pool, budget, lambda o: self.size[o.id], after, capacity))
        if not bound:
            return None
        self.arrival |= dict.fromkeys(bound, t)
        self.waiting = [o for o in self.waiting if o.id not in bound]
        return self.instance()


def average_daily_capacity(cal: Calendar, longest: int, machines: int = 1, weeks: int = 4) -> float:
    """Capacity of a working day on the gated machines, averaged over `weeks` (user 2026-11-18): a worker starts the
    machine from shift start until the last start at shift end + max overtime, and the last job may then run for
    the longest operation, but not past the next working day's shift start."""
    total, days = 0, 0
    for d in range(weeks * 7):
        if not is_working_day(cal, d):
            continue
        nxt = next(e for e in range(d + 1, d + 8) if is_working_day(cal, e))
        open_end = day_start(cal, d) + cal.shift_end + cal.max_overtime
        total += min(open_end + longest, day_start(cal, nxt) + cal.shift_start) - (day_start(cal, d) + cal.shift_start)
        days += 1
    return machines * total / days


def default_order_load(base: CarrierGeneratorParams, machines: Sequence[str], size: int = 4) -> tuple[int, int]:
    """(minutes on the gated machines, longest operation there) of one order of `size` counted parts nested alone
    (math/33: the load of a default order, with its own carriers and setups)."""
    ci = compile_instance(generate_carrier_instance(base.model_copy(update={
        "n_orders": 1, "count_range": (size, size), "count_lognormal": None, "release_range": (0, 0),
        "due_date_tightness": ()})))
    gated = {ci.machine_index[m] for m in machines}
    times = [min(p for m, p in opts if m in gated) for opts in ci.options if any(m in gated for m, _ in opts)]
    return sum(times), max(times, default=0)

