from pydantic import BaseModel, ConfigDict, NonNegativeInt, model_validator


class Assignment(BaseModel):
    """One scheduled operation. Structural checks only; feasibility is the checker's job."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    machine: str
    start: NonNegativeInt
    end: int

    @model_validator(mode="after")
    def check_interval(self):
        if self.end <= self.start:
            raise ValueError(
                f"assignment {self.order_id}/{self.op_id}: "
                f"end ({self.end}) must be > start ({self.start})"
            )
        return self


class Schedule(BaseModel):
    """Common output format of all planners."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    assignments: tuple[Assignment, ...]
