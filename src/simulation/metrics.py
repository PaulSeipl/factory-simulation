"""Metrics of one execution run: efficiency, stability against the start plan, effort (math/23_metrics.md)."""

from collections.abc import Sequence
from statistics import mean
from typing import TYPE_CHECKING

from simulation.calendar import days_late
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment

if TYPE_CHECKING:
    from simulation.control.rescheduling import ExecutionResult


def run_metrics(ci: CompiledInstance, plan: Sequence[Assignment], result: ExecutionResult) -> dict[str, int | float]:
    """One flat record per run (a CSV row); `plan` is the start plan the run began with."""
    planned = {(a.order_id, a.op_id): a for a in plan}
    order_end: dict[str, int] = {}  # owners of schedule entries can be carriers or runs; count per served order
    release: dict[str, int] = {}
    for a in result.schedule:
        o = ci.op_index[a.order_id, a.op_id]
        for k in (ci.order_ids[i] for i in ci.op_orders[o]):
            order_end[k] = max(order_end.get(k, 0), a.end)
            release[k] = min(release.get(k, ci.release[o]), ci.release[o])  # the order's own operations
    replans = [d for d in result.decisions if d["type"] == "REPLAN"]
    metrics = {
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
    # due-date metrics only for instances with due dates, so that rows of one experiment share their columns
    lateness = [order_end[k] - d for k, d in zip(ci.order_ids, ci.due_date, strict=True) if d is not None]
    if lateness:
        metrics |= {
            "total_tardiness": sum(max(lk, 0) for lk in lateness),
            "tardy_orders": sum(lk > 0 for lk in lateness),
            "max_lateness": max(lateness),
        }
        if cal := ci.calendar:  # the objective's unit: missed shipping cutoffs (math/04_workers.md)
            metrics["tardy_days"] = sum(
                days_late(cal, d, order_end[k]) for k, d in zip(ci.order_ids, ci.due_date, strict=True) if d is not None
            )
    return metrics
