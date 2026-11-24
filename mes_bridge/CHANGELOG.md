# Changelog

`mes_bridge` only; thesis changes go to `math/protocol.md`. Newest first.

## Unreleased

- Planned nesting flow (slice 7, task 7.1): in the MES setting `nesting_flow = PLANNED` an order reaches the scheduler
  once planned, before DATA_PREP_SECONDARY nested it, so its secondary parts have no plate and its print and plate
  steps are keyed per order. New `assumed.assume_plates` (called in `MesFactory.refresh` and `once.solve`) gives each
  such order an assumed plate and fills the plates in due-date order into assumed prints of up to
  `PLATES_PER_PRINT = 4` (user, 2026-11-24; stable `uuid5` ids per grouping), renaming the per-order keys to job and
  carrier keys; `once.steps(aliases=)` publishes each step under the MES's own keys again. DATA_PREP_SECONDARY is
  mapped (an order operation); a finished one is left out (`instance.is_mapped`): it decides nothing, and nestings
  clicked through within one minute clashed as frozen facts (C12, found with the recording). Recording
  `tests/data/problem_planned_flow.json` (scratch MES, 2026-11-24), tests `tests/test_assumed.py` (8). Checked live:
  both un-nested orders fully planned by the scheduler, nesting with a worker, one assumed print, order tab and Team
  plan show it.
- Overtime: `api.ProblemCalendarOut.max_overtime_minutes` (default 0, so older recordings still load) is the MES
  planning setting of the same name (spec decision 20: global, default 0); `instance._calendar` passes it as
  `Calendar.max_overtime` instead of the hard-coded 0. `tests/data/openapi.json` refreshed from the MES. Test
  `tests/test_instance.py::test_the_calendar_takes_the_mes_max_overtime_and_defaults_to_none`.
- Keep-alive: the MES serves a schedule only while it is younger than the planning setting `scheduler_stale_minutes`
  (default 30), else it shows "Scheduler offline"; the bridge published only on a change, so a quiet stretch
  (overnight, an unchanged FREE variant) marked a healthy scheduler offline. `MesClient.settings()` reads
  `GET /planning/settings` (`api.PlanningSettingsOut`, other fields ignored); `MesFactory.last_published_at` and
  `keep_alive(stale_minutes)` republish the current plan unchanged (through `update_plan`, so checked) once the last
  publication is older than half the threshold (also the first tick after `restore()`); `Runner.tick` calls it per
  variant after the step (a failure is logged, the step stands) and `next_wake` wakes at the deadline ("keep_alive").
  Cost: one extra schedule row per variant every stale/2 minutes while nothing changes. Tests `tests/test_runner.py`
  (5 new), `fake_mes` serves the settings.
- Startup: `runner._login_when_up` retries the login while the MES is unreachable (`OSError`, e.g. connection
  refused) every 5 s, up to 60 attempts (about 5 min), then re-raises; one log line per retry. An HTTP error
  status (`MesError`, e.g. 401) is raised at once. Tests `tests/test_runner.py` (3 new).
- `instance._options`: a machine whose MES status is DOWN or DECOMMISSIONED is no option of a step (the export
  lists it with its status); kept if a started task runs on it (the snapshot freezes that operation there) or if
  it would leave the step without a machine (warning logged, a repair follows). A status change changes the built
  instance, so the factory's change detection sees it (a complete rescheduling). `state.out_of_service` then removes
  such a machine per operation from every operation not started (options are per step in the format, so a started
  print would otherwise keep it open to the whole step); runner and `once` both apply it.
- Showcase: `tests/e2e/demo_db.py` (demo database), `mes_driver.py demo` (three arrived orders with due dates, a
  second printer), `tests/e2e/demo_scenario.py` (the showcase of `DEMO.md` end to end over the MES API: 22 checks).
- 6.1: bound and free (decision 4). `state.pin`: in BOUND an MES assignment pins every operation of its step that
  has not started: the assigned machine is its only option (for the whole run: setup, main and removal share one
  machine), the assigned worker the only qualified one; on the compiled instance, where both are per operation (in
  the format they are per step, shared by the carriers). A started step keeps its facts; a pin naming a machine or
  worker the operation cannot use is skipped and reported (`Pins.skipped`). FREE ignores the assignments.
  `MesFactory(variant=...)` publishes its variant; in BOUND a new, changed or removed pin is an instance change (a
  complete rescheduling, decision 18), since a repaired plan would break the new pin and never pass the checker.
  `runner.Runners`: one `Runner` per variant (own factory, anchor and state directory), one event queue, every wake
  steps each variant, BOUND first, and one failing variant does not stop the other. `SchedulerConfig.variants`
  (default both; FREE can be left out if two solves are too slow). `mes_bridge.once` publishes each configured
  variant. Tests `tests/test_variants.py` (14).
- 5.2: the frozen horizon (decision 19). CP-SAT and the GA plan from the snapshot plus every operation of the
  current plan that has not started and is planned to start before t + the time limit (whole minutes, rounded up):
  fixed with its planned machine, times and workers (`state.with_frozen_horizon`, after Shiau, Chen & Fan 2026 as
  math/05 records it; the thesis has the frozen horizon as an open point, so it lives in the bridge). The rule
  plans at once, so its horizon is 0. Tests: the fixed operations and their fields, no horizon, CP-SAT keeps them
  and its plan passes the checker against the real snapshot, the horizon per solver.
- 5.1: CP-SAT and the GA in `SchedulerConfig.solver` (`kind`: `rule` | `cpsat` | `ga`; `objective`: `worker`, the
  thesis worker objective with the cutoff buffer as in `simulation.experiment`, or `makespan`; `time_limit` in
  seconds; `deterministic_time` for CP-SAT; `seed`). CP-SAT runs on one thread, so a seed reproduces a plan.
  Shortcut: without any due date the worker objective drops its two due-date levels (the thesis objective refuses
  an instance without due dates; the MES due date is optional). Fallback: a solver that returns no plan for every
  operation (no solution in time, an infeasible model) hands over to the configured rule; `planner.last["fallback"]`
  says why. The snapshot now carries today's break as taken once its window has begun (`state.taken_breaks`,
  assumption: the earliest start in the window clear of the worker's frozen work), because the MES records no
  breaks and CP-SAT otherwise owes a break whose window is past and postpones it into the night (infeasible on
  every recording). Tests: both solvers and objectives on two recordings, with due dates, the objective's levels,
  the fallback on `problem_mill_prep.json`, 8 for the taken break.
- 4.3: breaks (decision 21). The calendar takes the break window and length from the problem (the MES's
  `planning_setting`, no longer hard-coded 12:00 / 60 min); the published schedule carries the plan's breaks (one
  per worker and day, `schedule_breaks`), from the one-shot command and the runner. Recordings re-made with the
  new calendar fields.
- 3.3b: `mes_bridge.config.SchedulerConfig` (decision 9; Pydantic, `extra="forbid"`, JSON via `--config` on the runner
  and the one-shot command): the solver (a sequencing and an assignment rule of the thesis), the rescheduling policy's
  thresholds (math/05 §3) and the safety-poll interval. CP-SAT and the GA join in 5.1, the frozen horizon in 5.2.
- 3.2: a rework round (decision 8). While a plate's rework request is open, the MES has its QM done (suppressed) and
  REWORK open; the bridge plans the thesis route QM -> REWORK (a mill run per plate) -> RECHECK -> sawing, so sawing
  and the primary finishing wait for the re-check. RECHECK has no MES key until QM reopens (an instance change), so it
  is planned but not published. Shortcut: REWORK's per-telescope attended minutes go into its run (setup = the base).
  Decision 8's estimates (params until the job exists, then the entered minutes) come from the export; a MES test
  pins it for a mill job.
- 3.1c: a third recording `problem_blank.json` (both orders' primary parts on one formed blank) in every
  recording test. Fix it found: one MES task can stand for several single-operation steps (a DATA_PREP_PRIMARY over
  two orders); the snapshot splits its time into consecutive pieces, one per step, so the worker is not frozen twice
  at once (`state._one_task_one_worker`). `tests/e2e/mes_driver.py seed --both` seeds an order with both lanes; the
  end-to-end run passed with it (25 steps planned over the wire, the served plan entirely from the scheduler).
- 3.1b2: the PRIMARY lane on blanks (B2 (1) A). A blank is the primary mill job's once DATA_PREP_PRIMARY formed it,
  before that one assumed blank per order (`B:<mill job>` / `B:<order>`). Blank milling (MILL_PREP_PRIMARY setup +
  run, REMOVE_MOUNT removal) and the flipped milling (PREP_MILL_FLIPPED setup + run) are given runs per blank;
  Gegenbetten (work, then curing as an unattended rest) and the removal from the blank (the separating step) are
  `per_carrier` steps; data prep, primary polishing and finishing are order steps. Per-carrier steps take the
  params' base once per carrier as the estimator base (math/21 §4), the rest of the MES minutes as part times. QM
  waits for its orders' primary polishing, inspection for the primary finishing (the cross-lane joins). Shortcut:
  REMOVE_MOUNT's per-part minutes (10 + 2 per part) are added to the blank's run, since a run's removal is one value
  per step; the mill's time stays exact, the worker misses 2 min per part. The interim `MAPPED` filter now lists the
  whole route.
- 3.1b1: the SECONDARY lane to the packaging. QM and sawing are `per_carrier` steps (one run per plate, main =
  sum of part times, estimator fixed 0 / share 1; the plate's MES minutes split over its parts; QM on the mill the
  MES params name); support removal, grinding, steam cleaning, polishing, inspection, documentation and packaging
  are order steps. SAWING is now the real separating step. The PRIMARY lane and its joins follow in 3.1b2.
- The MES export covers the whole route since 3.1a; `ProblemPartOut.mill_job_id` added (model, `openapi.json`
  copy, recordings re-made). Until 3.1b the bridge maps only the slice-1 steps (`instance.MAPPED`, a marked
  shortcut); the rest stays the MES fill's. The recorded print runs 3000 min, so its expected end lies after any
  recording time (the MES floors an end in the past to now + 15 min). Contract test: `SchedulerStateEnum` (the
  plan's) excluded.
- End-to-end (task 2.4): `tests/e2e/mes_driver.py` (MES side: seed an arrived order, then start / finish the mill
  data prep and start and hand off the print through the MES's services, each commit posting its event). Passed
  against this branch's MES and a running `mes_bridge.runner`: every transition woke the bridge within 0.5 s, the
  overrunning print led to a new publication, and `GET /planning/plan` served it (`scheduler` ONLINE, SECONDARY lane
  `SCHEDULER`, the tail `MES_FILL`). Fixes it found: a frozen operation lasts at least one minute; frozen operations
  keep the model's precedence and the snapshot time covers every finished end (`state._consistent`: whole minutes
  where the MES has seconds); `MesFactory.current_plan()` is the plan as executed (the real machine, workers and
  times of a started step, since a worker may start it differently than proposed). Tests for all three.
- State on disk (decision 22): `mes_bridge.store.Store` keeps `anchor.json` (epoch, anchor, the plan last published,
  its publication id; written atomically) and `decisions.jsonl` per variant under `--state-dir`
  (`mes_bridge_state/`, git-ignored). `Runner.resume()` continues from it only if the MES's current schedule of
  the variant is that publication and the epoch is this week's; otherwise the first step is a complete
  rescheduling. `MesFactory.restore`, `MesFactory.publication`. Tests `tests/test_store.py` (6: save and decisions
  per step, resume, someone else published, another epoch, an unreadable file, nothing saved).
- The long-running scheduler: `python -m mes_bridge.runner [--url] [--host] [--port]` (secrets
  `MES_SCHEDULER_PASSWORD`, `MES_EVENTS_TOKEN` from the environment). `runner.event_server`: `POST /events` with
  the shared bearer token (401 without, 400 for a body that is not a JSON object, 404 elsewhere), into a queue.
  `Runner`: one `factory.step` per wake for all events since the last (merged); next wake = the earliest of
  OVERDUE (a running step's expected end), PLANNED_START (a planned start), the policy's period and the safety
  poll (5 min); a failing step (MES down) is logged and retried at the next wake. `MesClient` logs in again once
  on a 401 (the 8 h token). Tests `tests/test_runner.py` (12; the event server on a real local socket).
- `mes_bridge.factory`: `MesFactory`, the MES as a `simulation.control.rescheduling.Factory` (snapshot from the
  problem, the plan last published in operation order, `update_plan` checks against the snapshot and publishes;
  a plan with violations is recorded in `rejected` and not published), and `step` (fetch, rebuild the instance; a
  changed set of operations is `adapt_plan`'s `arrived` case, decision 18; a planner plan the checker rejects is
  recorded, the factory keeps its plan). Tests `tests/test_mes_factory.py` against the shared `tests/fake_mes.py`:
  first step plans completely, an unchanged state publishes nothing, a longer print is repaired and published, a
  changed set of operations reschedules completely, facts that break a rule block the publish.
- One-shot scheduling: `python -m mes_bridge.once [--url] [--dry-run]` logs in as the scheduler (password from
  `MES_SCHEDULER_PASSWORD`), fetches the problem, plans with the SPT rule from the snapshot, checks it and
  publishes it as the BOUND schedule; a plan with violations is printed, not published (decision 23).
  `mes_bridge.client` (standard-library HTTP, swappable `send` for tests); `once.steps` turns the plan into one
  schedule step per open MES step (attended until the handoff or the end of the worker's share). Unit tests
  against a fake MES replaying the recordings; `tests/test_integration.py` against a running MES of this branch
  (skipped without `MES_IT_URL`).
- `mes_bridge.state`: `id_map` (MES key → its compiled operations in time order: AM_PREP = print setup + run,
  PART_POWDER_REMOVAL = removal, the mill chain likewise, every other step one operation) and `build_snapshot`
  (a started MES task freezes its operations: done with real times, running with the MES's expected end, at
  least t + 1; the handoff ends a setup and starts the run). A done step without a start, a started task without
  a worker, a worker outside the instance or a machine the operation cannot use raise `MappingError`. Tests:
  both recordings replan with `spt` from the snapshot and pass `check_schedule`; setup still running, handed off
  and finished; one negative test per rule. Recordings re-made with a consistent timeline (one worker, no
  overlap, the print after its mill data preps) by `tests/data/record_problems.py`, now kept here.
- `mes_bridge.instance.build_instance`: MES problem → thesis `Instance` (slice 1, SECONDARY lane). Plates are
  carriers; the print a given run per AM job (AM_PREP = setup + main, PART_POWDER_REMOVAL = removal), the
  secondary mill a given run per plate (MILL_PREP_SECONDARY = setup + main, SECONDARY_PLATE_REMOVAL = removal);
  cleaning, heat treatment, blasting carrier steps without runs (cleaning and blasting as s-batches of the MES
  linear form); DATA_PREP_SEC_MILL an order operation. Step shape from `params`, run and order minutes from the
  operations (an entered job estimate wins). Epoch Monday 00:00 in the MES time zone, minutes rounded up,
  instants before it clamped to 0; global calendar (shift = daily minutes + break). Shortcuts, each marked in
  the code: break 12:00 / 60 min until 4.3; REWORK left out until slice 3; the last carrier operation in scope
  takes the separating role the format needs (V14); an overdue due date clamps to the first cutoff after release;
  the oven is a worker step with an unattended rest and no p-batch (no oven machine in the export). Anything
  else the format cannot hold raises `MappingError`. Tests: both recordings map, compile, plan with `spt` and
  pass `check_schedule`; hand values; one negative test per `MappingError` rule; a V14 failure surfaces.
- `mes_bridge.api`: hand-written models of `GET /planning/problem` and `PUT` / `GET /planning/schedule`
  (`extra="forbid"`, MES enums as strings). `tests/test_contract.py` compares them field by field with the
  checked-in copy `tests/data/openapi.json` (decision 15); a detector self-test. Recorded problem responses
  `tests/data/problem_mill_prep.json` (two orders on two plates of one print, one mill job formed, one mill
  data prep running) and `problem_printing.json` (both mill jobs formed, AM_PREP handed off), from the MES
  test helpers of `tests/services/test_planning_problem.py` via a temporary test (not committed).
- Skeleton: own uv project with an editable path dependency on `simulation` (no workspace, so the thesis lock
  stays untouched); test that `src/simulation` never imports `mes_bridge`.
