"""Static CP-SAT model of the base model C1-C5 (math/01_basic-fjsp.md, math/12_cp-sat.md).

One start and one end variable per operation; one optional fixed-size interval per eligible
machine, all sharing the operation's start variable. The objective is a parameter. An optional
hint (e.g. the best dispatching schedule) warm-starts the search; it is not a hard constraint.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN, Objective


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
) -> CpSatResult:
    # trivial horizon: everything in sequence on its slowest machine after the last release
    horizon = max(ci.release) + sum(max(p for _, p in opts) for opts in ci.options)
    model = cp_model.CpModel()
    starts = [model.new_int_var(ci.release[o], horizon, f"S_{o}") for o in range(ci.n_ops)]  # C4 as lower bound
    ends = [model.new_int_var(0, horizon, f"C_{o}") for o in range(ci.n_ops)]
    choice: list[list[tuple[int, cp_model.IntVar]]] = []  # per op: (machine, x_{o,m})
    per_machine: list[list[cp_model.IntervalVar]] = [[] for _ in range(ci.n_machines)]

    for o in range(ci.n_ops):
        lits = []
        for m, p in ci.options[o]:
            x = model.new_bool_var(f"x_{o}_{m}")
            per_machine[m].append(model.new_optional_fixed_size_interval_var(starts[o], p, x, f"a_{o}_{m}"))
            lits.append((m, p, x))
        model.add_exactly_one(x for _, _, x in lits)  # C1
        model.add(ends[o] == starts[o] + sum(p * x for _, p, x in lits))  # C2
        choice.append([(m, x) for m, _, x in lits])
        for q in ci.predecessors[o]:
            model.add(starts[o] >= ends[q])  # C3
    for intervals in per_machine:
        model.add_no_overlap(intervals)  # C5

    for a in hint or ():
        o = ci.op_index[a.order_id, a.op_id]
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
