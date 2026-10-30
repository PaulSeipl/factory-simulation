"""The planning tool during execution (math/05_rescheduling-frozen-part.md).

At every time point of the DES, after its events and before anything starts:
1. read the snapshot (what the factory knows now, no scenario data),
2. repair the current plan (left/right shift),
3. if the repaired plan deviates substantially from the anchor (the plan of the last complete
   rescheduling, at first the start plan), ask a planner for a complete rescheduling and accept its
   plan if it stays within the change budget,
4. send the resulting plan to the factory.
The DES itself never decides anything; it only executes the plan it receives.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.planners.repair import repair
from simulation.sim.des import PlanNotExecutable, Simulation
from simulation.sim.scenario import Scenario
from simulation.sim.snapshot import Snapshot

# planner(ci, snapshot, current_plan) -> new complete plan (frozen operations as in the snapshot)
type Planner = Callable[[CompiledInstance, Snapshot, Sequence[Assignment]], list[Assignment]]


@dataclass(frozen=True, slots=True)
class ReschedulingPolicy:
    """Repair at every time point; complete rescheduling when a threshold is exceeded (math/05, section 3)."""

    planner: Planner | None = None  # complete rescheduling; None: repair only
    max_makespan_change: int | None = None  # trigger if the projected makespan deviates from the anchor by more
    max_shift: int | None = None  # trigger if a start deviates from the anchor by more
    change_budget: int | None = None  # reject a plan that changes more machine assignments


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
    anchor = sim.current_plan()
    while not sim.done:
        sim.process_events()
        if policy is not None:
            anchor = adapt_plan(ci, sim, policy, decisions, anchor)
        sim.start_operations()
    sim.check_completed()
    return ExecutionResult(sim.realized(), sim.log, decisions)


def adapt_plan(
    ci: CompiledInstance, sim: Simulation, policy: ReschedulingPolicy, decisions: list[dict],
    anchor: Sequence[Assignment],
) -> Sequence[Assignment]:
    """One step of the planning tool; returns the anchor for the next step."""
    snap, current = sim.snapshot(), sim.current_plan()
    repaired = repair(ci, snap, current)
    if repaired == current:
        return anchor
    makespan_change, max_shift = _change(current, repaired, snap)
    # measured against the anchor, so that many small repairs add up instead of each staying below the threshold
    makespan_deviation, shift_deviation = _change(anchor, repaired, snap)
    decisions.append({"t": snap.t, "type": "REPAIR", "makespan_change": makespan_change, "max_shift": max_shift,
                      "makespan_deviation": makespan_deviation, "shift_deviation": shift_deviation})
    new_plan = repaired
    if policy.planner is not None and _triggered(policy, makespan_deviation, shift_deviation):
        # accepted or rejected, the result is the plan a complete rescheduling settled on: the new anchor
        new_plan = anchor = _reschedule(ci, snap, repaired, policy, decisions)
    sim.update_plan(new_plan)
    return anchor


def _change(before: Sequence[Assignment], after: Sequence[Assignment], snap: Snapshot) -> tuple[int, int]:
    """Change of the projected makespan and largest start shift of the operations not started."""
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    start_before = {(a.order_id, a.op_id): a.start for a in before}
    shifts = [abs(a.start - start_before[a.order_id, a.op_id]) for a in after if (a.order_id, a.op_id) not in frozen]
    return max(a.end for a in after) - max(a.end for a in before), max(shifts, default=0)


def _triggered(policy: ReschedulingPolicy, makespan_deviation: int, shift_deviation: int) -> bool:
    return (policy.max_makespan_change is not None and abs(makespan_deviation) > policy.max_makespan_change) or (
        policy.max_shift is not None and shift_deviation > policy.max_shift
    )


def _reschedule(
    ci: CompiledInstance, snap: Snapshot, repaired: Sequence[Assignment], policy: ReschedulingPolicy,
    decisions: list[dict],
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
    decisions.append({"t": snap.t, "type": "REPLAN", "accepted": accepted, "changed_assignments": changed,
                      "makespan_before": max(a.end for a in repaired), "makespan_after": max(a.end for a in proposed),
                      "planner_time": planner_time})
    return proposed if accepted else repaired
