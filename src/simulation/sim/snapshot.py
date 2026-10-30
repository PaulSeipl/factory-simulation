"""Snapshot of the factory at time t: what a planner may see when it replans (math/13_des.md, section 6).

Finished operations are fixed with their realized times (they are in the past). Running operations
are frozen: machine and start are fixed, but only the expected end is given, computed from the
planned processing time, never from the scenario. Operations that have not started are free.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment

if TYPE_CHECKING:  # the DES uses snapshots itself, so its module is imported for type checking only
    from simulation.sim.des import SimState


class FrozenOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    machine: str
    start: NonNegativeInt
    end: NonNegativeInt  # realized if finished, expected if running
    running: bool


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instance: str
    t: NonNegativeInt
    frozen: tuple[FrozenOperation, ...]  # finished and running operations; all others are free


def snapshot(ci: CompiledInstance, plan: Sequence[Assignment], state: SimState) -> Snapshot:
    machine = {(a.order_id, a.op_id): a.machine for a in plan}
    frozen = []
    for o, (order_id, op_id) in enumerate(ci.op_keys):
        start, end = state.start[o], state.end[o]
        if start is None:
            continue
        m = machine[order_id, op_id]
        if end is None:
            # expected end from the planned duration; an overrunning operation ends at t + 1 at the earliest
            end = max(start + dict(ci.options[o])[ci.machine_index[m]], state.t + 1)
        frozen.append(FrozenOperation(
            order_id=order_id, op_id=op_id, machine=m, start=start, end=end, running=state.end[o] is None,
        ))
    return Snapshot(instance=ci.name, t=state.t, frozen=tuple(frozen))
