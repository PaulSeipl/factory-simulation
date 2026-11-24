"""The scheduler's configuration (spec decision 9): one Pydantic model, read from a JSON file in v1; later stored in
the MES and sent with the problem. Unknown keys fail loudly.

    {"solver": {"kind": "rule", "sequencing": "edd"},
     "thorough": {"kind": "cpsat", "time_limit": 60, "objective": "worker"},
     "policy": {"max_shift": 60, "period": 480},
     "safety_poll_minutes": 5}

Two solver profiles (task 7.2): `solver` plans every automatic step and must be fast; `thorough` plans only on a
user's request (a proposal) and may take minutes. Measured on the five-order demo problem (125 operations, 3 workers,
2026-11-24): the EDD rule instantly; CP-SAT with the worker objective found no plan in 10 s and took 92 s at
`time_limit: 30` and 183 s at 60, since the limit holds per stage of its lexicographic objective, not per solve.
A thorough solve may take up to 30 min (user, 2026-11-24): the worker objective has up to five levels, so
`time_limit: 360` for CP-SAT with it (`max_solve_seconds`, which the planners see as "ready by"). The demo keeps 60.

The solver is one of the thesis planners (task 5.1): a dispatching rule pair (`kind: "rule"`, the default,
`simulation.planners.dispatching`), CP-SAT (`"cpsat"`, `planners.cpsat.cpsat_planner`) or the GA (`"ga"`,
`planners.ga.ga_planner`). CP-SAT and the GA take the objective (`"worker"`: the thesis worker objective with the
cutoff buffer, math/04 (O7), as in `simulation.experiment`; `"makespan"`) and a wall-clock time limit; the
frozen horizon follows in 5.2.
"""

import logging
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveFloat, PositiveInt, field_validator
from simulation.control.rescheduling import Planner, ReschedulingPolicy
from simulation.model.compiled import CompiledInstance
from simulation.objectives import (
    ACTIVE_MAKESPAN,
    BREAK_PENALTY,
    MAKESPAN,
    OVERTIME,
    Objective,
    lexicographic,
    worker_objective_with_slack,
)
from simulation.planners.cpsat import cpsat_planner
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_planner
from simulation.planners.ga import GaParams, ga_planner

from mes_bridge.state import with_frozen_horizon


log = logging.getLogger(__name__)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SolverConfig(_Model):
    kind: Literal["rule", "cpsat", "ga"] = "rule"
    # kind "rule"
    sequencing: str = "spt"
    assignment: str | None = None  # None: the dispatcher's default
    # kinds "cpsat" and "ga"
    objective: Literal["worker", "makespan"] = "worker"
    buffer: PositiveInt = Field(default=60, lt=1440)  # minutes before the shipping cutoff (math/04 (O7))
    # seconds of wall clock; CP-SAT with the worker objective spends it per stage of the lexicographic objective, so a
    # solve takes several times this (measured 2026-11-24: 30 -> 92 s, 60 -> 183 s on 125 operations)
    time_limit: PositiveFloat = 10.0
    deterministic_time: PositiveFloat | None = None  # CP-SAT only: a work-based limit, same result under any load
    seed: NonNegativeInt = 0

    @field_validator("sequencing")
    @classmethod
    def _known_sequencing(cls, v: str) -> str:
        if v not in SEQUENCING_RULES:
            raise ValueError(f"unknown sequencing rule {v!r}, known: {sorted(SEQUENCING_RULES)}")
        return v

    @field_validator("assignment")
    @classmethod
    def _known_assignment(cls, v: str | None) -> str | None:
        if v is not None and v not in ASSIGNMENT_RULES:
            raise ValueError(f"unknown assignment rule {v!r}, known: {sorted(ASSIGNMENT_RULES)}")
        return v

    def objective_for(self, ci: CompiledInstance) -> Objective:
        """The configured objective. Shortcut: the worker objective's first two levels (tardiness, cutoff buffer)
        need a due date; while no order has one (the MES due date is optional), the remaining levels."""
        if self.objective == "makespan":
            return MAKESPAN
        if any(d is not None for d in ci.due_date):
            return worker_objective_with_slack(self.buffer)
        return lexicographic(OVERTIME, BREAK_PENALTY, ACTIVE_MAKESPAN)

    @property
    def horizon_minutes(self) -> int:
        """The frozen horizon (decision 19): the solve's time limit in whole minutes, rounded up; 0 for a rule."""
        return 0 if self.kind == "rule" else math.ceil(self.time_limit / 60)

    @property
    def max_solve_seconds(self) -> float:
        """How long a solve takes at most, for the planners' "ready by" (task 7.5a): CP-SAT spends its limit per level
        of a lexicographic objective (the worker objective has up to five), the GA once; a rule is instant."""
        if self.kind == "rule":
            return 0.0
        levels = 5 if self.kind == "cpsat" and self.objective == "worker" else 1
        return self.time_limit * levels

    def rule_planner(self) -> Planner:
        return dispatch_planner(SEQUENCING_RULES[self.sequencing], ASSIGNMENT_RULES.get(self.assignment or ""))

    def planner(self) -> Planner:
        """The configured planner. CP-SAT and the GA fall back to the rule (`sequencing`, `assignment`) when they
        return no plan for the operations (no solution within the time limit, an infeasible model); `planner.last`
        then says why (`fallback`), and is the solver's own report otherwise. Both plan from the snapshot with the
        frozen horizon (decision 19, `state.with_frozen_horizon`): what the current plan starts within the solve's
        time limit is kept, since it may have started by the time the plan is published."""
        if self.kind == "rule":
            return self.rule_planner()

        def planner(ci, snapshot, current):
            snapshot = with_frozen_horizon(snapshot, current, self.horizon_minutes)
            objective = self.objective_for(ci)
            if self.kind == "cpsat":
                # one solver thread, so a seed reproduces a plan (as the thesis experiments)
                inner = cpsat_planner(
                    self.time_limit, 1, self.seed, objective=objective, deterministic_time=self.deterministic_time
                )
            else:
                inner = ga_planner(objective, GaParams(time_limit=self.time_limit, seed=self.seed))
            try:
                plan = inner(ci, snapshot, current)
                reason = None if len(plan.assignments) == ci.n_ops else f"{len(plan.assignments)} of {ci.n_ops} planned"
            except (RuntimeError, ValueError) as e:  # cpsat_planner raises without a solution
                plan, reason = None, str(e)
            planner.last = getattr(inner, "last", None)  # the solver's report of this call (status, limits)
            if reason is None:
                return plan
            log.warning("%s found no plan (%s): the %s rule plans instead", self.kind, reason, self.sequencing)
            planner.last = {**(planner.last or {}), "fallback": reason}
            return self.rule_planner()(ci, snapshot, current)

        planner.__qualname__ = f"{self.kind}_planner"
        return planner


class PolicyConfig(_Model):
    """The thresholds of the thesis rescheduling policy (math/05 §3), minutes; None: that trigger is off."""

    max_makespan_change: PositiveInt | None = None
    max_shift: PositiveInt | None = None
    max_mean_shift: float | None = Field(default=None, gt=0)
    change_budget: int | None = Field(default=None, ge=0)
    period: PositiveInt | None = None  # safety net: a complete rescheduling at least this often
    early_finish: PositiveInt | None = None


class SchedulerConfig(_Model):
    # Two profiles (slice 7, task 7.2; user 2026-11-24: a long solve is never automatic):
    # `solver` plans every automatic step (an event, an arrival, the poll, the periodic deadline), so it must be fast;
    # `thorough` only plans what a user requests (a proposal, task 7.3) and may take minutes; None: `solver` does both.
    solver: SolverConfig = SolverConfig()
    thorough: SolverConfig | None = None
    # decision 4: both by default; if two solves per step are too slow, FREE can be left out
    variants: tuple[Literal["BOUND", "FREE"], ...] = Field(default=("BOUND", "FREE"), min_length=1)

    @field_validator("variants")
    @classmethod
    def _unique(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError(f"a variant twice: {list(v)}")
        return v

    policy: PolicyConfig = PolicyConfig()
    safety_poll_minutes: PositiveInt = 5  # decision 14: a step without any event

    def rescheduling_policy(self) -> ReschedulingPolicy:
        """The automatic path: always the fast profile (`solver`), never `thorough`."""
        return ReschedulingPolicy(planner=self.solver.planner(), **self.policy.model_dump())

    def thorough_planner(self) -> Planner:
        """The planner for a requested proposal: `thorough`, else `solver`."""
        return (self.thorough or self.solver).planner()

    @classmethod
    def load(cls, path: str | Path | None) -> "SchedulerConfig":
        """The file's configuration, or the defaults without a file."""
        return cls() if path is None else cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
