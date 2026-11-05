"""Due dates per order (math/06_due-dates.md): d_k = r_k + round(theta_k * basis_k), theta_k drawn from `tightness`.

Two bases for the time an order is given:
- lead-time bound (default): Lambda_k, the longest path through the precedence graph of order k, weighted with
  the average processing time of each operation over its eligible machines (the shortest possible lead time
  without waiting). For chains Lambda_k is the total work content used by Li et al. (2026); for orders with
  parallel branches the longest path is our adaptation. Ignores waiting for machines, so it does not scale with
  the load of an instance.
- reference plan: C_k^ref - r_k, the flow time of order k in a given feasible plan (e.g. the best dispatching
  plan). With theta_k >= 1 that plan is on time, so every instance has a plan without tardiness and tardiness
  comes from disturbances or weaker planning (own calibration).
"""

import math
import random
from collections.abc import Mapping, Sequence

from graphlib import TopologicalSorter

from simulation.calendar import next_cutoff
from simulation.model.instance import CarrierStep, Instance, Order, operation_graph
from simulation.model.schedule import Assignment


def lead_time_bound(order: Order, carrier_steps: Mapping[str, CarrierStep] | None = None) -> float:
    """Longest path through the order with average processing times.

    A carrier operation counts with its step: average of the step's machines plus setup and removal (the
    constant per machine, not the run estimate; math/06_due-dates.md).
    """
    ops = {op.id: op for op in order.operations}
    finish: dict[str, float] = {}
    for j in TopologicalSorter({op.id: op.predecessors for op in order.operations}).static_order():
        op = ops[j]
        start = max((finish[q] for q in op.predecessors), default=0.0)
        if op.duration is not None:  # without machine (math/04_workers.md)
            finish[j] = start + op.duration
        elif op.options is None:
            step = carrier_steps[op.step]
            finish[j] = start + sum(step.options.values()) / len(step.options) + step.setup + step.removal
        else:
            finish[j] = start + sum(op.options.values()) / len(op.options)
    return max(finish.values())


def assign_due_dates(
    instance: Instance, tightness: Sequence[float], seed: int, reference: Sequence[Assignment] | None = None
) -> Instance:
    """Copy of the instance with a due date per order; theta_k uniform from `tightness` (own random stream).

    Without `reference` the basis is the lead-time bound, with it the flow time of each order in that plan.
    """
    rng = random.Random(f"due-{seed}")
    if reference is not None:  # entries of carriers and runs count for every order they serve
        served = {key: node.orders for key, node in operation_graph(instance).items()}
        order_end: dict[str, int] = {}
        for a in reference:
            for k in served[a.order_id, a.op_id]:
                order_end[k] = max(order_end.get(k, 0), a.end)
    data = instance.model_dump()
    for order, raw in zip(instance.orders, data["orders"], strict=True):
        if reference is None:
            basis = lead_time_bound(order, instance.carrier_steps)
        else:
            basis = order_end[order.id] - order.release
        due = order.release + math.floor(rng.choice(tightness) * basis + 0.5)
        # with a work calendar the due date is a shipping date: the next cutoff (math/04_workers.md)
        raw["due_date"] = next_cutoff(instance.calendar, due) if instance.calendar else due
    return Instance.model_validate(data)
