"""Objectives as pairs: evaluation of a finished schedule and the same expression for CP-SAT.

Both halves must agree on every CP-SAT solution (tested). See math/01_basic-fjsp.md, section 4, and
math/06_due-dates.md, section 4 (due-date objectives, lexicographic combination).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from simulation.calendar import DAY, cutoffs, days_late
from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment


@dataclass(frozen=True, slots=True)
class Objective:
    name: str
    # evaluate(ci, schedule) -> value to minimize
    evaluate: Callable[[CompiledInstance, Sequence[Assignment]], int]
    # cpsat(model, ci, starts, ends, horizon) -> expression to minimize
    cpsat: Callable[
        [cp_model.CpModel, CompiledInstance, Sequence[cp_model.IntVar], Sequence[cp_model.IntVar], int],
        cp_model.LinearExprT,
    ]
    # spread(ci) >= difference of the values of any two solutions of one CP-SAT model (static or from a snapshot);
    # the weight of a higher level in `lexicographic`
    spread: Callable[[CompiledInstance], int]


def static_horizon(ci: CompiledInstance) -> int:
    """H_0: latest release plus every operation on its slowest machine (the horizon of the static model)."""
    return max(ci.release) + sum(
        max(p for _, p in options) if options else ci.fixed_duration[o] for o, options in enumerate(ci.options)
    )


def _makespan_cpsat(model, _ci, _starts, ends, horizon):
    cmax = model.new_int_var(0, horizon, "Cmax")
    model.add_max_equality(cmax, ends)
    return cmax


MAKESPAN = Objective(
    name="makespan",
    evaluate=lambda _ci, schedule: max(a.end for a in schedule),
    cpsat=_makespan_cpsat,
    spread=static_horizon,  # every model's makespan lies in [t, H] with H - t <= H_0 (math/06, section 4)
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


def _tardiness_cpsat(model, ci, _starts, ends, horizon):
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


def _tardy_orders_cpsat(model, ci, _starts, ends, horizon):
    cks = _order_end_vars(model, ci, ends, horizon)
    tardy = []
    for k in _due_orders(ci):
        uk = model.new_bool_var(f"U_{k}")
        # U_k = 1 iff C_k > d_k (both directions, so that the value agrees with evaluate on every solution)
        model.add(cks[k] <= ci.due_date[k]).only_enforce_if(uk.Not())
        model.add(cks[k] >= ci.due_date[k] + 1).only_enforce_if(uk)
        tardy.append(uk)
    return sum(tardy)


def _total_tardiness(ci: CompiledInstance, schedule: Sequence[Assignment]) -> int:
    """Minutes, or with a work calendar the number of missed shipping cutoffs (math/04_workers.md)."""
    ends = _order_ends(ci, schedule)
    if cal := ci.calendar:
        return sum(days_late(cal, ci.due_date[k], ends[k]) for k in _due_orders(ci))
    return sum(max(ends[k] - ci.due_date[k], 0) for k in _due_orders(ci))


def _tardiness_spread(ci: CompiledInstance) -> int:
    # each T_k moves at most as far as C_k, i.e. within a window of length H_0 (math/06, section 4); a window of
    # that length holds at most H_0 // 1440 + 1 cutoffs (one per day)
    if ci.calendar:
        return len(_due_orders(ci)) * (static_horizon(ci) // DAY + 1)
    return len(_due_orders(ci)) * static_horizon(ci)


def _tardy_orders(ci: CompiledInstance, schedule: Sequence[Assignment]) -> int:
    ends = _order_ends(ci, schedule)
    return sum(ends[k] > ci.due_date[k] for k in _due_orders(ci))


TOTAL_TARDINESS = Objective(
    name="total_tardiness", evaluate=_total_tardiness, cpsat=_tardiness_cpsat, spread=_tardiness_spread,
)
TARDY_ORDERS = Objective(
    name="tardy_orders", evaluate=_tardy_orders, cpsat=_tardy_orders_cpsat,
    spread=lambda ci: len(_due_orders(ci)),
)


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
        evaluate=lambda ci, s: weight(ci) * primary.evaluate(ci, s) + secondary.evaluate(ci, s),
        cpsat=lambda model, ci, starts, ends, horizon: (
            weight(ci) * primary.cpsat(model, ci, starts, ends, horizon)
            + secondary.cpsat(model, ci, starts, ends, horizon)
        ),
        spread=lambda ci: weight(ci) * primary.spread(ci) + secondary.spread(ci),
    )
