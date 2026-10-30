"""Metrics of one execution run: efficiency, stability against the start plan, effort (math/23_metrics.md)."""

from collections.abc import Sequence
from statistics import mean
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment

if TYPE_CHECKING:
    from simulation.control.rescheduling import ExecutionResult


def run_metrics(ci: CompiledInstance, plan: Sequence[Assignment], result: ExecutionResult) -> dict[str, int | float]:
    """One flat record per run (a CSV row); `plan` is the start plan the run began with."""
    planned = {(a.order_id, a.op_id): a for a in plan}
    order_end: dict[str, int] = {}
    for a in result.schedule:
        order_end[a.order_id] = max(order_end.get(a.order_id, 0), a.end)
    release = {k: ci.release[ci.op_index[k, j]] for k, j in ci.op_keys}
    replans = [d for d in result.decisions if d["type"] == "REPLAN"]
    return {
        "planned_makespan": max(a.end for a in plan),
        "makespan": max(a.end for a in result.schedule),
        "mean_flow_time": mean(end - release[k] for k, end in order_end.items()),
        "mean_start_deviation": mean(abs(a.start - planned[a.order_id, a.op_id].start) for a in result.schedule),
        "machine_changes": sum(a.machine != planned[a.order_id, a.op_id].machine for a in result.schedule),
        "repairs": sum(d["type"] == "REPAIR" for d in result.decisions),
        "reschedulings": len(replans),
        "accepted_reschedulings": sum(d["accepted"] for d in replans),
        "planner_time": sum(d["planner_time"] for d in replans),
    }
