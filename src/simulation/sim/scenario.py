"""Disturbance scenarios (math/22_scenarios.md).

A scenario holds one sampled disturbance factor per operation for one seed. It is generated
separately from the instance and is seen only by the DES, never by a planner.
"""

import math
import random

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, PositiveFloat

from simulation.model.compiled import CompiledInstance
from simulation.model.instance import Instance


class OperationFactor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    factor: PositiveFloat  # realized / planned processing time, before rounding


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instance: str  # name of the instance the scenario was sampled for
    seed: int
    sigma: NonNegativeFloat  # standard deviation of ln(factor)
    factors: tuple[OperationFactor, ...]


def sample_scenario(instance: Instance, sigma: float, seed: int) -> Scenario:
    """Log-normal factor per operation with mean 1: ln(factor) ~ N(-sigma^2 / 2, sigma^2)."""
    rng = random.Random(seed)
    factors = tuple(
        OperationFactor(order_id=order.id, op_id=op.id, factor=rng.lognormvariate(-sigma**2 / 2, sigma))
        for order in instance.orders
        for op in order.operations
    )
    return Scenario(instance=instance.name, seed=seed, sigma=sigma, factors=factors)


def realized_duration(planned: int, factor: float) -> int:
    """max(1, round(planned * factor)), rounding halves up (Python's round() would round them to even)."""
    return max(1, math.floor(planned * factor + 0.5))


def factors_by_index(ci: CompiledInstance, scenario: Scenario) -> list[float]:
    """Factor per compiled operation index; the scenario must cover every operation exactly once."""
    if scenario.instance != ci.name:
        raise ValueError(f"scenario for instance {scenario.instance!r}, not {ci.name!r}")
    factor: list[float | None] = [None] * ci.n_ops
    for f in scenario.factors:
        o = ci.op_index.get((f.order_id, f.op_id))
        if o is None or factor[o] is not None:
            raise ValueError(f"scenario factor for {(f.order_id, f.op_id)}: unknown or duplicate operation")
        factor[o] = f.factor
    if missing := [ci.op_keys[o] for o in range(ci.n_ops) if factor[o] is None]:
        raise ValueError(f"scenario has no factor for {missing}")
    return factor
