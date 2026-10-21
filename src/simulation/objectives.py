"""Objectives as pairs: evaluation of a finished schedule and the same expression for CP-SAT.

Both halves must agree on every CP-SAT solution (tested). See math/01_basic-fjsp.md, section 4.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

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


def _makespan_cpsat(model, _ci, _starts, ends, horizon):
    cmax = model.new_int_var(0, horizon, "Cmax")
    model.add_max_equality(cmax, ends)
    return cmax


MAKESPAN = Objective(
    name="makespan",
    evaluate=lambda _ci, schedule: max(a.end for a in schedule),
    cpsat=_makespan_cpsat,
)
