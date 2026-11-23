# Changelog

`mes_bridge` only; thesis changes go to `math/protocol.md`. Newest first.

## Unreleased

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
