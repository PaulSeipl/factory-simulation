"""The planning tool during execution (math/05_rescheduling-frozen-part.md).

At every time point of the DES, after its events and before anything starts:
1. read the snapshot (what the factory knows now, no scenario data),
2. repair the current plan (left/right shift),
3. if the repaired plan deviates substantially from the anchor (the plan of the last complete
   rescheduling, at first the start plan) in makespan, start times or the planner's objective, or if the
   last complete rescheduling is `period` minutes ago (safety net), ask a planner for a complete
   rescheduling and accept its plan if it stays within the change budget,
4. send the resulting plan to the factory.
The DES itself never decides anything; it only executes the plan it receives.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.objectives import Objective
from simulation.planners.repair import repair
from simulation.sim.des import PlanNotExecutable, Simulation
from simulation.sim.scenario import Scenario
from simulation.sim.snapshot import Snapshot

# planner(ci, snapshot, current_plan) -> new complete plan (frozen operations as in the snapshot)
type Planner = Callable[[CompiledInstance, Snapshot, Sequence[Assignment]], list[Assignment]]


@dataclass(frozen=True, slots=True)
class ReschedulingPolicy:
    """Repair at every time point; complete rescheduling when a threshold is exceeded or the period has passed
    (math/05, section 3)."""

    planner: Planner | None = None  # complete rescheduling; None: repair only
    max_makespan_change: int | None = None  # trigger if the projected makespan deviates from the anchor by more
    max_shift: int | None = None  # trigger if a start deviates from the anchor by more
    change_budget: int | None = None  # reject a plan that changes more machine assignments
    objective: Objective | None = None  # with max_objective_change: trigger on this objective (e.g. the planner's)
    max_objective_change: int | None = None  # trigger if objective(repaired) deviates from objective(anchor) by more
    period: int | None = None  # safety net: complete rescheduling at the latest this many minutes after the last one

    def __post_init__(self):
        if (self.objective is None) != (self.max_objective_change is None):
            raise ValueError("objective and max_objective_change must be given together")
        if self.period is not None and self.period <= 0:
            raise ValueError(f"period must be positive, got {self.period}")


class Anchor(NamedTuple):
    plan: Sequence[Assignment]  # plan of the last complete rescheduling (accepted or rejected); at first the start plan
    t: int  # time of that rescheduling; 0 for the start plan


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    schedule: list[Assignment]  # realized schedule
    log: list[dict]  # factory: START and COMPLETE per operation
    decisions: list[dict] = field(default_factory=list)  # planning tool: REPAIR and REPLAN records


def execute(
    ci: CompiledInstance, plan: Sequence[Assignment], scenario: Scenario | None = None,
    policy: ReschedulingPolicy | None = None,
) -> ExecutionResult:
    """Run the factory on the plan; with a policy the planning tool adapts the plan during the run."""
    sim = Simulation(ci, plan, scenario)
    decisions: list[dict] = []
    anchor, wake = Anchor(sim.current_plan(), 0), None
    while not sim.done:
        sim.process_events()
        if policy is not None:
            anchor = adapt_plan(ci, sim, policy, decisions, anchor)
            # the safety net needs a time point even if the factory has no event then
            if policy.period is not None and sim.has_unstarted and wake != anchor.t + policy.period:
                wake = anchor.t + policy.period
                sim.wake_at(wake)
        sim.start_operations()
    sim.check_completed()
    return ExecutionResult(sim.realized(), sim.log, decisions)


def adapt_plan(
    ci: CompiledInstance, sim: Simulation, policy: ReschedulingPolicy, decisions: list[dict], anchor: Anchor,
) -> Anchor:
    """One step of the planning tool; returns the anchor for the next step."""
    snap, current = sim.snapshot(), sim.current_plan()
    repaired = repair(ci, snap, current)
    periodic = (policy.period is not None and len(snap.frozen) < ci.n_ops  # something left to plan
                and snap.t >= anchor.t + policy.period)
    if repaired == current and not periodic:
        return anchor
    triggers = []
    if repaired != current:
        makespan_change, max_shift = _change(current, repaired, snap)
        # measured against the anchor, so that many small repairs add up instead of each staying below the threshold
        makespan_deviation, shift_deviation = _change(anchor.plan, repaired, snap)
        record = {"t": snap.t, "type": "REPAIR", "makespan_change": makespan_change, "max_shift": max_shift,
                  "makespan_deviation": makespan_deviation, "shift_deviation": shift_deviation}
        if policy.objective is not None:
            record["objective_deviation"] = (policy.objective.evaluate(ci, repaired)
                                             - policy.objective.evaluate(ci, anchor.plan))
        decisions.append(record)
        triggers = _triggers(policy, record)
    if periodic:
        triggers.append("period")
    new_plan = repaired
    if policy.planner is not None and triggers:
        # accepted or rejected, the result is the plan a complete rescheduling settled on: the new anchor
        new_plan = _reschedule(ci, snap, repaired, policy, decisions, triggers)
        anchor = Anchor(new_plan, snap.t)
    if new_plan != current:
        sim.update_plan(new_plan)
    return anchor


def _change(before: Sequence[Assignment], after: Sequence[Assignment], snap: Snapshot) -> tuple[int, int]:
    """Change of the projected makespan and largest start shift of the operations not started."""
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    start_before = {(a.order_id, a.op_id): a.start for a in before}
    shifts = [abs(a.start - start_before[a.order_id, a.op_id]) for a in after if (a.order_id, a.op_id) not in frozen]
    return max(a.end for a in after) - max(a.end for a in before), max(shifts, default=0)


def _triggers(policy: ReschedulingPolicy, record: dict) -> list[str]:
    """Names of the thresholds the repair exceeded."""
    return [name for name, limit, value in (
        ("makespan", policy.max_makespan_change, abs(record["makespan_deviation"])),
        ("shift", policy.max_shift, record["shift_deviation"]),
        ("objective", policy.max_objective_change, abs(record.get("objective_deviation", 0))),
    ) if limit is not None and value > limit]


def _reschedule(
    ci: CompiledInstance, snap: Snapshot, repaired: Sequence[Assignment], policy: ReschedulingPolicy,
    decisions: list[dict], triggers: list[str],
) -> Sequence[Assignment]:
    """Complete rescheduling; returns the new plan if accepted, otherwise the repaired plan."""
    t0 = time.perf_counter()
    proposed = policy.planner(ci, snap, repaired)
    planner_time = time.perf_counter() - t0  # wall clock seconds; varies between runs
    if violations := check_schedule(ci, proposed, snap):
        raise PlanNotExecutable("planner returned an infeasible plan:\n"
                                + "\n".join(f"[{v.constraint}] {v.message}" for v in violations))
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    machine_before = {(a.order_id, a.op_id): a.machine for a in repaired}
    changed = sum(a.machine != machine_before[a.order_id, a.op_id] for a in proposed
                  if (a.order_id, a.op_id) not in frozen)
    accepted = policy.change_budget is None or changed <= policy.change_budget
    decisions.append({"t": snap.t, "type": "REPLAN", "triggers": triggers, "accepted": accepted,
                      "changed_assignments": changed,
                      "makespan_before": max(a.end for a in repaired), "makespan_after": max(a.end for a in proposed),
                      "planner_time": planner_time})
    return proposed if accepted else repaired
