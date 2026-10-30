"""The planning tool during execution (math/05_rescheduling-frozen-part.md).

At every time point of the DES, after its events and before anything starts:
1. read the snapshot (what the factory knows now, no scenario data),
2. repair the current plan (left/right shift),
3. if the repair changes the plan substantially, ask a planner for a complete rescheduling and accept
   its plan if it stays within the change budget,
4. send the resulting plan to the factory.
The DES itself never decides anything; it only executes the plan it receives.
"""

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
    max_makespan_change: int | None = None  # trigger if a repair changes the projected makespan by more
    max_shift: int | None = None  # trigger if a repair shifts a start by more
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
    while not sim.done:
        sim.process_events()
        if policy is not None:
            adapt_plan(ci, sim, policy, decisions)
        sim.start_operations()
    sim.check_completed()
    return ExecutionResult(sim.realized(), sim.log, decisions)


def adapt_plan(ci: CompiledInstance, sim: Simulation, policy: ReschedulingPolicy, decisions: list[dict]) -> None:
    snap, current = sim.snapshot(), sim.current_plan()
    repaired = repair(ci, snap, current)
    if repaired == current:
        return
    makespan_change, max_shift = _change(current, repaired, snap)
    decisions.append({"t": snap.t, "type": "REPAIR", "makespan_change": makespan_change, "max_shift": max_shift})
    new_plan = repaired
    if policy.planner is not None and _triggered(policy, makespan_change, max_shift):
        new_plan = _reschedule(ci, snap, repaired, policy, decisions)
    sim.update_plan(new_plan)


def _change(current: Sequence[Assignment], repaired: Sequence[Assignment], snap: Snapshot) -> tuple[int, int]:
    """Change of the projected makespan and largest start shift of the operations not started."""
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    shifts = [abs(b.start - a.start) for a, b in zip(current, repaired, strict=True)
              if (a.order_id, a.op_id) not in frozen]
    return max(a.end for a in repaired) - max(a.end for a in current), max(shifts, default=0)


def _triggered(policy: ReschedulingPolicy, makespan_change: int, max_shift: int) -> bool:
    return (policy.max_makespan_change is not None and abs(makespan_change) > policy.max_makespan_change) or (
        policy.max_shift is not None and max_shift > policy.max_shift
    )


def _reschedule(
    ci: CompiledInstance, snap: Snapshot, repaired: Sequence[Assignment], policy: ReschedulingPolicy,
    decisions: list[dict],
) -> Sequence[Assignment]:
    """Complete rescheduling; returns the new plan if accepted, otherwise the repaired plan."""
    proposed = policy.planner(ci, snap, repaired)
    if violations := check_schedule(ci, proposed, snap):
        raise PlanNotExecutable("planner returned an infeasible plan:\n"
                                + "\n".join(f"[{v.constraint}] {v.message}" for v in violations))
    frozen = {(f.order_id, f.op_id) for f in snap.frozen}
    machine_before = {(a.order_id, a.op_id): a.machine for a in repaired}
    changed = sum(a.machine != machine_before[a.order_id, a.op_id] for a in proposed
                  if (a.order_id, a.op_id) not in frozen)
    accepted = policy.change_budget is None or changed <= policy.change_budget
    decisions.append({"t": snap.t, "type": "REPLAN", "accepted": accepted, "changed_assignments": changed,
                      "makespan_before": max(a.end for a in repaired), "makespan_after": max(a.end for a in proposed)})
    return proposed if accepted else repaired
