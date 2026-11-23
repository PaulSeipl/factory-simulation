"""Hand-written models of the MES endpoints the bridge uses (spec decision 15).

`GET /planning/problem` (what the scheduler plans from) and `PUT` / `GET /planning/schedule` (what it
publishes). Names match the MES schemas, so `tests/test_contract.py` can compare them field by field
with the checked-in copy `tests/data/openapi.json`. `extra="forbid"`: a field the MES adds fails loudly
until the copy and these models are updated on purpose. MES enums are plain strings here; the MES
validates them.
"""

from datetime import date, datetime, time
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- GET /planning/problem ---


class ProblemOrderOut(_Model):
    id: UUID
    short_id: str
    due_date: date | None
    arrival: datetime | None  # DATA_PREP_SECONDARY finished (decision 6)


class ProblemPartOut(_Model):
    id: UUID
    order_id: UUID
    part_type: str  # PRIMARY | SECONDARY
    units: int  # tooth links (secondary: telescopes), at least 1
    carrier: str | None  # ProblemCarrierOut.key
    mill_job_id: UUID | None  # once a data prep formed it: a secondary part's plate mill job, a primary part's blank


class ProblemJobOut(_Model):
    id: UUID
    kind: str  # AM | MILL
    equipment_id: UUID | None
    estimated_duration_minutes: int | None  # entered by a worker; the run time once set (decision 8)
    build_plate_set_id: UUID | None


class ProblemCarrierOut(_Model):
    key: str  # `<am job id>:<quadrant>`
    am_job_id: UUID
    quadrant: str
    part_ids: list[UUID]
    mill_job_id: UUID | None


class ProblemOperationOut(_Model):
    key: str  # order:<id>:<task> | job:<id>:<task> | carrier:<am job>:<quadrant>:<task>
    task_type: str
    lane: str
    order_ids: list[UUID]
    job_id: UUID | None
    predecessors: list[str]
    attended_minutes: float
    unattended_minutes: float
    machine_options: list[UUID]
    delay_minutes: float
    done: bool


class ProblemParamsOut(_Model):
    task_type: str | None
    job_kind: str | None
    part_type: str | None
    unit_kind: str  # PART | PART_COUNT | PLATE | ORDER
    base_minutes_attended: float
    per_unit_minutes_attended: float
    base_minutes_unattended: float
    per_unit_minutes_unattended: float
    max_batch_size: int | None
    resource: str | None
    has_handoff: bool


class ProblemWorkerOut(_Model):
    id: UUID
    daily_minutes: int
    workdays: list[int]  # ISO weekdays, 1 = Monday


class ProblemMachineOut(_Model):
    id: UUID
    equipment_type: str
    name: str
    status: str | None


class ProblemAssignmentOut(_Model):
    key: str
    worker_id: UUID
    equipment_id: UUID | None
    tie_break: int | None


class ProblemCalendarOut(_Model):
    day_start: time
    time_zone: str


class ProblemInstanceOut(_Model):
    orders: list[ProblemOrderOut]
    parts: list[ProblemPartOut]
    jobs: list[ProblemJobOut]
    carriers: list[ProblemCarrierOut]
    operations: list[ProblemOperationOut]
    params: list[ProblemParamsOut]
    workers: list[ProblemWorkerOut]
    machines: list[ProblemMachineOut]
    assignments: list[ProblemAssignmentOut]
    calendar: ProblemCalendarOut


class ProblemTaskOut(_Model):
    key: str
    task_id: UUID
    worker_id: UUID | None
    equipment_id: UUID | None
    started_at: datetime
    handoff_at: datetime | None
    finished_at: datetime | None
    expected_attended_end: datetime | None
    expected_end: datetime | None


class ProblemSnapshotOut(_Model):
    tasks: list[ProblemTaskOut]


class ProblemOut(_Model):
    as_of: datetime
    instance: ProblemInstanceOut
    snapshot: ProblemSnapshotOut


# --- PUT / GET /planning/schedule ---


class ScheduleStepIn(_Model):
    key: str
    worker_id: UUID | None = None
    equipment_id: UUID | None = None
    start: AwareDatetime
    attended_end: AwareDatetime
    end: AwareDatetime


class ScheduleBreakIn(_Model):
    worker_id: UUID
    start: AwareDatetime
    end: AwareDatetime


class ScheduleIn(_Model):
    variant: str  # BOUND | FREE
    snapshot_as_of: AwareDatetime
    solved_at: AwareDatetime
    steps: list[ScheduleStepIn]
    breaks: list[ScheduleBreakIn] = []


class ScheduleStepOut(_Model):
    key: str
    worker_id: UUID | None
    equipment_id: UUID | None
    start: datetime
    attended_end: datetime
    end: datetime


class ScheduleBreakOut(_Model):
    worker_id: UUID
    start: datetime
    end: datetime


class ScheduleOut(_Model):
    id: UUID
    variant: str
    snapshot_as_of: datetime
    solved_at: datetime
    created_at: datetime | None  # nullable in the MES schema (TimestampMixin)
    steps: list[ScheduleStepOut]
    breaks: list[ScheduleBreakOut]
