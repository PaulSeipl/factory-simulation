"""Time-buffer baseline (math/14_genetic-algorithm.md section 4b): plan with processing times inflated by a factor f,
then give every operation its nominal duration back at the same start. The gaps left behind are time buffers that
absorb delays under the DES's right-shift execution; any planner (rule, GA, CP-SAT) can plan on the inflated instance.
"""

import dataclasses
import math
from collections import defaultdict
from collections.abc import Sequence
from statistics import NormalDist

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.planners.repair import planned_durations


def quantile_factor(sigma: float, q: float) -> float:
    """The q-quantile of the mean-one log-normal factor of math/22: exp(-sigma^2 / 2 + z_q sigma)."""
    if not 0 < q < 1:
        raise ValueError(f"quantile {q} outside (0, 1)")
    return math.exp(-sigma**2 / 2 + NormalDist().inv_cdf(q) * sigma)


def inflate(ci: CompiledInstance, f: float) -> CompiledInstance:
    """`ci` with every machine duration and machine-less duration times f, rounded half up; p-batch steps keep theirs
    (a fixed program does not deviate, math/22). Worker share lengths stay, so the buffer lies in the operation."""
    if f < 1:
        raise ValueError(f"buffer factor {f} below 1")

    def up(p: int, o: int) -> int:
        return p if ci.batch_capacity[o] > 1 else math.floor(p * f + 0.5)

    return dataclasses.replace(
        ci, options=tuple(tuple((m, up(p, o)) for m, p in opts) for o, opts in enumerate(ci.options)),
        fixed_duration=tuple(None if p is None else up(p, o) for o, p in enumerate(ci.fixed_duration)))


def shorten(ci: CompiledInstance, plan: Sequence[Assignment], breaks=()) -> list[Assignment]:
    """The plan (made on an inflated `ci`) with nominal durations at the same starts, checked against `ci`."""
    machine: list[int | None] = [None] * ci.n_ops
    members = defaultdict(list)
    for a in plan:
        o = ci.op_index[a.order_id, a.op_id]
        machine[o] = None if a.machine is None else ci.machine_index[a.machine]
        if a.batch is not None:
            members[a.batch].append(o)
    batch = [(o,) for o in range(ci.n_ops)]
    for ops in members.values():
        for o in ops:
            batch[o] = tuple(sorted(ops))
    p = planned_durations(ci, machine, batch)
    out = [a.model_copy(update={"end": a.start + p[ci.op_index[a.order_id, a.op_id]]}) for a in plan]
    # shortening moves a removal (suffix) share earlier, which may meet another share of its worker
    if violations := check_schedule(ci, out, breaks=breaks):
        raise ValueError(f"shortened plan infeasible: {violations[:3]}")
    return out
