# Workers, phase 1: calendar, day tardiness, worker format and checker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instances can carry a work calendar, workers and worker shares; tardiness counts missed shipping cutoffs;
the independent checker validates worker assignments, shifts and breaks.

**Architecture:** Spec steps 1 and 2 (`§9`). Pydantic models in `model/instance.py` and `model/schedule.py` get the
new fields (schema 0.6); calendar arithmetic lives in a new pure module `simulation/calendar.py` used by objectives,
due dates and the checker; `CompiledInstance` gets index-based worker data. DES, rules, CP-SAT and rescheduling
reject instances with workers (`NotImplementedError`) until phases 2–4; each phase gets its own plan after the
user approved the previous one (working style, `CLAUDE.md`).

**Tech Stack:** Python 3.12, Pydantic v2, OR-Tools CP-SAT (objective halves only), pytest, `uv run`.

**Spec:** `docs/superpowers/specs/2026-11-05-workers-shifts-design.md`

## Global Constraints

- Time is integer minutes; a calendar is only allowed with `time_unit == "min"`.
- Calendar defaults (spec §3.3, user): shift 08:00–17:30 (`480`–`1050` minute of day), break 60 min starting in
  `[720, 780]`, overtime at most 120 min (shift end at most `1170`), working days Monday–Friday, cutoff 12:00
  (`720`), `t = 0` is Monday 08:00 (`origin = 480` minute of week).
- Instances without `calendar` and without `workers` behave exactly as today (all existing tests stay green
  unchanged, apart from the schema-version string).
- Pydantic models `frozen=True, extra="forbid"`; no Pydantic in `CompiledInstance`.
- One negative test per new validation rule; checker returns `Violation` lists, new constraints numbered C11–C14.
- `math/` updated in the same task as the model change; protocol entry at the end of each task (`math/protocol.md`).
- Commits only when the user says so (`CLAUDE.md` harness rule); the commit steps below are "on approval".

## Review Focus

1. Due date exactly on a cutoff and completion exactly at a cutoff minute: `C_k = D_k` is on time, `C_k = D_k + 1`
   is 1 day late (Task 2 test `test_boundary_minutes`).
2. Friday cutoff missed, shipped Monday before 12:00: 1 day, not 3 (Task 2 `test_weekend_counts_one_day`).
3. A worker share crossing midnight or the break by one minute is a violation, ending exactly at the break start is
   not (Task 6 `test_share_touching_break_is_allowed`).
4. Batched oven run: the three member operations carry one prefix and one suffix; one worker on the run is not a
   double booking (Task 6 `test_batch_shares_count_once`).
5. Old schedules without `workers` on instances without workers stay feasible (Task 5
   `test_old_schedule_still_feasible`).

---

### Task 1: Calendar model and calendar arithmetic

**Files:**
- Create: `src/simulation/calendar.py`
- Modify: `src/simulation/model/instance.py` (class `Calendar`, field `Instance.calendar`, validators, `schema_version`
  → `"0.6"`)
- Modify: every `"0.5"` literal: `src/simulation/{generator,carrier_generator}.py`, `io/brandimarte_loader.py`,
  `viz.py`, `tests/test_{carrier_kinds,carrier_runs,compile,dispatching,instance_model,objectives}.py`,
  `data/instances/*.json`; regenerate `schemas/instance-0.6.json` with `uv run python tests/test_schema.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- Produces (Pydantic, `instance.py`):
  `class Calendar(BaseModel)`: `origin: int = 480` (minute of week at t = 0, Monday 00:00 = 0), `shift_start: int = 480`,
  `shift_end: int = 1050`, `break_earliest: int = 720`, `break_latest: int = 780`, `break_length: PositiveInt = 60`,
  `max_overtime: NonNegativeInt = 120`, `cutoff: int = 720`, `working_days: tuple[int, ...] = (0, 1, 2, 3, 4)`.
  `Instance.calendar: Calendar | None = None`.
- Produces (`calendar.py`, plain functions on the Pydantic `Calendar`; compiled copy in Task 4):
  - `minute_of_day(cal, t: int) -> int`, `day_index(cal, t: int) -> int` (days since t = 0's day, 0-based),
    `is_working_day(cal, day: int) -> bool`
  - `day_start(cal, day: int) -> int` (t of 00:00 of that day; may be negative for day 0)
  - `cutoffs(cal, until: int) -> list[int]` (all cutoff times `0 <= c <= until` on working days, ascending)
  - `next_cutoff(cal, t: int) -> int` (smallest cutoff `>= t`)
  - `days_late(cal, due: int, end: int) -> int` = `|{c ∈ cutoffs : due <= c < end}|`

- [ ] **Step 1: Write failing tests** in `tests/test_calendar.py`:
  - `test_origin_monday_0800`: `minute_of_day(Calendar(), 0) == 480`, `day_index(Calendar(), 0) == 0`,
    `day_index(Calendar(), 960) == 1` (Tue 00:00 is t = 960).
  - `test_cutoffs_skip_weekend`: `cutoffs(Calendar(), 8*1440)` == `[240 + d*1440 for d in (0,1,2,3,4,7)]`
    (Mon 12:00 is t = 240; next Monday is day 7).
  - `test_next_cutoff`: `next_cutoff(cal, 240) == 240`, `next_cutoff(cal, 241) == 1680`; from Friday 12:01
    (`t = 4*1440 + 241`) → `7*1440 + 240`.
  - `test_days_late`: due `240`; end `240` → 0; `241` → 1; `1680` → 1; `1681` → 2.
  - one negative test per validator (see Step 3), e.g. `test_break_must_fit_in_shift`.
- [ ] **Step 2: Run** `uv run pytest tests/test_calendar.py -v` — expect FAIL (import error).
- [ ] **Step 3: Implement** `Calendar` with validators (each `ValueError` with a clear message):
  `0 <= shift_start < break_earliest <= break_latest`, `break_latest + break_length <= shift_end`,
  `shift_end + max_overtime <= 1440`, `0 <= cutoff < 1440`, `working_days` non-empty, unique, each in `0..6`,
  `0 <= origin < 7*1440`. In `Instance.check_references`: calendar requires `time_unit == "min"`; with a calendar
  every `due_date` must be a cutoff (`next_cutoff(cal, d) == d`). Then the functions in `calendar.py`.
- [ ] **Step 4: Bump schema** to `"0.6"` everywhere listed above, regenerate the schema file.
- [ ] **Step 5: Run** `uv run pytest -q` — all pass (calendar tests + unchanged suite).
- [ ] **Step 6: math** — `math/04_workers.md` created with §1 prose (workers, calendar), §2 sets/parameters for the
  calendar ($\Gamma$, shift, break window, overtime cap), change-log row; symbols first in `math/notation.md`;
  README line; protocol entry.
- [ ] **Step 7: Commit (on approval)** `feat: work calendar and schema 0.6`.

### Task 2: Tardiness in missed shipping days

**Files:**
- Modify: `src/simulation/objectives.py` (`_total_tardiness`, `_tardiness_cpsat`, `TOTAL_TARDINESS.spread`)
- Modify: `src/simulation/due_dates.py` (`assign_due_dates` rounds up to cutoffs)
- Modify: `src/simulation/metrics.py` (`tardy_days` column, minute columns unchanged)
- Modify: `src/simulation/model/compiled.py` (field `calendar`, see Interfaces)
- Test: `tests/test_objectives.py`, `tests/test_due_dates.py`, `tests/test_metrics.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces: `CompiledInstance.calendar: WeekCalendar | None`, where `WeekCalendar` is a frozen slots dataclass in
  `calendar.py` with the same nine fields as `Calendar` (ints/tuple), built by `WeekCalendar.of(cal: Calendar)`;
  the Task 1 functions accept either (duck-typed on the field names).
- `TOTAL_TARDINESS.evaluate`: with `ci.calendar` → `sum(days_late(cal, D_k, C_k))`, else minutes as today.
  `TARDY_ORDERS` unchanged (late iff `C_k > D_k` holds in both units).

- [ ] **Step 1: Failing tests** (`tests/test_objectives.py`), on a one-order instance with calendar and due date
  240, schedules ending at given times:
  - `test_boundary_minutes`: ends 240 → 0, 241 → 1, 1680 → 1, 1681 → 2 (evaluate).
  - `test_weekend_counts_one_day`: due Friday 12:00 (`4*1440+240`), end Monday 10:00 (`7*1440+120`) → 1.
  - `test_day_tardiness_cpsat_agrees`: CP-SAT with `TOTAL_TARDINESS` on a two-operation calendar instance
    (operation durations forcing an end of 1700) reports objective 2 and `evaluate` on its schedule is 2.
  - `test_minute_tardiness_without_calendar_unchanged`: existing mk01 due-date test values unchanged.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**:
  - `_tardiness_cpsat` with calendar: for each due order and each `c in cutoffs(cal, horizon)` with `c >= D_k`
    a Boolean `b` with `C_k >= c + 1` ⇔ `b` (both directions, as `_tardy_orders_cpsat`); `T_k = sum(b)`.
  - spread with calendar: `len(due) * len(cutoffs(cal, static_horizon(ci)))`.
  - `assign_due_dates`: after computing the minute value, `next_cutoff(cal, value)` if the instance has a calendar.
  - `run_metrics`: with calendar add `tardy_days`; keep `total_tardiness` (minutes), `tardy_orders`,
    `max_lateness`.
- [ ] **Step 4: Tests** `test_due_dates.py::test_due_dates_rounded_up_to_cutoffs` (every due date is a cutoff and
  ≥ the unrounded value); `test_metrics.py::test_tardy_days_column`. Run `uv run pytest -q` — pass.
- [ ] **Step 5: math** — `math/06_due-dates.md`: day tardiness (formula from spec §4), CP-SAT mapping, rounding;
  `04_workers.md` objective note; protocol entry.
- [ ] **Step 6: Commit (on approval)** `feat: tardiness in missed shipping days`.

### Task 3: Worker shares and machine-less operations in the format

**Files:**
- Modify: `src/simulation/model/instance.py` (`WorkerShare`, `Instance.workers`, `Operation.duration`,
  `Operation.worker`, `CarrierStep.worker`, `CarrierStep.setup_attended`, `CarrierStep.removal_attended`)
- Modify: `schemas/instance-0.6.json` (regenerate; still unpublished, so in place)
- Test: `tests/test_instance_model.py`

**Interfaces:**
- Produces:
  - `class WorkerShare(BaseModel)`: `whole: bool = False`, `prefix: NonNegativeInt = 0`, `suffix: NonNegativeInt = 0`,
    `qualified: tuple[str, ...] | None = None` (None = every worker).
  - `Instance.workers: tuple[str, ...] = ()`
  - `Operation.duration: PositiveInt | None = None` (machine-less operation; exclusive with `options`)
  - `Operation.worker: WorkerShare | None = None`
  - `CarrierStep.worker: WorkerShare | None = None` (main operation of the step; for a batch step one share per run),
    `CarrierStep.setup_attended: bool = False`, `CarrierStep.removal_attended: bool = False` (whole share, all workers).

- [ ] **Step 1: Failing negative tests**, one per rule:
  `whole` together with `prefix`/`suffix` > 0; neither `whole` nor `prefix + suffix > 0`; `prefix + suffix`
  greater than the shortest option duration (or `duration`); unknown name in `qualified`; empty `qualified`;
  duplicate worker IDs; worker ID equal to a machine ID; share used but `workers` empty; operation with both
  `options` and `duration`; machine-less operation (`duration`) without `worker`; machine-less carrier operation
  (not supported: carrier operations take durations from `carrier_steps`); `setup_attended`/`removal_attended` on
  a step without setup/removal. Plus `test_valid_worker_instance_loads` for a small valid instance.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** fields and validators in `Instance.check_references` / field validators; regenerate
  the schema.
- [ ] **Step 4: Run** `uv run pytest -q` — pass.
- [ ] **Step 5: math** — `04_workers.md` §2 (shares $a_o$, $r_o$, qualification sets $W_o$) and table of the five
  kinds from spec §3.2; `notation.md`; protocol entry.
- [ ] **Step 6: Commit (on approval)** `feat: worker shares and machine-less operations in the format`.

### Task 4: Compilation of workers and guards in consumers

**Files:**
- Modify: `src/simulation/model/compiled.py`
- Modify: `src/simulation/sim/des.py`, `src/simulation/planners/dispatching.py`, `src/simulation/planners/cpsat.py`,
  `src/simulation/planners/repair.py` (guard only)
- Test: `tests/test_compile.py`

**Interfaces:**
- Produces in `CompiledInstance`:
  - `worker_ids: tuple[str, ...]`
  - `fixed_duration: tuple[int | None, ...]` (op idx → duration of a machine-less op, else None); machine-less ops
    have `options == ()`
  - `shares: tuple[tuple[Share, ...], ...]` (op idx → shares in the order whole, prefix, suffix), with
    `class Share(NamedTuple): kind: str  # "whole" | "prefix" | "suffix"`, `length: int` (0 for whole),
    `workers: tuple[int, ...]` (qualified worker idxs)
  - `calendar: WeekCalendar | None` (from Task 2)
  - helper `share_interval(share: Share, start: int, end: int) -> tuple[int, int]` in `compiled.py`
    (whole → `(start, end)`, prefix → `(start, start+length)`, suffix → `(end-length, end)`)
- Setup/removal operations of a run step with `setup_attended`/`removal_attended` get a whole share; the main
  operations of a step with `CarrierStep.worker` get that share; members of one batch carry the same share.
- Guards: `Simulation.__init__`, `dispatch` / list-scheduling entry, `solve`, `shift_repair` raise
  `NotImplementedError("workers: phase 2+")` if `ci.worker_ids` or any `ci.fixed_duration` is set.

- [ ] **Step 1: Failing tests**: `test_compiled_shares_and_fixed_duration` (one machine-less op with prefix 10 and
  duration 40, one machine op with whole share, `qualified=("A",)` → `workers == (0,)`), `test_share_interval`,
  `test_run_setup_gets_whole_share`, `test_consumers_reject_workers` (each of the four raises).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** in `compile_instance` (`operation_graph` unchanged; durations of machine-less ops come
  from `Operation.duration`); `static_horizon` uses `fixed_duration` when `options == ()`.
- [ ] **Step 4: Run** `uv run pytest -q` — pass.
- [ ] **Step 5: math** `04_workers.md` §5 (implementation, compiled form); protocol entry.
- [ ] **Step 6: Commit (on approval)** `feat: compile workers and shares`.

### Task 5: Schedule format for workers and breaks

**Files:**
- Modify: `src/simulation/model/schedule.py`
- Test: `tests/test_schedule.py` (new) or existing schedule tests in `tests/test_instance_model.py`

**Interfaces:**
- Produces:
  - `Assignment.machine: str | None` (None for machine-less operations)
  - `Assignment.workers: tuple[str, ...] = ()` (one per share, same order as `ci.shares[o]`)
  - `class Break(BaseModel)`: `worker: str`, `start: NonNegativeInt` (length from the calendar)
  - `Schedule.breaks: tuple[Break, ...] = ()`
- Every place that builds `Schedule`/`Assignment` keeps working (defaults); JSON I/O unchanged otherwise.

- [ ] **Step 1: Failing tests**: `test_assignment_without_machine`, `test_schedule_with_breaks_roundtrip`
  (`write_model` / `read_model`), `test_old_schedule_still_feasible` (toy-3x3 CP-SAT plan through `check_schedule`
  → `[]`).
- [ ] **Step 2–4:** run (FAIL), implement, run `uv run pytest -q` (pass).
- [ ] **Step 5: Commit (on approval)** `feat: schedule format with workers and breaks`.

### Task 6: Checker C11–C14

**Files:**
- Modify: `src/simulation/check/feasibility.py`
- Create: `data/instances/toy-workers.json` (mini instance, see Step 1)
- Test: `tests/test_workers_checker.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- `check_schedule(ci, assignments, snapshot=None, breaks=())` — new keyword `breaks: Iterable[Break]`; existing
  callers unchanged.
- New named functions (style of the existing ones), constraint labels:
  - `C11` `worker_shares_wrong(ci, o, a) -> list[Violation]`: `len(a.workers) == len(ci.shares[o])`, each worker
    known and qualified; `a.machine is None` iff `ci.options[o] == ()`; duration of a machine-less op equals
    `fixed_duration`. Members of a batch (C10 group) must carry identical `workers`.
  - `C12` `worker_overlaps(ci, by_op) -> list[Violation]`: share intervals of one worker do not overlap; a batch's
    share counts once.
  - `C13` `outside_shift(ci, by_op) -> list[Violation]` (only with `ci.calendar`): each share interval lies within
    one working day in `[shift_start, shift_end + max_overtime]` (minute of day).
  - `C14` `break_violations(ci, by_op, breaks) -> list[Violation]` (only with calendar and workers): for each worker
    and each working day on which that worker has a share, exactly one break with minute-of-day start in
    `[break_earliest, break_latest]`; no share interval overlaps `[start, start + break_length)`.
- `not_eligible`, `wrong_duration`, `machine_overlaps` skip / handle machine-less operations.

- [ ] **Step 1: Mini instance** `toy-workers.json` with calendar defaults, workers `A`, `B`, machine `P`:
  order `k1`: `print` on P (60 min, prefix 15), then `gegenbetten` machine-less (duration 90, prefix 30,
  `qualified=["A"]`), then `pack` machine-less (whole, 20 min), due date Monday 12:00 (240); order `k2`: only
  `pack` (whole, 20 min), due 240.
  Hand plan (comment in the test, t = 0 is Mon 08:00): k2 pack [0, 20) (A); k1 print [0, 60) (B on the prefix
  [0, 15)), gegenbetten [60, 150) (A on [60, 90)), pack [150, 170) (A); breaks A and B at 240 (12:00) → feasible,
  `TOTAL_TARDINESS == 0`.
- [ ] **Step 2: Failing tests** in `tests/test_workers_checker.py`:
  - `test_hand_plan_is_feasible` → `[]`
  - one test per constraint, each a single change of the hand plan: wrong worker count (C11), `B` on gegenbetten
    (C11, not qualified), machine given for a machine-less op (C11), k2 pack moved to [70, 90) by A, overlapping
    A's gegenbetten prefix (C12), k1 pack at night `[1000, 1020)` (C13), k1 pack at `[680, 700)` ending 19:40 (C13),
    k1 pack at `[230, 250)` across the break (C14), break of A at `t = 301` = 13:01 (C14), missing break of B
    (C14), two breaks of A on Monday (C14)
  - `test_share_touching_break_is_allowed` (share ends at break start)
  - `test_batch_shares_count_once` (oven batch of 3 carriers with one prefix/suffix by A: no C12)
  - `test_shares_without_calendar_ignore_shifts` (no calendar: C13/C14 not checked, C11/C12 are)
- [ ] **Step 3: Run** — FAIL.
- [ ] **Step 4: Implement** the four functions and the `breaks` parameter; wire them into `check_schedule`.
- [ ] **Step 5: Run** `uv run pytest -q` — pass, incl. all existing checker tests.
- [ ] **Step 6: math** `04_workers.md` §3 constraints (C11)–(C14) in LaTeX with one-sentence explanations, §5
  checker mapping, §6 assumptions (overstay soft, swap rule, [CHECK WITH FIDENTIS] marker), §7 sources (spec §3.1,
  §3.3), change log; `01_basic-fjsp.md` note that C1 now allows machine-less operations; protocol entry.
- [ ] **Step 7: Commit (on approval)** `feat: checker for workers, shifts and breaks`.

---

## Later phases (own plans, after approval of this one)

- Phase 2: DES (shifts, breaks, overtime, swap rule, oven overstay, worker-aware snapshot) — spec §6, step 3.
- Phase 3: dispatching rule with workers and calendar — spec §7, step 4.
- Phase 4: CP-SAT (worker intervals, breaks, overtime, objective levels 0–3) and rescheduling — spec §5, §7,
  steps 5–6; zero-disturbance test with workers.
- Phase 5: generator, packaging operation in routes, dental example, calendar Gantt (§8a), notebook — step 7.
- Phase 6: worker s-batch across orders (packaging, polishing) — step 8.
