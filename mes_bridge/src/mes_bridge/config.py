"""The scheduler's configuration (spec decision 9): one Pydantic model, read from a JSON file in v1; later stored in
the MES and sent with the problem. Unknown keys fail loudly.

    {"solver": {"sequencing": "spt", "assignment": "ect"},
     "policy": {"max_shift": 60, "period": 480},
     "safety_poll_minutes": 5}

The solver is a dispatching rule pair of the thesis (`simulation.planners.dispatching`); CP-SAT and the GA join in
task 5.1, the frozen horizon in 5.2.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator
from simulation.control.rescheduling import Planner, ReschedulingPolicy
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_planner


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SolverConfig(_Model):
    sequencing: str = "spt"
    assignment: str | None = None  # None: the dispatcher's default

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

    def planner(self) -> Planner:
        return dispatch_planner(SEQUENCING_RULES[self.sequencing], ASSIGNMENT_RULES.get(self.assignment or ""))


class PolicyConfig(_Model):
    """The thresholds of the thesis rescheduling policy (math/05 §3), minutes; None: that trigger is off."""

    max_makespan_change: PositiveInt | None = None
    max_shift: PositiveInt | None = None
    max_mean_shift: float | None = Field(default=None, gt=0)
    change_budget: int | None = Field(default=None, ge=0)
    period: PositiveInt | None = None  # safety net: a complete rescheduling at least this often
    early_finish: PositiveInt | None = None


class SchedulerConfig(_Model):
    solver: SolverConfig = SolverConfig()
    policy: PolicyConfig = PolicyConfig()
    safety_poll_minutes: PositiveInt = 5  # decision 14: a step without any event

    def rescheduling_policy(self) -> ReschedulingPolicy:
        return ReschedulingPolicy(planner=self.solver.planner(), **self.policy.model_dump())

    @classmethod
    def load(cls, path: str | Path | None) -> "SchedulerConfig":
        """The file's configuration, or the defaults without a file."""
        return cls() if path is None else cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
