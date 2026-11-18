"""Metrics of one execution run: efficiency, stability against the start plan, effort (math/23_metrics.md)."""

from collections import defaultdict
from collections.abc import Sequence
from statistics import mean
from typing import TYPE_CHECKING

from simulation.calendar import day_index, day_start, days_late, minute_of_day
from simulation.check.feasibility import worker_intervals
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.objectives import ACTIVE_MAKESPAN, overtime

if TYPE_CHECKING:
    from simulation.control.rescheduling import ExecutionResult


def run_metrics(ci: CompiledInstance, plan: Sequence[Assignment], result: ExecutionResult) -> dict[str, int | float]:
    """One flat record per run (a CSV row); `plan` is the start plan the run began with. Deviations from it count
    only the operations it holds (orders that arrived later are not in it, math/07_order-arrivals.md)."""
    planned = {(a.order_id, a.op_id): a for a in plan}
    order_end: dict[str, int] = {}  # owners of schedule entries can be carriers or runs; count per served order
    release: dict[str, int] = {}
    for a in result.schedule:
        o = ci.op_index[a.order_id, a.op_id]
        for k in (ci.order_ids[i] for i in ci.op_orders[o]):
            order_end[k] = max(order_end.get(k, 0), a.end)
            release[k] = min(release.get(k, ci.release[o]), ci.release[o])  # the order's own operations
    replans = [d for d in result.decisions if d["type"] == "REPLAN"]
    in_plan = [a for a in result.schedule if (a.order_id, a.op_id) in planned]
    metrics = {
        "planned_makespan": max((a.end for a in plan), default=0),
        "makespan": max(a.end for a in result.schedule),
        "mean_flow_time": mean(end - release[k] for k, end in order_end.items()),
        # an empty start plan (nothing known at 0, math/33) has no deviation
        "mean_start_deviation": mean(abs(a.start - planned[a.order_id, a.op_id].start) for a in in_plan)
        if in_plan else 0.0,
        "machine_changes": sum(a.machine != planned[a.order_id, a.op_id].machine for a in in_plan),
        "repairs": sum(d["type"] == "REPAIR" for d in result.decisions),
        "reschedulings": len(replans),
        "accepted_reschedulings": sum(d["accepted"] for d in replans),
        "planner_time": sum(d["planner_time"] for d in replans),
    }
    if any("planner" in d for d in replans):  # CP-SAT reports which limit stopped it
        metrics["wall_limited_reschedulings"] = sum(d["planner"]["wall_limited"] for d in replans if "planner" in d)
    if any(ci.arrival):  # order arrivals (math/07): lead time from the acceptance, reschedulings at arrivals
        accepted = dict(zip(ci.order_ids, ci.accepted, strict=True))
        metrics |= {"mean_lead_time": mean(end - accepted[k] for k, end in order_end.items()),
                    "arrival_reschedulings": sum("arrival" in d["triggers"] for d in replans)}
    if ci.calendar is not None:  # the activity clock at the end (math/04_workers.md (O6), math/23_metrics.md M1)
        metrics["active_makespan"] = ACTIVE_MAKESPAN.evaluate(ci, result.schedule)
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
    if ci.worker_ids:  # worker metrics (math/04_workers.md, math/23_metrics.md)
        metrics |= _worker_metrics(ci, result)
    return metrics


def plan_metrics(ci: CompiledInstance, plan: Sequence[Assignment]) -> dict[str, int]:
    """Metrics of a plan, not of a realized run (math/23_metrics.md (M10)): for every plan of the plan history.
    Orders without operations in the plan (not arrived yet) do not count."""
    ends: dict[int, int] = {}
    for a in plan:
        for k in ci.op_orders[ci.op_index[a.order_id, a.op_id]]:
            ends[k] = max(ends.get(k, 0), a.end)
    late = [(ci.due_date[k], e) for k, e in ends.items() if ci.due_date[k] is not None]
    out = {"makespan": max((a.end for a in plan), default=0), "total_tardiness": sum(max(e - d, 0) for d, e in late)}
    if cal := ci.calendar:
        out |= {"tardy_days": sum(days_late(cal, d, e) for d, e in late), "overtime": overtime(ci, plan)}
    return out


def _worker_metrics(ci: CompiledInstance, result: ExecutionResult) -> dict[str, int]:
    """Oven overstay and swaps from the factory log; with a calendar overtime, overruns past shift end + max
    overtime, and break postponement and spread, from the realized share intervals and breaks."""
    out = {"overstay": sum(r["minutes"] for r in result.log if r["type"] == "OVERSTAY"),
           "swaps": sum(r["type"] == "SWAP" for r in result.log)}
    if (cal := ci.calendar) is None:
        return out
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in result.schedule}
    last_end: dict[tuple[str, int], int] = {}  # (worker, day) -> end of its last share
    overruns = 0
    for w, intervals in worker_intervals(ci, by_op).items():
        for s, e, _ in intervals:
            d = day_index(cal, s)
            last_end[w, d] = max(last_end.get((w, d), 0), e)
            overruns += e > day_start(cal, d) + cal.shift_end + cal.max_overtime
    per_day: dict[int, list[int]] = defaultdict(list)
    for b in result.breaks:
        per_day[day_index(cal, b.start)].append(b.start)
    return out | {
        "overtime": sum(max(0, e - day_start(cal, d) - cal.shift_end) for (_, d), e in last_end.items()),
        "overruns": overruns,
        "break_postponement": sum(max(0, minute_of_day(cal, b.start) - cal.break_earliest) for b in result.breaks),
        "break_spread": sum(max(starts) - min(starts) for starts in per_day.values()),
    }
