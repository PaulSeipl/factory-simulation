"""CP-SAT model of the base model C1-C5 (math/01_basic-fjsp.md, math/12_cp-sat.md).

One start and one end variable per operation; one optional fixed-size interval per eligible
machine, all sharing the operation's start variable. The objective is a parameter. An optional
hint (e.g. the best dispatching schedule) warm-starts the search; it is not a hard constraint.

From a snapshot (complete rescheduling, math/05_rescheduling-frozen-part.md): frozen operations are
fixed intervals with the times of the snapshot (C7), all others start at t at the earliest (C6). With
a reference plan and a change budget, at most that many operations not started may run on another
machine than in the reference plan.

Runs (math/03_carriers.md): the operations of a run choose the same machine (C8), and instead of their own
intervals one interval from the start of the first to the end of the last operation enters the machine's
no-overlap constraint (C9: the machine is blocked also while the removal waits).

Batches (C10): operations of a batch step are assigned to batch slots; a used slot has a machine and a start,
occupies the machine once and holds at most the capacity; an operation in a slot takes its machine and start.

Workers (math/04_workers.md, no calendar yet): operations without machine have C = S + p (C1'). Per share and
qualified worker an optional interval (prefix at the start, suffix at the end, whole share over the operation),
exactly one worker per share (C11), no overlap per worker (C12). A batch's shares belong to its slot (one set of
workers per run). Frozen: started shares are fixed intervals of their worker; a pending removal ends at the
forced end of C7^o, with a worker free of the frozen part then.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from simulation.calendar import day_index, day_start, is_working_day
from simulation.model.compiled import CompiledInstance, Share
from simulation.model.schedule import Assignment, Break, Plan
from simulation.objectives import MAKESPAN, CalendarVars, Objective, horizon_bound, level_weights, serial_end
from simulation.planners.repair import forced_removals

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot


@dataclass(frozen=True, slots=True)
class CpSatResult:
    status: str  # CP-SAT status name: OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN, MODEL_INVALID
    schedule: list[Assignment]  # empty unless a solution was found
    objective: int | None  # objective value of the schedule
    bound: int | None  # best proven lower bound on the objective
    wall_time: float  # seconds
    breaks: tuple[Break, ...] = ()  # with workers and a calendar: one per worker and working day of the horizon
    levels: tuple[int, ...] = ()  # the solver's value per level (one entry for a single objective)


def solve(
    ci: CompiledInstance,
    objective: Objective = MAKESPAN,
    time_limit: float = 10.0,
    workers: int = 8,  # solver threads (not the factory's workers, which come from ci)
    seed: int = 0,
    hint: Sequence[Assignment] | None = None,
    snapshot: Snapshot | None = None,
    reference: Sequence[Assignment] | None = None,
    change_budget: int | None = None,
    deterministic_time: float | None = None,  # work-based limit: same result under any machine load (1 worker)
) -> CpSatResult:
    cal = ci.calendar if ci.worker_ids else None  # shifts and breaks bind workers only (machines run at any time)
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    # op -> (share, forced start, free workers, booked worker), C7^o
    removal = forced_removals(ci, snapshot) if snapshot else {}
    end_of = {o: f.end for o, f in frozen.items()} | {o: s + ci.shares[o][i].length
                                                     for o, (i, s, *_) in removal.items()}
    t = snapshot.t if snapshot else 0

    def durations(o: int) -> list[int]:
        return [p for _, p in ci.options[o]] or [ci.fixed_duration[o]]

    # trivial horizon: after the last fixed time point, every free operation in sequence on its slowest machine (with
    # a calendar: from the next working morning on, each one's shares inside the shift and outside 12:00-13:00)
    base = max([*ci.release, t, *end_of.values()])
    free_ops = [o for o in ci.topo_order if o not in frozen]
    horizon = (serial_end(ci, base, free_ops) if cal is not None
               else base + sum(max(durations(o)) for o in free_ops))
    model = cp_model.CpModel()
    starts: list[cp_model.IntVar] = []
    ends: list[cp_model.IntVar] = []
    choice: list[list[tuple[int, cp_model.IntVar]]] = []  # per op: (machine, x_{o,m}); empty without machine
    per_machine: list[list[cp_model.IntervalVar]] = [[] for _ in range(ci.n_machines)]
    per_worker: list[list[cp_model.IntervalVar]] = [[] for _ in ci.worker_ids]
    # occupy their machine through the run's span (C9) or through their batch slot (C10)
    in_run = {o for g in ci.machine_groups for o in g} | {o for o in range(ci.n_ops) if ci.batch_capacity[o] > 1}
    frozen_batches: set[tuple[str | None, int, int]] = set()

    for o in range(ci.n_ops):
        if (f := frozen.get(o)) is not None:  # C7: fixed machine and times (realized, expected or forced end)
            starts.append(model.new_constant(f.start))
            ends.append(model.new_constant(end_of[o]))
            if f.machine is None:
                choice.append([])
                continue
            m = ci.machine_index[f.machine]
            batch = ci.batch_capacity[o] > 1
            if o not in in_run or (batch and (f.machine, f.start, f.end) not in frozen_batches):
                frozen_batches.add((f.machine, f.start, f.end))  # a started batch blocks its machine once
                per_machine[m].append(model.new_fixed_size_interval_var(f.start, end_of[o] - f.start, f"frozen_{o}"))
            choice.append([(m, model.new_constant(1))])
            continue
        starts.append(model.new_int_var(max(ci.release[o], t), horizon, f"S_{o}"))  # C4 and C6 as lower bound
        ends.append(model.new_int_var(0, horizon, f"C_{o}"))
        if (fixed := ci.fixed_duration[o]) is not None:  # C1': no machine, fixed duration
            model.add(ends[o] == starts[o] + fixed)
            choice.append([])
            continue
        lits = []
        for m, p in ci.options[o]:
            x = model.new_bool_var(f"x_{o}_{m}")
            if o not in in_run:
                per_machine[m].append(model.new_optional_fixed_size_interval_var(starts[o], p, x, f"a_{o}_{m}"))
            lits.append((m, p, x))
        model.add_exactly_one(x for _, _, x in lits)  # C1
        model.add(ends[o] == starts[o] + sum(p * x for _, p, x in lits))  # C2
        choice.append([(m, x) for m, _, x in lits])
    for o in range(ci.n_ops):
        if o not in frozen:
            for q in ci.predecessors[o]:
                model.add(starts[o] >= ends[q])  # C3
    for g in ci.machine_groups:
        x_first = dict(choice[g[0]])
        for q in g[1:]:  # C8: one machine for the whole run
            for m, x in choice[q]:
                model.add(x == x_first.get(m, 0))
        span = model.new_int_var(0, horizon, f"span_{g[0]}")
        for m, x in x_first.items():  # C9: the machine is blocked from the first start to the last end
            blocked = model.new_optional_interval_var(starts[g[0]], span, ends[g[-1]], x, f"run_{g[0]}_{m}")
            per_machine[m].append(blocked)

    def shares_of(name: str, shares: Sequence[Share], start, end, present) -> list[list[tuple[int, cp_model.IntVar]]]:
        """Worker choice per share of an operation (or a batch slot) in [start, end); `present`: 1 or the slot's
        used literal. Returns per share [(worker, v)]."""
        out = []
        for i, sh in enumerate(shares):
            lits = []
            if sh.kind == "whole":  # interval terms must be affine: the duration as a variable
                size = model.new_int_var(0, horizon, f"len_{name}_{i}")
                model.add(size == end - start)
            for z in sh.workers:
                v = model.new_bool_var(f"v_{name}_{i}_{z}")
                if sh.kind == "prefix":
                    iv = model.new_optional_fixed_size_interval_var(start, sh.length, v, f"w_{name}_{i}_{z}")
                elif sh.kind == "suffix":
                    iv = model.new_optional_fixed_size_interval_var(end - sh.length, sh.length, v, f"w_{name}_{i}_{z}")
                else:
                    iv = model.new_optional_interval_var(start, size, end, v, f"w_{name}_{i}_{z}")
                per_worker[z].append(iv)
                lits.append((z, v))
            model.add(sum(v for _, v in lits) == present)  # C11: one qualified worker per share
            out.append(lits)
        return out

    share_lits: dict[int, list[list[tuple[int, cp_model.IntVar]]]] = {}  # op -> per share [(worker, v)]
    families: dict[tuple, list[int]] = {}  # operations that may share a batch: same options, capacity and shares
    for o in range(ci.n_ops):
        if o in frozen:
            continue
        if ci.batch_capacity[o] > 1:
            families.setdefault((ci.options[o], ci.batch_capacity[o], ci.shares[o]), []).append(o)
        elif ci.shares[o]:
            share_lits[o] = shares_of(str(o), ci.shares[o], starts[o], ends[o], 1)
    slot_of: dict[int, list[tuple[cp_model.IntVar, list]]] = {}  # batch op -> [(y_oj, slot's share choice)]
    for (options, capacity, shares), ops in families.items():
        used, slot_start, slot_machine, members = [], [], [], []
        for j in range(len(ops)):  # at most one slot per operation
            used.append(model.new_bool_var(f"batch_{ops[0]}_{j}"))
            slot_start.append(model.new_int_var(0, horizon, f"T_{ops[0]}_{j}"))
            slot_machine.append({m: model.new_bool_var(f"z_{ops[0]}_{j}_{m}") for m, _ in options})
            model.add(sum(slot_machine[j].values()) == used[j])
            for m, p in options:
                per_machine[m].append(model.new_optional_fixed_size_interval_var(
                    slot_start[j], p, slot_machine[j][m], f"slot_{ops[0]}_{j}_{m}"))
            members.append([])
            if j:
                model.add(used[j] <= used[j - 1])  # symmetry: slots are used from the front
        slot_shares = [[] for _ in ops]
        for j in range(len(ops) if shares else 0):
            slot_end = model.new_int_var(0, horizon, f"E_{ops[0]}_{j}")  # affine end for the suffix interval
            model.add(slot_end == slot_start[j] + sum(p * slot_machine[j][m] for m, p in options))
            slot_shares[j] = shares_of(f"{ops[0]}_{j}", shares, slot_start[j], slot_end, used[j])
        for i, o in enumerate(ops):
            y = [model.new_bool_var(f"y_{o}_{j}") for j in range(i + 1)]  # symmetry: operation i uses a slot <= i
            model.add_exactly_one(y)
            x_of = dict(choice[o])
            for j, y_oj in enumerate(y):
                model.add(starts[o] == slot_start[j]).only_enforce_if(y_oj)
                for m, z in slot_machine[j].items():
                    model.add(z == x_of.get(m, 0)).only_enforce_if(y_oj)
                members[j].append(y_oj)
            slot_of[o] = [(y_oj, slot_shares[j]) for j, y_oj in enumerate(y)]
        for j in range(len(ops)):
            model.add(sum(members[j]) <= capacity * used[j])
    for intervals in per_machine:
        model.add_no_overlap(intervals)  # C5

    # frozen worker time: started shares as in the snapshot (a batch once), pending removals at the forced time
    frozen_workers: dict[int, list] = {}
    frozen_time: list[list[tuple[int, int]]] = [[] for _ in ci.worker_ids]  # what is fixed per worker (calendar)
    seen: set[tuple[str | None, int, int]] = set()
    for o, f in frozen.items():
        if ci.batch_capacity[o] > 1 and (f.machine, f.start, f.end) in seen:
            continue
        seen.add((f.machine, f.start, f.end))
        lengths = f.share_lengths or [sh.length for sh in ci.shares[o]]
        for sh, n, w in zip(ci.shares[o], lengths, f.workers, strict=True):
            if w is not None:
                if sh.kind == "prefix":
                    a = f.start
                elif sh.kind == "suffix":
                    a = f.end - n
                else:
                    a, n = f.start, f.end - f.start
                per_worker[z := ci.worker_ids.index(w)].append(model.new_fixed_size_interval_var(a, n, f"fw_{o}"))
                frozen_time[z].append((a, a + n))
        if o in removal:
            i, s, free, booked = removal[o]
            n = ci.shares[o][i].length
            if len(set(map(id, removal.values()))) > 1:  # several runs: each forced time assumes the others' workers
                free = [booked]
            if cal is not None and len(free) > 1 and any(
                    s < day_start(cal, d) + cal.break_latest + cal.break_length
                    and day_start(cal, d) + cal.break_earliest < s + n for d in (day_index(cal, s),)):
                free = free[:1]  # near a break: one worker, so that its forced postponement (C14^f) is known
            if len(free) == 1:
                frozen_time[free[0]].append((s, s + n))
            frozen_workers[o] = []
            for z in free:
                v = model.new_bool_var(f"v_removal_{o}_{z}")
                per_worker[z].append(model.new_optional_fixed_size_interval_var(s, ci.shares[o][i].length, v,
                                                                                f"w_removal_{o}_{z}"))
                frozen_workers[o].append((z, v))
            model.add_exactly_one(v for _, v in frozen_workers[o])
    calendar_vars, break_vars = (_calendar(model, ci, snapshot, horizon, per_worker, frozen_time) if cal is not None
                                 else (None, []))
    for intervals in per_worker:
        model.add_no_overlap(intervals)  # C12 (with the calendar also C13 and the breaks, C14)

    if reference is not None and change_budget is not None:  # at most change_budget machines differ
        machine_before = {ci.op_index[a.order_id, a.op_id]: ci.machine_index[a.machine] for a in reference
                          if a.machine is not None}
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
        for lits, w in zip(share_lits.get(o, ()), a.workers, strict=False):
            for z, v in lits:
                model.add_hint(v, ci.worker_ids[z] == w)

    if horizon - t > horizon_bound(ci):  # the spreads of the lexicographic weights rely on it (math/06 section 4)
        raise AssertionError(f"horizon {horizon} - t {t} exceeds the bound {horizon_bound(ci)}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit  # per level of a lexicographic objective
    if deterministic_time is not None:
        solver.parameters.max_deterministic_time = deterministic_time
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    # a lexicographic objective level by level (math/06 (O3)): minimize level i, keep it at most at its value, hint
    # the solution to the next level; no weights, so no large coefficients. Exact if every level is solved to optimum
    levels = objective.levels or (objective,)
    if not objective.levels and objective.spread(ci) >= 2**53:  # solver values are doubles: exact only below 2^53
        raise ValueError(f"objective {objective.name}: spread {objective.spread(ci)} too large for exact values")
    values, bounds, statuses, wall = [], [], [], 0.0
    for i, level in enumerate(levels):
        expr = level.cpsat(model, ci, starts, ends, horizon, calendar_vars)
        model.minimize(expr)
        status = solver.solve(model)
        wall += solver.wall_time
        if status == cp_model.INFEASIBLE and i > 0:
            # the previous level's solution satisfies this model, so INFEASIBLE is wrong: OR-Tools 9.15 presolve
            # can reject a bound at exactly the optimum (protocol 2026-11-11 (40)); retry this level without presolve
            solver.parameters.cp_model_presolve = False
            status = solver.solve(model)
            wall += solver.wall_time
            solver.parameters.cp_model_presolve = True
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if i == 0:
                return CpSatResult(solver.status_name(status), [], None, None, wall)
            # shortcut: the hinted solution of the previous level should be found at once; raise the limit otherwise
            raise RuntimeError(f"level {level.name}: no solution within the time limit ({solver.status_name(status)})")
        statuses.append(status)
        values.append(round(solver.value(expr)))
        bounds.append(round(solver.best_objective_bound))
        if i + 1 < len(levels):
            model.add(expr <= values[-1])
            model.clear_hints()
            for j in range(len(model.proto.variables)):
                v = model.get_int_var_from_proto_index(j)
                model.add_hint(v, solver.value(v))
    name = "OPTIMAL" if all(s == cp_model.OPTIMAL for s in statuses) else "FEASIBLE"

    def chosen(lits) -> str:
        return next(ci.worker_ids[z] for z, v in lits if solver.boolean_value(v))

    schedule = []
    for o in range(ci.n_ops):
        if o in frozen:
            ws = list(frozen[o].workers)
            if o in frozen_workers:
                ws[removal[o][0]] = chosen(frozen_workers[o])
            elif o in removal:  # a later member of a frozen batch: the removal of its first member
                lead = next(q for q in frozen_workers if (frozen[q].machine, frozen[q].start, frozen[q].end)
                            == (frozen[o].machine, frozen[o].start, frozen[o].end))
                ws[removal[o][0]] = chosen(frozen_workers[lead])
        elif o in slot_of:
            lits = next(sl for y, sl in slot_of[o] if solver.boolean_value(y))
            ws = [chosen(share) for share in lits]
        else:
            ws = [chosen(share) for share in share_lits.get(o, ())]
        m = next((m for m, x in choice[o] if solver.boolean_value(x)), None)
        order_id, op_id = ci.op_keys[o]
        # a started share with the snapshot's length where it differs from the planned one (the checker reads it)
        lengths = frozen[o].share_lengths if o in frozen else ()
        if not any(sh.kind != "whole" and n != sh.length for sh, n in zip(ci.shares[o], lengths, strict=False)):
            lengths = ()
        schedule.append(Assignment(
            order_id=order_id, op_id=op_id, machine=None if m is None else ci.machine_ids[m],
            start=solver.value(starts[o]), end=solver.value(ends[o]), workers=tuple(ws), share_lengths=lengths,
        ))
    breaks = tuple(sorted((Break(worker=ci.worker_ids[z], start=b if isinstance(b, int) else solver.value(b))
                           for z, b in break_vars),
                          key=lambda b: (b.start, b.worker)))
    if objective.levels:  # the combined value from the plan (exact Python integers, weights of (O3))
        value = objective.evaluate(ci, schedule, breaks)
        # lower bound: the optimal levels before the first one not proven, that one's bound, 0 below (levels >= 0)
        k = next((i for i, st in enumerate(statuses) if st != cp_model.OPTIMAL), len(levels) - 1)
        weights = level_weights(ci, levels)
        bound = sum(w * v for w, v in zip(weights[:k], values[:k], strict=True)) + weights[k] * bounds[k]
    else:
        value, bound = round(solver.objective_value), round(solver.best_objective_bound)
    return CpSatResult(name, schedule, value, bound, wall, breaks, tuple(values))


def _calendar(model, ci: CompiledInstance, snapshot: Snapshot | None, horizon: int, per_worker, frozen_time):
    """C13 and C14 per worker (math/04_workers.md, math/12_cp-sat.md section 7b): fixed blocks for night and
    weekend; per working day an overtime variable ot in [0, max overtime] and a block [shift end + ot, shift end +
    max overtime); per working day one break (always present, decision 2a of the phase 4 plan), in the window, from t
    on the snapshot's day, the taken one fixed, or at the earliest clear start after the window if none fits (C14^f).
    Every block starts after the frozen work it would hit (an overrun). Returns the terms for the objectives
    (`CalendarVars`: overtime per worker and day, the overtime of earlier days, breaks with their day) and
    [(worker, break start)] for the output; constants are plain ints."""
    cal, t = ci.calendar, snapshot.t if snapshot else 0
    taken = {(ci.worker_ids.index(b.worker), day_index(cal, b.start)): b.start for b in snapshot.breaks} if snapshot \
        else {}
    days = [d for d in range(day_index(cal, t), day_index(cal, horizon) + 2) if is_working_day(cal, d)]
    history = [(z, d, b) for (z, d), b in taken.items() if d < days[0]]  # taken on earlier days, kept (C7^b)
    breaks = [(z, b) for z, _, b in history]
    terms = CalendarVars(breaks=[(d, b) for _, d, b in history])
    past = defaultdict(int)  # (worker, day) -> end of its last frozen share, on the days before the model's
    for z in range(len(ci.worker_ids)):
        fz = frozen_time[z]
        for a, e in fz:
            if (d := day_index(cal, a)) < days[0]:
                past[z, d] = max(past[z, d], e)

        def after_frozen(a: int, b: int, fz=fz) -> int:  # a block [a, b) starts after frozen work running into it
            return max([a, *(e for s, e in fz if s < b and e > a)])

        prev = t
        for d in days:
            ds = day_start(cal, d)
            if (a := after_frozen(prev, ds + cal.shift_start)) < ds + cal.shift_start:  # night, weekend
                per_worker[z].append(model.new_fixed_size_interval_var(a, ds + cal.shift_start - a, f"off_{z}_{d}"))
            h_end, latest = ds + cal.shift_end, ds + cal.shift_end + cal.max_overtime
            lb = max([0, *(e - h_end for s, e in fz if s < latest and e > h_end)])
            if lb <= cal.max_overtime:  # C13: shares of the day end by shift end + ot
                ot = model.new_int_var(lb, cal.max_overtime, f"ot_{z}_{d}")
                per_worker[z].append(model.new_interval_var(h_end + ot, cal.max_overtime - ot, latest,
                                                            f"after_{z}_{d}"))
                terms.overtime.append(ot)
            else:  # a frozen overrun past shift end + max overtime: its overtime is history
                terms.overtime.append(lb)
            prev = latest
            if (z, d) in taken:
                b = taken[z, d]
                per_worker[z].append(model.new_fixed_size_interval_var(b, cal.break_length, f"br_{z}_{d}"))
                breaks.append((z, b))
                terms.breaks.append((d, b))
                continue
            lo, hi = max(ds + cal.break_earliest, t), ds + cal.break_latest
            first = _clear_start(fz, lo, cal.break_length)
            if first <= hi:  # a break in the window (C14)
                b = model.new_int_var(lo, hi, f"br_{z}_{d}")
            elif t <= hi or any(ds <= s < hi for s, _ in fz):  # owed, but nothing fits: forced postponement (C14^f)
                b = first
            else:
                continue  # the snapshot's day after the window with nothing before it: no break owed
            per_worker[z].append(model.new_fixed_size_interval_var(b, cal.break_length, f"brk_{z}_{d}"))
            breaks.append((z, b))
            terms.breaks.append((d, b))
    past_overtime = sum(max(0, e - day_start(cal, d) - cal.shift_end) for (_, d), e in past.items())
    return dataclasses.replace(terms, past_overtime=past_overtime), breaks


def _clear_start(intervals: Sequence[tuple[int, int]], s: int, n: int) -> int:
    """Earliest s' >= s with [s', s' + n) clear of `intervals`."""
    while (e := next((e for a, e in intervals if a < s + n and s < e), None)) is not None:
        s = e
    return s


def cpsat_planner(
    time_limit: float = 1.0, workers: int = 1, seed: int = 0, change_budget: int | None = None,
    objective: Objective = MAKESPAN,
):
    """Planner for the complete rescheduling: planner(ci, snapshot, current_plan) -> new complete plan.

    The current (repaired) plan is the hint and the reference for the change budget. One worker by default,
    so that runs with the same seed are reproducible.
    """

    def planner(ci: CompiledInstance, snapshot: Snapshot, current: Sequence[Assignment]) -> Plan:
        result = solve(ci, objective, time_limit, workers, seed, hint=current, snapshot=snapshot,
                       reference=current, change_budget=change_budget)
        if not result.schedule and ci.calendar is not None and ci.worker_ids:
            # the planner interface has no current breaks to fall back on
            raise RuntimeError(f"CP-SAT found no plan within {time_limit} s ({result.status}); raise the time limit")
        # shortcut: without a solution within the time limit the current plan is kept; raise the limit if this occurs
        return Plan(result.schedule or list(current), result.breaks)

    return planner
