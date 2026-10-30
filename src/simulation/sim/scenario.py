"""Disturbance scenarios (math/22_scenarios.md).

A scenario holds, per operation and for one seed, a processing-time factor and a start offset.
It is generated separately from the instance and is seen only by the DES, never by a planner.
"""

import math
import random

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt, PositiveFloat

from simulation.model.compiled import CompiledInstance
from simulation.model.instance import Instance


class OperationFactor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    factor: PositiveFloat  # realized / planned processing time, before rounding
    start_offset: int = 0  # minutes the start deviates from the plan: < 0 early, > 0 late


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instance: str  # name of the instance the scenario was sampled for
    seed: int
    sigma: NonNegativeFloat  # standard deviation of ln(factor)
    q: float = Field(default=1.0, ge=0, le=1)  # probability that an operation starts exactly as planned
    max_early: NonNegativeInt = 0  # start offset otherwise uniform in [-max_early, max_late]
    max_late: NonNegativeInt = 0
    factors: tuple[OperationFactor, ...]


def sample_scenario(
    instance: Instance, sigma: float, seed: int, q: float = 1.0, max_early: int = 0, max_late: int = 0
) -> Scenario:
    """Log-normal factor per operation with mean 1: ln(factor) ~ N(-sigma^2 / 2, sigma^2).

    Start offset: 0 with probability q, otherwise uniform integer in [-max_early, max_late]. Offsets come
    from a separate random stream, so switching them on does not change the factors of a seed.
    """
    rng, start_rng = random.Random(seed), random.Random(f"start-{seed}")
    factors = tuple(
        OperationFactor(
            order_id=order.id, op_id=op.id, factor=rng.lognormvariate(-sigma**2 / 2, sigma),
            start_offset=0 if start_rng.random() < q else start_rng.randint(-max_early, max_late),
        )
        for order in instance.orders
        for op in order.operations
    )
    return Scenario(instance=instance.name, seed=seed, sigma=sigma, q=q, max_early=max_early, max_late=max_late,
                    factors=factors)


def realized_duration(planned: int, factor: float) -> int:
    """max(1, round(planned * factor)), rounding halves up (Python's round() would round them to even)."""
    return max(1, math.floor(planned * factor + 0.5))


def factors_by_index(ci: CompiledInstance, scenario: Scenario) -> list[OperationFactor]:
    """Disturbances per compiled operation index; the scenario must cover every operation exactly once."""
    if scenario.instance != ci.name:
        raise ValueError(f"scenario for instance {scenario.instance!r}, not {ci.name!r}")
    factor: list[OperationFactor | None] = [None] * ci.n_ops
    for f in scenario.factors:
        o = ci.op_index.get((f.order_id, f.op_id))
        if o is None or factor[o] is not None:
            raise ValueError(f"scenario factor for {(f.order_id, f.op_id)}: unknown or duplicate operation")
        factor[o] = f
    if missing := [ci.op_keys[o] for o in range(ci.n_ops) if factor[o] is None]:
        raise ValueError(f"scenario has no factor for {missing}")
    return factor
