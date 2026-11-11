"""Objectives as pairs: evaluation of a finished schedule and the same expression for CP-SAT.

Both halves agree on every CP-SAT solution (tested), with one exception: the overtime of the worker objective
(math/04_workers.md, math/12_cp-sat.md section 7b) is bounded from below by the shares in CP-SAT, so on a solution
that is only FEASIBLE the solver's value may exceed `evaluate`; at the optimum (overtime weight > 0) they agree,
and the bound stays a valid lower bound. See math/01_basic-fjsp.md, section 4, and math/06_due-dates.md, section 4
(due-date objectives, lexicographic combination).
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from ortools.sat.python import cp_model

from simulation.calendar import (
    DAY,
    WEEK,
    cutoffs,
    day_index,
    day_start,
    days_late,
    is_working_day,
    minute_of_day,
    next_cutoff,
    shift_window,
)
from simulation.check.feasibility import worker_intervals
from simulation.model.compiled import CompiledInstance, share_interval
from simulation.model.schedule import Assignment, Break


@dataclass(frozen=True, slots=True)
class CalendarVars:
    """CP-SAT terms of the worker calendar for the objectives (math/12_cp-sat.md section 7b)."""

    overtime: list = field(default_factory=list)  # ot per worker and working day of the model (variable or constant)
    past_overtime: int = 0  # overtime on the days before the snapshot's (history)
    breaks: list = field(default_factory=list)  # (day, break start) of every break of the plan, taken ones too


@dataclass(frozen=True, slots=True)
class Objective:
    name: str
    # evaluate(ci, schedule, breaks=()) -> value to minimize
    evaluate: Callable[..., int]
    # cpsat(model, ci, starts, ends, horizon, calendar_vars=None) -> expression to minimize
    cpsat: Callable[..., cp_model.LinearExprT]
    # spread(ci) >= difference of the values of any two solutions of one CP-SAT model (static or from a snapshot);
    # the weight of a higher level in `lexicographic`
    spread: Callable[[CompiledInstance], int]
    # the levels of a lexicographic objective, highest first (CP-SAT solves them one after another); empty otherwise
    levels: tuple["Objective", ...] = ()


def _longest(ci: CompiledInstance, o: int) -> int:
    return max(p for _, p in ci.options[o]) if ci.options[o] else ci.fixed_duration[o]


def static_horizon(ci: CompiledInstance) -> int:
    """H_0: latest release plus every operation on its slowest machine (the horizon of the static model)."""
    return max(ci.release) + sum(_longest(ci, o) for o in range(ci.n_ops))


def serial_end(ci: CompiledInstance, base: int, ops: Sequence[int]) -> int:
    """End of a feasible serial plan with a calendar: from the next working morning after the day of `base`, one
    operation after the other on its slowest machine, every share inside the shift window (with overtime) and outside
    12:00-13:00 (where every worker can take its break). A subset of the operations in the same order ends no later
    (each start is a monotone function of the previous end)."""
    cal = ci.calendar
    d = next(e for e in range(day_index(cal, base) + 1, day_index(cal, base) + 9) if is_working_day(cal, e))
    s = day_start(cal, d) + cal.shift_start
    for o in ops:
        p, limit = _longest(ci, o), s + 2 * WEEK
        while True:
            need = s
            for sh in ci.shares[o]:
                lo, hi = share_interval(sh, s, s + p)
                a = lo
                while True:
                    if a > limit:  # the calendar repeats weekly: no fit within two weeks, none ever
                        raise ValueError(f"{ci.op_keys[o]}: its shares never fit the shifts next to the break")
                    a = shift_window(cal, a, hi - lo, cal.shift_end + cal.max_overtime)
                    noon = day_start(cal, day_index(cal, a)) + cal.break_earliest
                    if not (a < noon + cal.break_length and noon < a + hi - lo):
                        break
                    a = noon + cal.break_length
                need = max(need, a - (lo - s))
            if need == s:
                break
            s = need
        s += p
    return s


def horizon_bound(ci: CompiledInstance) -> int:
    """H: bound on (horizon - t) of every CP-SAT model of the instance. H_0 without workers or calendar. With both,
    H^cal: the model's horizon is the serial plan of its free operations from the next working morning after its
    fixed part (`serial_end`). The fixed part ends at most r_max + the longest operation + 4 days after t (a removal
    forced to the next working morning), that morning is at most 4 days later, and the serial plan of a subset is no
    longer than that of all operations from a morning of the same weekday (math/06_due-dates.md section 4; asserted
    in solve)."""
    if ci.calendar is None or not ci.worker_ids:
        return static_horizon(ci)
    cal, ops, serial = ci.calendar, list(ci.topo_order), 0
    for d in range(7):  # one start per weekday (the calendar repeats weekly)
        morning = day_start(cal, next(e for e in range(d, d + 8) if is_working_day(cal, e))) + cal.shift_start
        serial = max(serial, serial_end(ci, day_start(cal, d) - 1, ops) - morning)  # serial_end starts there too
    return max(ci.release) + max(_longest(ci, o) for o in ops) + 8 * DAY + serial


def _makespan_cpsat(model, _ci, _starts, ends, horizon, _cal=None):
    cmax = model.new_int_var(0, horizon, "Cmax")
    model.add_max_equality(cmax, ends)
    return cmax


MAKESPAN = Objective(
    name="makespan",
    evaluate=lambda _ci, schedule, _breaks=(): max(a.end for a in schedule),
    cpsat=_makespan_cpsat,
    spread=horizon_bound,  # every model's makespan lies in [t, horizon] with horizon - t <= H (math/06, section 4)
)


def _shift_windows_and_gaps(cal, until: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Regular shift windows [h^S, h^E) of the working days and the gaps between them (nights, weekends), from 0
    to the first window starting at or after `until`."""
    windows = []
    for d in range(day_index(cal, 0), day_index(cal, until) + 9):
        if is_working_day(cal, d):
            windows.append((day_start(cal, d) + cal.shift_start, day_start(cal, d) + cal.shift_end))
            if windows[-1][0] >= until:
                break
    gaps = [(0, windows[0][0])] if windows[0][0] > 0 else []
    gaps += [(we, ws) for (_, we), (ws, _) in zip(windows, windows[1:], strict=False)]
    return [(max(ws, 0), we) for ws, we in windows if we > 0], gaps


def _active_makespan(ci: CompiledInstance, schedule: Sequence[Assignment], _breaks=()) -> int:
    """C^act_max (math/04_workers.md (O6)): the activity clock at the end of the plan. It runs in the regular shift
    windows and, outside them, while an operation is in progress (machine, worker or unattended rest, user
    2026-11-10); per gap from its start to the last end of an operation started before the gap ends. Without a
    calendar the makespan."""
    cmax = max(a.end for a in schedule)
    if (cal := ci.calendar) is None:
        return cmax
    windows, gaps = _shift_windows_and_gaps(cal, cmax)
    shift = sum(max(0, min(cmax, we) - ws) for ws, we in windows)
    night = sum(max(0, max((min(a.end, ge) for a in schedule if a.start < ge), default=gs) - gs)
                for gs, ge in gaps if gs < cmax)
    return shift + night


def _active_makespan_cpsat(model, ci, starts, ends, horizon, _cal=None):
    """The same in CP-SAT, exact in both directions on every solution: per window max(0, min(C_max, end) - start);
    per gap and operation that can start before the gap ends a literal [S_o < gap end] and the term min(C_o, gap
    end) (else the gap start)."""
    cmax = _makespan_cpsat(model, ci, starts, ends, horizon)
    if (cal := ci.calendar) is None:
        return cmax
    windows, gaps = _shift_windows_and_gaps(cal, horizon)
    terms = []
    for ws, we in windows:
        part = model.new_int_var(0, we - ws, f"act_{ws}")
        until = model.new_int_var(min(0, ws), we, f"act_until_{ws}")
        model.add_min_equality(until, [cmax, we])
        model.add_max_equality(part, [until - ws, 0])
        terms.append(part)
    for gs, ge in gaps:
        if gs >= horizon:
            continue
        candidates = [gs]
        for o, (s, e) in enumerate(zip(starts, ends, strict=True)):
            if model.proto.variables[s.index].domain[0] >= ge:
                continue  # starts after the gap: no part in it
            started = model.new_bool_var(f"in_gap_{o}_{gs}")
            model.add(s <= ge - 1).only_enforce_if(started)
            model.add(s >= ge).only_enforce_if(started.Not())
            upto = model.new_int_var(0, ge, f"gap_end_{o}_{gs}")
            model.add_min_equality(upto, [e, ge])
            term = model.new_int_var(min(0, gs), ge, f"gap_term_{o}_{gs}")
            model.add(term == upto).only_enforce_if(started)
            model.add(term == gs).only_enforce_if(started.Not())
            candidates.append(term)
        last = model.new_int_var(gs, ge, f"gap_last_{gs}")
        model.add_max_equality(last, candidates)
        terms.append(last - gs)
    return sum(terms)


ACTIVE_MAKESPAN = Objective(
    name="active_makespan", evaluate=_active_makespan, cpsat=_active_makespan_cpsat,
    spread=horizon_bound,  # the clock runs at most as fast as real time: within [t, horizon] it moves at most H
)


def _order_ends(ci: CompiledInstance, schedule: Sequence[Assignment]) -> list[int]:
    """Completion C_k per order index: latest end of the operations serving k (incl. carrier and run operations)."""
    ends = [0] * len(ci.order_ids)
    for a in schedule:
        for k in ci.op_orders[ci.op_index[a.order_id, a.op_id]]:
            ends[k] = max(ends[k], a.end)
    return ends


def _due_orders(ci: CompiledInstance) -> list[int]:
    """Order indices with a due date; orders without one are not penalized."""
    if not (due := [k for k, d in enumerate(ci.due_date) if d is not None]):
        raise ValueError(f"instance {ci.name} has no due dates")
    return due


def _order_end_vars(model, ci, ends, horizon) -> list:
    """C_k per order index: maximum over the operations without successors (the others end earlier)."""
    sinks: list[list] = [[] for _ in ci.order_ids]
    for o in range(ci.n_ops):
        if not ci.successors[o]:
            for k in ci.op_orders[o]:
                sinks[k].append(ends[o])
    cks = []
    for k, sink_ends in enumerate(sinks):
        ck = model.new_int_var(0, horizon, f"C_order_{k}")
        model.add_max_equality(ck, sink_ends)
        cks.append(ck)
    return cks


def _tardiness_cpsat(model, ci, _starts, ends, horizon, _cal=None):
    cks = _order_end_vars(model, ci, ends, horizon)
    tardiness = []
    if cal := ci.calendar:  # T_k = number of missed cutoffs c >= d_k, one Boolean [C_k > c] each (math/04)
        for k in _due_orders(ci):
            for c in (c for c in cutoffs(cal, horizon) if c >= ci.due_date[k]):
                late = model.new_bool_var(f"late_{k}_{c}")
                model.add(cks[k] <= c).only_enforce_if(late.Not())  # both directions: value equals evaluate
                model.add(cks[k] >= c + 1).only_enforce_if(late)
                tardiness.append(late)
        return sum(tardiness)
    for k in _due_orders(ci):
        tk = model.new_int_var(0, horizon, f"T_{k}")
        model.add_max_equality(tk, [cks[k] - ci.due_date[k], 0])  # T_k = max(C_k - d_k, 0)
        tardiness.append(tk)
    return sum(tardiness)


def _tardy_orders_cpsat(model, ci, _starts, ends, horizon, _cal=None):
    cks = _order_end_vars(model, ci, ends, horizon)
    tardy = []
    for k in _due_orders(ci):
        uk = model.new_bool_var(f"U_{k}")
        # U_k = 1 iff C_k > d_k (both directions, so that the value agrees with evaluate on every solution)
        model.add(cks[k] <= ci.due_date[k]).only_enforce_if(uk.Not())
        model.add(cks[k] >= ci.due_date[k] + 1).only_enforce_if(uk)
        tardy.append(uk)
    return sum(tardy)


def _total_tardiness(ci: CompiledInstance, schedule: Sequence[Assignment], _breaks=()) -> int:
    """Minutes, or with a work calendar the number of missed shipping cutoffs (math/04_workers.md)."""
    ends = _order_ends(ci, schedule)
    if cal := ci.calendar:
        return sum(days_late(cal, ci.due_date[k], ends[k]) for k in _due_orders(ci))
    return sum(max(ends[k] - ci.due_date[k], 0) for k in _due_orders(ci))


def _tardiness_spread(ci: CompiledInstance) -> int:
    # each T_k moves at most as far as C_k, i.e. within a window of length H (math/06, section 4); a window of
    # that length holds at most H // 1440 + 1 cutoffs (one per day)
    if ci.calendar:
        return len(_due_orders(ci)) * (horizon_bound(ci) // DAY + 1)
    return len(_due_orders(ci)) * horizon_bound(ci)


def _tardy_orders(ci: CompiledInstance, schedule: Sequence[Assignment], _breaks=()) -> int:
    ends = _order_ends(ci, schedule)
    return sum(ends[k] > ci.due_date[k] for k in _due_orders(ci))


TOTAL_TARDINESS = Objective(
    name="total_tardiness", evaluate=_total_tardiness, cpsat=_tardiness_cpsat, spread=_tardiness_spread,
)
TARDY_ORDERS = Objective(
    name="tardy_orders", evaluate=_tardy_orders, cpsat=_tardy_orders_cpsat,
    spread=lambda ci: len(_due_orders(ci)),
)


# --- worker objective (math/04_workers.md section 4, spec §5): tardiness and overtime, breaks, makespan ----------

def overtime(ci: CompiledInstance, schedule: Sequence[Assignment]) -> int:
    """Sum over workers and days of the minutes after the shift end of the worker's last share that day (M7)."""
    if (cal := ci.calendar) is None or not ci.worker_ids:
        return 0
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in schedule}
    last: dict[tuple[str, int], int] = {}
    for w, intervals in worker_intervals(ci, by_op).items():
        for s, e, _ in intervals:
            last[w, d] = max(last.get((w, d := day_index(cal, s)), 0), e)
    return sum(max(0, e - day_start(cal, d) - cal.shift_end) for (_, d), e in last.items())


def _days(ci: CompiledInstance) -> int:
    """Number of days a model can span: H // 1440 + 2 (the snapshot's day and the one after the horizon)."""
    return horizon_bound(ci) // DAY + 2


def tardiness_and_overtime(theta_o: Fraction | int) -> Objective:
    """Level 1: sum_k T_k + theta_O * sum_{z,nu} ot_{z,nu}, theta_O >= 0 days of tardiness per minute of overtime
    (a required parameter, varied in experiments). Scaled by the denominator of theta_O to stay an integer:
    den * sum T + num * sum ot (the same order)."""
    theta = Fraction(theta_o)
    if theta < 0:
        raise ValueError(f"theta_O must be >= 0, got {theta}")
    num, den = theta.numerator, theta.denominator

    def cpsat(model, ci, starts, ends, horizon, cal=None):
        ot = sum(cal.overtime) + cal.past_overtime if cal is not None else 0
        return den * _tardiness_cpsat(model, ci, starts, ends, horizon) + num * ot

    def spread(ci: CompiledInstance) -> int:
        ot = len(ci.worker_ids) * _days(ci) * ci.calendar.max_overtime if ci.calendar and ci.worker_ids else 0
        return den * _tardiness_spread(ci) + num * ot

    return Objective(
        name=f"tardiness+{theta}*overtime",
        evaluate=lambda ci, schedule, _breaks=(): den * _total_tardiness(ci, schedule) + num * overtime(ci, schedule),
        cpsat=cpsat, spread=spread,
    )


def _break_penalty(ci: CompiledInstance, _schedule: Sequence[Assignment], breaks: Sequence[Break] = ()) -> int:
    """Level 2: postponement (minutes after the earliest break start) plus spread (latest minus earliest break per
    day), equal weights (spec §5), as the metrics M7 do."""
    if (cal := ci.calendar) is None:
        return 0
    per_day: dict[int, list[int]] = defaultdict(list)
    for b in breaks:
        per_day[day_index(cal, b.start)].append(b.start)
    return (sum(max(0, minute_of_day(cal, b.start) - cal.break_earliest) for b in breaks)
            + sum(max(s) - min(s) for s in per_day.values()))


def _break_penalty_cpsat(model, ci, _starts, _ends, _horizon, cal=None):
    if cal is None or not cal.breaks:
        return 0
    calendar, per_day, terms = ci.calendar, defaultdict(list), []
    for d, b in cal.breaks:
        earliest = day_start(calendar, d) + calendar.break_earliest
        # a variable break starts in the window (>= earliest); a constant one (taken, forced) may be anywhere
        terms.append(max(0, b - earliest) if isinstance(b, int) else b - earliest)
        per_day[d].append(b)
    for d, starts in per_day.items():
        if len(starts) > 1:  # breaks may lie after the horizon (the model's last day): bounds of the day itself
            ds = day_start(calendar, d)
            hi, lo = model.new_int_var(ds, ds + DAY, f"br_max_{d}"), model.new_int_var(ds, ds + DAY, f"br_min_{d}")
            model.add_max_equality(hi, starts)
            model.add_min_equality(lo, starts)
            terms.append(hi - lo)
    return sum(terms)


BREAK_PENALTY = Objective(
    name="break_penalty", evaluate=_break_penalty, cpsat=_break_penalty_cpsat,
    # per day: each variable break moves within the 60-minute window, and so does the spread of the day
    spread=lambda ci: _days(ci) * (len(ci.worker_ids) + 1) * (ci.calendar.break_latest - ci.calendar.break_earliest)
    if ci.calendar else 0,
)


OVERTIME = Objective(
    name="overtime", evaluate=lambda ci, schedule, _breaks=(): overtime(ci, schedule),
    # the overtime variables are lower bounds, exact where this level minimizes them (math/12 section 7b)
    cpsat=lambda _m, _ci, _s, _e, _h, cal=None: sum(cal.overtime) + cal.past_overtime if cal is not None else 0,
    spread=lambda ci: len(ci.worker_ids) * _days(ci) * ci.calendar.max_overtime if ci.calendar else 0,
)


def _shipping_cutoff(cal, due: int, end: int) -> int:
    """d^ship_k: the cutoff the order ships with, the first cutoff at or after its end, not before its due date."""
    return max(due, next_cutoff(cal, end))


def cutoff_slack(buffer: int) -> Objective:
    """Shortfall of the buffer before the shipping cutoff (math/04_workers.md (O7), user 2026-11-11):
    sum_k sh_k, sh_k = max(0, buffer - (d^ship_k - C_k)), for the orders with a due date. An order that ends less
    than `buffer` minutes before its cutoff counts the missing minutes, on time or late (then before the cutoff it
    ships with). Own modeling after the slack and buffer ideas of Davenport et al. (2001) and Klimek & Lebkowski
    (2009)."""
    if not 0 < buffer < DAY:  # the CP-SAT form relies on cutoffs at least a day apart
        raise ValueError(f"buffer must lie in (0, {DAY}), got {buffer}")

    def evaluate(ci: CompiledInstance, schedule: Sequence[Assignment], _breaks=()) -> int:
        if (cal := ci.calendar) is None:
            raise ValueError("cutoff_slack needs a calendar")
        ends = _order_ends(ci, schedule)
        return sum(max(0, buffer - (_shipping_cutoff(cal, ci.due_date[k], ends[k]) - ends[k]))
                   for k in _due_orders(ci))

    def cpsat(model, ci, _starts, ends, horizon, _cal=None):
        # per cutoff c >= d_k a literal [C_k > c]; the term C_k - c + buffer counts for the cutoffs not missed: the
        # first of them is d^ship_k, the later ones lie a day or more further and give negative terms
        cal, cks, terms = ci.calendar, _order_end_vars(model, ci, ends, horizon), []
        for k in _due_orders(ci):
            parts = [0]
            for c in sorted({c for c in [*cutoffs(cal, horizon), next_cutoff(cal, horizon)] if c >= ci.due_date[k]}):
                late = model.new_bool_var(f"slack_late_{k}_{c}")
                model.add(cks[k] <= c).only_enforce_if(late.Not())
                model.add(cks[k] >= c + 1).only_enforce_if(late)
                part = model.new_int_var(buffer - c, buffer, f"slack_term_{k}_{c}")  # C_k >= 0
                model.add(part == cks[k] - c + buffer).only_enforce_if(late.Not())
                model.add(part == 0).only_enforce_if(late)
                parts.append(part)
            sh = model.new_int_var(0, buffer, f"slack_sh_{k}")
            model.add_max_equality(sh, parts)  # both directions: the value equals evaluate on every solution
            terms.append(sh)
        return sum(terms)

    return Objective(name=f"cutoff_slack({buffer})", evaluate=evaluate, cpsat=cpsat,
                     spread=lambda ci: len(_due_orders(ci)) * buffer)


def worker_objective_with_slack(buffer: int) -> Objective:
    """Tardiness strictly first, then the cutoff buffer, then overtime, breaks and the activity clock (user
    2026-11-11): five levels, solved one after another by CP-SAT."""
    return lexicographic(TOTAL_TARDINESS, cutoff_slack(buffer), OVERTIME, BREAK_PENALTY, ACTIVE_MAKESPAN)


def worker_objective(theta_o: Fraction | int) -> Objective:
    """The lexicographic objective of the worker model (spec §5): level 1 tardiness and overtime, level 2 break
    penalty, level 3 the activity clock at the plan's end (`ACTIVE_MAKESPAN`). Level 0 (oven overstay) is a
    metric only: with C7^o it is the same for every plan (phase 4 plan, decision 3)."""
    return lexicographic(tardiness_and_overtime(theta_o), BREAK_PENALTY, ACTIVE_MAKESPAN)


def level_weights(ci: CompiledInstance, levels: Sequence[Objective]) -> list[int]:
    """theta_i of (O3): theta_n = 1, theta_i = 1 + sum_{j > i} theta_j spr(f_j) (the weights `lexicographic` uses)."""
    weights, below = [1], 0
    for i in range(len(levels) - 1, 0, -1):
        below += weights[0] * levels[i].spread(ci)
        weights.insert(0, below + 1)
    return weights


def lexicographic(*objectives: Objective) -> Objective:
    """Exact lexicographic order as one weighted sum: each level weighs one more than the spread of all lower ones,
    so one unit of a higher level outweighs any change below it."""
    *higher, combined = objectives
    for primary in reversed(higher):
        combined = _over(primary, combined)
    return combined


def _over(primary: Objective, secondary: Objective) -> Objective:
    def weight(ci: CompiledInstance) -> int:
        return secondary.spread(ci) + 1

    return Objective(
        name=f"{primary.name}>{secondary.name}",
        evaluate=lambda ci, s, breaks=(): (weight(ci) * primary.evaluate(ci, s, breaks)
                                           + secondary.evaluate(ci, s, breaks)),
        cpsat=lambda model, ci, starts, ends, horizon, cal=None: (
            weight(ci) * primary.cpsat(model, ci, starts, ends, horizon, cal)
            + secondary.cpsat(model, ci, starts, ends, horizon, cal)
        ),
        spread=lambda ci: weight(ci) * primary.spread(ci) + secondary.spread(ci),
        levels=(primary.levels or (primary,)) + (secondary.levels or (secondary,)),
    )
