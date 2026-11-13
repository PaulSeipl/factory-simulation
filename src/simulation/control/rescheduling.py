"""The planning tool during execution (math/05_rescheduling-frozen-part.md).

At every time point of the DES, after its events and before anything starts, and again after the starts of that
time point (every start is an event):
1. read the snapshot (what the factory knows now, no scenario data),
2. repair the current plan (left/right shift),
3. if the repaired plan deviates substantially from the anchor (the plan of the last complete
   rescheduling, at first the start plan) in makespan, start times or the planner's objective, or if the
   last complete rescheduling is `period` minutes ago (safety net), ask a planner for a complete
   rescheduling and accept its plan if it stays within the change budget,
4. send the resulting plan to the factory.
An order arrival (the visible instance grew, math/07_order-arrivals.md) skips 2 and 3: repair cannot place a new
order, so a complete rescheduling runs at once and is accepted regardless of the change budget.
The DES itself never decides anything; it only executes the plan it receives.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from operator import attrgetter
from typing import NamedTuple

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Break, Plan
from simulation.objectives import TOTAL_TARDINESS, Objective, overtime
from simulation.planners.repair import repair_plan
from simulation.sim.des import PlanNotExecutable, Simulation
from simulation.sim.scenario import Scenario
from simulation.sim.snapshot import Snapshot

# planner(ci, snapshot, current_plan) -> new complete plan with its breaks (frozen operations and started breaks as
# in the snapshot)
type Planner = Callable[[CompiledInstance, Snapshot, Sequence[Assignment]], Plan]


@dataclass(frozen=True, slots=True)
class ReschedulingPolicy:
    """Repair at every time point; complete rescheduling when a threshold is exceeded or the period has passed
    (math/05, section 3)."""

    planner: Planner | None = None  # complete rescheduling; None: repair only
    max_makespan_change: int | None = None  # trigger if the projected makespan deviates from the anchor by more
    max_shift: int | None = None  # trigger if a start deviates from the anchor by more
    max_mean_shift: float | None = None  # trigger if the mean start deviation from the anchor is larger
    change_budget: int | None = None  # reject a plan that changes more machine assignments
    objective: Objective | None = None  # with max_objective_change: trigger on this objective (e.g. the planner's)
    max_objective_change: int | None = None  # trigger if objective(repaired) deviates from objective(anchor) by more
    period: int | None = None  # safety net: complete rescheduling at the latest this many minutes after the last one
    repair_overtime: bool = False  # the repair may move shares into overtime up to the window (math/05, section 3)
    # trigger if an operation finishes at least this many minutes before its end in the current plan while the
    # repaired plan still has tardiness or overtime (math/05, section 3; user 2026-11-11)
    early_finish: int | None = None

    def __post_init__(self):
        if (self.objective is None) != (self.max_objective_change is None):
            raise ValueError("objective and max_objective_change must be given together")
        if self.period is not None and self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")
        if self.early_finish is not None and self.early_finish <= 0:
            raise ValueError(f"early_finish must be positive, got {self.early_finish}")


class Anchor(NamedTuple):
    plan: Sequence[Assignment]  # plan of the last complete rescheduling (accepted or rejected); at first the start plan
    t: int  # time of that rescheduling; 0 for the start plan
    breaks: Sequence[Break] = ()  # the breaks of that plan (for objectives with a break term)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # factory: START and COMPLETE per operation
    decisions: list[dict] = field(default_factory=list)  # planning tool: REPAIR and REPLAN records
    breaks: tuple[Break, ...] = ()  # realized breaks of the workers (math/04_workers.md)
    # with keep_history: the start plan, then per plan update its time, cause and the changed assignments and breaks
    history: list[dict] = field(default_factory=list)


def execute(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None,
    policy: ReschedulingPolicy | None = None, breaks: Sequence[Break] = (),
    visible: Callable[[int], CompiledInstance] | None = None, keep_history: bool = False,
) -> ExecutionResult:
    """Run the factory on the plan and its breaks; with a policy the planning tool adapts the plan during the run.

    `visible`: t -> the instance the planning tool knows at t (`compile_visible`, math/07_order-arrivals.md); the
    tool plans over it and reschedules completely when it grows. None: every order is known from the start.
    `keep_history`: record every plan the factory receives as a change set (e.g. to animate the plan over time)."""
    if visible is not None and any(t > 0 for t in ci.arrival) and (policy is None or policy.planner is None):
        raise ValueError("arrivals need a planner: repair cannot place a new order (math/07_order-arrivals.md)")
    at = visible or (lambda _t: ci)
    sim = Simulation(ci, plan, scenario, breaks, visible)
    decisions: list[dict] = []
    anchor, wake, known = Anchor(sim.current_plan(), 0, sim.current_breaks()), None, at(0)
    history, sent = [], {}
    if keep_history:
        _record(history, sent, sim, decisions)
    while not sim.done:
        sim.process_events()
        while True:  # every start is an event too: the tool sees it at once (math/13 section 3, user 2026-11-11)
            if policy is not None:
                ci_t = at(sim.state.t)
                anchor = adapt_plan(ci_t, sim, policy, decisions, anchor, arrived=ci_t is not known)
                known = ci_t
                if keep_history:
                    _record(history, sent, sim, decisions)
                # the safety net needs a time point even if the factory has no event then
                if policy.period is not None and sim.has_unstarted and wake != anchor.t + policy.period:
                    wake = anchor.t + policy.period
                    sim.wake_at(wake)
            # a new plan may release more operations at this time point; each operation starts once, so this ends
            if not sim.start_operations() or policy is None:
                break
    sim.check_completed()
    return ExecutionResult(sim.realized(), sim.log, decisions, sim.realized_breaks(), history)


def _record(history: list[dict], sent: dict, sim: Simulation, decisions: list[dict]) -> None:
    """Append the assignments and breaks that changed since the last recorded plan (all of them the first time);
    nothing if the plan is unchanged. The cause is the last decision at this time point (REPAIR or REPLAN)."""
    plan = {(a.order_id, a.op_id): a.model_dump(include={"machine", "start", "end", "workers"})
            for a in sim.current_plan()}
    breaks = sorted((b.worker, b.start) for b in sim.current_breaks())
    changed = {k: v for k, v in plan.items() if sent.get(k) != v}
    if not changed and history and breaks == sent.get("breaks"):
        return
    cause = next((d for d in reversed(decisions) if d["t"] == sim.state.t), None)
    history.append({"t": sim.state.t, "type": cause["type"] if cause else "START",
                    "triggers": cause.get("triggers", []) if cause else [],
                    "changed": [{"order_id": k[0], "op_id": k[1], **v} for k, v in changed.items()],
                    "breaks": breaks})
    sent.update(changed)
    sent["breaks"] = breaks


def adapt_plan(
    ci: CompiledInstance, sim: Simulation, policy: ReschedulingPolicy, decisions: list[dict], anchor: Anchor,
    arrived: bool = False,
) -> Anchor:
    """One step of the planning tool; returns the anchor for the next step. `arrived`: `ci` has grown by an order
    arrival since the last step."""
    snap, current, current_breaks = sim.snapshot(), sim.current_plan(), sim.current_breaks()
    if arrived:  # repair cannot place a new order: complete rescheduling, never rejected (math/07, step 3)
        new_plan, new_breaks = _reschedule(ci, snap, current, policy, decisions, ["arrival"], always=True)
        sim.update_plan(new_plan, new_breaks)
        return Anchor(new_plan, snap.t, new_breaks)
    # with workers and a calendar the repair also moves overdue breaks and adds owed ones; otherwise it keeps them
    repaired, repaired_breaks = repair_plan(ci, snap, current, current_breaks, overtime=policy.repair_overtime)
    if ci.calendar is None or not ci.worker_ids:
        repaired_breaks = current_breaks
    periodic = (policy.period is not None and len(snap.frozen) < ci.n_ops  # something left to plan
                and snap.t >= anchor.t + policy.period)
    changed = not _same(repaired, current) or not _same_breaks(repaired_breaks, current_breaks)
    # an early finish the repair may not use (an operation with a gap keeps its start): a chance to gain
    early_finish = (policy.early_finish is not None and len(snap.frozen) < ci.n_ops and anchor.t < snap.t
                    and _earliness(snap, current) >= policy.early_finish and _room_to_gain(ci, repaired))
    if not changed and not periodic and not early_finish:
        return anchor
    triggers = []
    if changed:
        makespan_change, max_shift, mean_shift = _change(current, repaired, snap)
        # measured against the anchor, so that many small repairs add up instead of each staying below the threshold
        makespan_deviation, shift_deviation, mean_shift_deviation = _change(anchor.plan, repaired, snap)
        record = {"t": snap.t, "type": "REPAIR", "makespan_change": makespan_change, "max_shift": max_shift,
                  "mean_shift": mean_shift, "makespan_deviation": makespan_deviation,
                  "shift_deviation": shift_deviation, "mean_shift_deviation": mean_shift_deviation}
        if policy.objective is not None:
            record["objective_deviation"] = (policy.objective.evaluate(ci, repaired, repaired_breaks)
                                             - policy.objective.evaluate(ci, anchor.plan, anchor.breaks))
        decisions.append(record)
        triggers = _triggers(policy, record)
    if periodic:
        triggers.append("period")
    if early_finish:
        triggers.append("early_finish")
    new_plan, new_breaks = repaired, repaired_breaks
    if policy.planner is not None and triggers:
        # accepted or rejected, the result is the plan a complete rescheduling settled on: the new anchor
        if (proposed := _reschedule(ci, snap, repaired, policy, decisions, triggers)) is not None:
            new_plan, new_breaks = proposed
        anchor = Anchor(new_plan, snap.t, new_breaks)
    if not _same(new_plan, current) or not _same_breaks(new_breaks, current_breaks):
        sim.update_plan(new_plan, new_breaks)
    return anchor


def _earliness(snap: Snapshot, current: Sequence[Assignment]) -> int:
    """Delta E: largest end in the current plan minus realized end over the operations that completed at snap.t."""
    planned = {(a.order_id, a.op_id): a.end for a in current}
    return max((planned[f.order_id, f.op_id] - f.end for f in snap.frozen if not f.running and f.end == snap.t),
               default=0)


def _room_to_gain(ci: CompiledInstance, plan: Sequence[Assignment]) -> bool:
    """The plan has tardiness (orders with a due date) or overtime, which a complete rescheduling might lower."""
    return ((any(d is not None for d in ci.due_date) and TOTAL_TARDINESS.evaluate(ci, plan) > 0)
            or overtime(ci, plan) > 0)


def _same(a: Sequence[Assignment], b: Sequence[Assignment]) -> bool:
    """Equal plans up to share lengths: a repaired plan carries the snapshot's lengths of started shares for the
    checker, the plan in the factory does not (math/05_rescheduling-frozen-part.md section 5)."""
    return len(a) == len(b) and all(_compared(x) == _compared(y) for x, y in zip(a, b, strict=True))


# every field but share_lengths, read from the model so that a new field is compared too
_compared = attrgetter(*(f for f in Assignment.model_fields if f != "share_lengths"))


def _same_breaks(a: Sequence[Break], b: Sequence[Break]) -> bool:
    """Equal breaks in any order (the DES lists the taken ones first)."""
    return sorted((x.worker, x.start) for x in a) == sorted((x.worker, x.start) for x in b)


def _change(before: Sequence[Assignment], after: Sequence[Assignment], snap: Snapshot) -> tuple[int, int, float]:
    """Change of the projected makespan, largest and mean start shift of the operations not started."""
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    start_before = {(a.order_id, a.op_id): a.start for a in before}
    shifts = [abs(a.start - start_before[a.order_id, a.op_id]) for a in after if (a.order_id, a.op_id) not in frozen]
    return (max(a.end for a in after) - max(a.end for a in before), max(shifts, default=0),
            sum(shifts) / len(shifts) if shifts else 0.0)


def _triggers(policy: ReschedulingPolicy, record: dict) -> list[str]:
    """Names of the thresholds the repair exceeded."""
    return [name for name, limit, value in (
        ("makespan", policy.max_makespan_change, abs(record["makespan_deviation"])),
        ("shift", policy.max_shift, record["shift_deviation"]),
        ("mean_shift", policy.max_mean_shift, record["mean_shift_deviation"]),
        ("objective", policy.max_objective_change, abs(record.get("objective_deviation", 0))),
    ) if limit is not None and value > limit]


def _reschedule(
    ci: CompiledInstance, snap: Snapshot, repaired: Sequence[Assignment], policy: ReschedulingPolicy,
    decisions: list[dict], triggers: list[str], always: bool = False,
) -> Plan | None:
    """Complete rescheduling; returns the new plan with its breaks if accepted, None if rejected. `always`: accept
    regardless of the change budget (an arrival: the repaired plan lacks the new orders)."""
    t0 = time.perf_counter()
    proposed, breaks = policy.planner(ci, snap, repaired)
    planner_time = time.perf_counter() - t0  # wall clock seconds; varies between runs
    if violations := check_schedule(ci, proposed, snap, breaks):
        raise PlanNotExecutable("planner returned an infeasible plan:\n"
                                + "\n".join(f"[{v.constraint}] {v.message}" for v in violations))
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    machine_before = {(a.order_id, a.op_id): a.machine for a in repaired}
    free = [a for a in proposed if (a.order_id, a.op_id) not in frozen]
    # the budget counts operations planned before; arrived ones are inserted, not changed (math/07)
    changed = sum(a.machine != machine_before[a.order_id, a.op_id] for a in free
                  if (a.order_id, a.op_id) in machine_before)
    accepted = always or policy.change_budget is None or changed <= policy.change_budget
    decisions.append({"t": snap.t, "type": "REPLAN", "triggers": triggers, "accepted": accepted,
                      "changed_assignments": changed,
                      "inserted": sum((a.order_id, a.op_id) not in machine_before for a in free),
                      "makespan_before": max(a.end for a in repaired), "makespan_after": max(a.end for a in proposed),
                      "planner_time": planner_time})
    return Plan(proposed, breaks) if accepted else None
