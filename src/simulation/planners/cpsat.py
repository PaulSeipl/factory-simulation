"""CP-SAT model of the base model C1-C5 (math/01_basic-fjsp.md, math/12_cp-sat.md).

One start and one end variable per operation; one optional fixed-size interval per eligible
machine, all sharing the operation's start variable. The objective is a parameter. An optional
hint (e.g. the best dispatching schedule) warm-starts the search; it is not a hard constraint.

From a snapshot (complete rescheduling, math/05_rescheduling-frozen-part.md): frozen operations are
fixed intervals with the times of the snapshot (C7), all others start at t at the earliest (C6). With
a reference plan and a change budget, at most that many operations not started may run on another
machine than in the reference plan.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN, Objective

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot


@dataclass(frozen=True, slots=True)
class CpSatResult:
    status: str  # CP-SAT status name: OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN, MODEL_INVALID
    schedule: list[Assignment]  # empty unless a solution was found
    objective: int | None  # objective value of the schedule
    bound: int | None  # best proven lower bound on the objective
    wall_time: float  # seconds


def solve(
    ci: CompiledInstance,
    objective: Objective = MAKESPAN,
    time_limit: float = 10.0,
    workers: int = 8,
    seed: int = 0,
    hint: Sequence[Assignment] | None = None,
    snapshot: Snapshot | None = None,
    reference: Sequence[Assignment] | None = None,
    change_budget: int | None = None,
) -> CpSatResult:
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    t = snapshot.t if snapshot else 0
    # trivial horizon: after the last fixed time point, every free operation in sequence on its slowest machine
    horizon = max([*ci.release, t, *(f.end for f in frozen.values())]) + sum(
        max(p for _, p in ci.options[o]) for o in range(ci.n_ops) if o not in frozen
    )
    model = cp_model.CpModel()
    starts: list[cp_model.IntVar] = []
    ends: list[cp_model.IntVar] = []
    choice: list[list[tuple[int, cp_model.IntVar]]] = []  # per op: (machine, x_{o,m})
    per_machine: list[list[cp_model.IntervalVar]] = [[] for _ in range(ci.n_machines)]

    for o in range(ci.n_ops):
        if (f := frozen.get(o)) is not None:  # C7: fixed machine and times (realized or expected end)
            m = ci.machine_index[f.machine]
            starts.append(model.new_constant(f.start))
            ends.append(model.new_constant(f.end))
            per_machine[m].append(model.new_fixed_size_interval_var(f.start, f.end - f.start, f"frozen_{o}"))
            choice.append([(m, model.new_constant(1))])
            continue
        starts.append(model.new_int_var(max(ci.release[o], t), horizon, f"S_{o}"))  # C4 and C6 as lower bound
        ends.append(model.new_int_var(0, horizon, f"C_{o}"))
        lits = []
        for m, p in ci.options[o]:
            x = model.new_bool_var(f"x_{o}_{m}")
            per_machine[m].append(model.new_optional_fixed_size_interval_var(starts[o], p, x, f"a_{o}_{m}"))
            lits.append((m, p, x))
        model.add_exactly_one(x for _, _, x in lits)  # C1
        model.add(ends[o] == starts[o] + sum(p * x for _, p, x in lits))  # C2
        choice.append([(m, x) for m, _, x in lits])
    for o in range(ci.n_ops):
        if o not in frozen:
            for q in ci.predecessors[o]:
                model.add(starts[o] >= ends[q])  # C3
    for intervals in per_machine:
        model.add_no_overlap(intervals)  # C5

    if reference is not None and change_budget is not None:  # at most change_budget machines differ
        machine_before = {ci.op_index[a.order_id, a.op_id]: ci.machine_index[a.machine] for a in reference}
        model.add(sum(1 - x for o in range(ci.n_ops) if o not in frozen
                      for m, x in choice[o] if m == machine_before[o]) <= change_budget)

    for a in hint or ():
        o = ci.op_index[a.order_id, a.op_id]
        if o in frozen:
            continue
        model.add_hint(starts[o], a.start)
        model.add_hint(ends[o], a.end)
        for m, x in choice[o]:
            model.add_hint(x, ci.machine_ids[m] == a.machine)

    model.minimize(objective.cpsat(model, ci, starts, ends, horizon))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    status = solver.solve(model)
    name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return CpSatResult(name, [], None, None, solver.wall_time)

    schedule = []
    for o in range(ci.n_ops):
        m = next(m for m, x in choice[o] if solver.boolean_value(x))
        order_id, op_id = ci.op_keys[o]
        schedule.append(Assignment(
            order_id=order_id, op_id=op_id, machine=ci.machine_ids[m],
            start=solver.value(starts[o]), end=solver.value(ends[o]),
        ))
    return CpSatResult(
        name, schedule, round(solver.objective_value), round(solver.best_objective_bound), solver.wall_time
    )


def cpsat_planner(
    time_limit: float = 1.0, workers: int = 1, seed: int = 0, change_budget: int | None = None,
    objective: Objective = MAKESPAN,
):
    """Planner for the complete rescheduling: planner(ci, snapshot, current_plan) -> new complete plan.

    The current (repaired) plan is the hint and the reference for the change budget. One worker by default,
    so that runs with the same seed are reproducible.
    """

    def planner(ci: CompiledInstance, snapshot: Snapshot, current: Sequence[Assignment]) -> list[Assignment]:
        result = solve(ci, objective, time_limit, workers, seed, hint=current, snapshot=snapshot,
                       reference=current, change_budget=change_budget)
        # shortcut: without a solution within the time limit the current plan is kept; raise the limit if this occurs
        return result.schedule or list(current)

    return planner
