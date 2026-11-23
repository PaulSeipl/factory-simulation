# Changelog

`mes_bridge` only; thesis changes go to `math/protocol.md`. Newest first.

## Unreleased

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
