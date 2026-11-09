"""Snapshot of the factory at time t: what a planner may see when it replans (math/13_des.md, section 6).

Finished operations are fixed with their realized times (they are in the past). Running operations
are frozen: machine and start are fixed, but only the expected end is given, computed from the
planned processing time, never from the scenario. Operations that have not started are free.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Break

if TYPE_CHECKING:  # the DES uses snapshots itself, so its module is imported for type checking only
    from simulation.sim.des import SimState


class FrozenOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    machine: str | None  # None: operation without machine
    start: NonNegativeInt
    end: NonNegativeInt  # realized if finished, expected if running
    running: bool
    # worker per share; None for a share not started yet (the removal of a running oven may still change)
    workers: tuple[str | None, ...] = ()
    # length per share: realized if the share is done (observed), expected if it runs (a running prefix at least
    # until t + 1), planned if not started; empty: the planned lengths (math/04_workers.md)
    share_lengths: tuple[int, ...] = ()


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instance: str
    t: NonNegativeInt
    frozen: tuple[FrozenOperation, ...]  # finished and running operations; all others are free
    # breaks started at or before t, with their realized starts (math/04_workers.md); planned ones not yet started
    # are not part of the snapshot: the planner decides them anew
    breaks: tuple[Break, ...] = ()


def snapshot(ci: CompiledInstance, plan: Sequence[Assignment], state: SimState,
             breaks: Sequence[Break] = (), share_len: Sequence[Sequence[int]] = ()) -> Snapshot:
    """`breaks`: the planned breaks of the run, in the order of state.break_start. `share_len`: the realized share
    lengths of the DES, read only for shares that are done (the past)."""
    machine = {(a.order_id, a.op_id): a.machine for a in plan}
    workers = {(a.order_id, a.op_id): a.workers for a in plan}
    leader = {q: batch[0] for batch in state.started_batch.values() for q in batch}
    frozen = []
    for o, (order_id, op_id) in enumerate(ci.op_keys):
        start, end = state.start[o], state.end[o]
        if start is None:
            continue
        m = machine[order_id, op_id]
        first = leader.get(o, o)  # a batch's shares are carried by its first operation
        started = [state.end[o] is not None or (first, i) in state.share_done or (first, i) in state.worker_on
                   for i in range(len(ci.shares[o]))]
        if end is None:
            # expected end from the planned duration; an overrunning operation ends at t + 1 at the earliest, one
            # whose removal (suffix) has not started at t + its planned length
            planned = ci.fixed_duration[o] if m is None else dict(ci.options[o])[ci.machine_index[m]]
            rest = next((sh.length for sh, s in zip(ci.shares[o], started, strict=True)
                         if sh.kind == "suffix" and not s), 1)
            end = max(start + planned, state.t + rest)
        lengths = []
        for i, sh in enumerate(ci.shares[o]):
            if share_len and (state.end[o] is not None or (first, i) in state.share_done):
                lengths.append(share_len[first][i])  # done: observed
            elif sh.kind == "whole":
                lengths.append(end - start)
            elif sh.kind == "prefix" and (first, i) in state.worker_on:
                lengths.append(max(sh.length, state.t + 1 - start))  # running: expected, overrun seen until t + 1
            else:
                lengths.append(sh.length)  # suffix running or not started: planned
        frozen.append(FrozenOperation(
            order_id=order_id, op_id=op_id, machine=m, start=start, end=end, running=state.end[o] is None,
            workers=tuple(w if done else None for w, done in zip(workers[order_id, op_id], started, strict=True)),
            share_lengths=tuple(lengths) if ci.shares[o] else (),
        ))
    taken = tuple(Break(worker=b.worker, start=s) for b, s in zip(breaks, state.break_start, strict=True)
                  if s is not None)
    return Snapshot(instance=ci.name, t=state.t, frozen=tuple(frozen), breaks=taken)
