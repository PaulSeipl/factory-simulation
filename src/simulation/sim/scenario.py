"""Disturbance scenarios (math/22_scenarios.md).

A scenario holds, per operation and for one seed, a processing-time factor and a start offset.
It is generated separately from the instance and is seen only by the DES, never by a planner.
"""

import math
import random

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt, PositiveFloat

from simulation.model.compiled import CompiledInstance
from simulation.model.instance import Instance, operation_graph


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
    instance: Instance, sigma: float, seed: int, q: float = 1.0, max_early: int = 0, max_late: int = 0,
    keyed: bool = False,
) -> Scenario:
    """Log-normal factor per operation with mean 1: ln(factor) ~ N(-sigma^2 / 2, sigma^2).

    Start offset: 0 with probability q, otherwise uniform integer in [-max_early, max_late]. Offsets come
    from a separate random stream, so switching them on does not change the factors of a seed.
    `keyed`: every operation draws from its own streams, keyed by seed and operation, so its disturbance does not
    depend on which other operations exist (math/22 §3; needed when carriers and runs are created during a run,
    math/33). Default: one stream in graph order, as before.
    """
    rng, start_rng = random.Random(seed), random.Random(f"start-{seed}")

    def streams(owner: str, op_id: str) -> tuple[random.Random, random.Random]:
        if not keyed:
            return rng, start_rng
        return random.Random(f"{seed}/{owner}/{op_id}"), random.Random(f"start-{seed}/{owner}/{op_id}")

    def draw(owner: str, op_id: str) -> OperationFactor:
        r, s = streams(owner, op_id)
        return OperationFactor(order_id=owner, op_id=op_id, factor=r.lognormvariate(-sigma**2 / 2, sigma),
                               start_offset=0 if s.random() < q else s.randint(-max_early, max_late))

    # every compiled operation, incl. carrier and run operations (owner in order_id); for instances without carriers
    # the same operations in the same order as the routes, so the draws of a seed are unchanged
    factors = tuple(draw(owner, op_id) for owner, op_id in operation_graph(instance))
    return Scenario(instance=instance.name, seed=seed, sigma=sigma, q=q, max_early=max_early, max_late=max_late,
                    factors=factors)


def sample_planner_scenario(
    ci: CompiledInstance, sigma: float, seed: int, q: float = 1.0, max_early: int = 0, max_late: int = 0,
) -> Scenario:
    """A planner's own scenario for whatever instance it plans (math/14 section 4a): keyed draws per compiled
    operation, the same as `sample_scenario(..., keyed=True)` for the same operation, so an operation keeps its draw
    when orders arrive. Draw it from seeds disjoint from the evaluation seeds (no leakage)."""
    factors = []
    for owner, op_id in ci.op_keys:
        r, s = random.Random(f"{seed}/{owner}/{op_id}"), random.Random(f"start-{seed}/{owner}/{op_id}")
        factors.append(OperationFactor(order_id=owner, op_id=op_id, factor=r.lognormvariate(-sigma**2 / 2, sigma),
                                       start_offset=0 if s.random() < q else s.randint(-max_early, max_late)))
    return Scenario(instance=ci.name, seed=seed, sigma=sigma, q=q, max_early=max_early, max_late=max_late,
                    factors=tuple(factors))


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
