from pydantic import BaseModel, ConfigDict, NonNegativeInt, model_validator


class Assignment(BaseModel):
    """One scheduled operation. Structural checks only; feasibility is the checker's job."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    op_id: str
    machine: str | None  # None: operation without machine (math/04_workers.md); required, so never omitted by accident
    start: NonNegativeInt
    end: int
    workers: tuple[str, ...] = ()  # one worker per share of the operation, in the order of CompiledInstance.shares
    # realized share lengths (set by the DES, whose shares scale with the disturbance); empty: the planned lengths
    share_lengths: tuple[int, ...] = ()

    @model_validator(mode="after")
    def check_interval(self):
        if self.end <= self.start:
            raise ValueError(
                f"assignment {self.order_id}/{self.op_id}: "
                f"end ({self.end}) must be > start ({self.start})"
            )
        return self


class Break(BaseModel):
    """Lunch break of a worker; its length comes from the instance's calendar (math/04_workers.md)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    worker: str
    start: NonNegativeInt


class Schedule(BaseModel):
    """Common output format of all planners."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    assignments: tuple[Assignment, ...]
    breaks: tuple[Break, ...] = ()  # planned breaks; empty for instances without workers
