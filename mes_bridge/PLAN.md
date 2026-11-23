# MES scheduler integration: implementation plan

Driven by a self-paced `/loop`. **Read this file top to bottom at the start of every round.**

- **Design (binding):** MES spec `docs/specs/2026-11-22-scheduler-integration-design.md` (decisions 1–23) and
  ADR `docs/adr/0003-scheduler-publishes-a-stored-schedule.md`. If the code disagrees with the spec, that is a
  Blocked entry, not a silent fix.
- **Repositories (work only in these worktrees):**
  - simulation: `C:\Users\pauls\code\fidentis\simulation\.claude\worktrees\planner-api-loop-design-e38416`
  - MES: `C:\Users\pauls\code\fidentis\PROD_DATA_MES_V2____postgres-dbms\.claude\worktrees\planner-api-loop-design-d4a13c`
- **Rules:** each repo's own `CLAUDE.md` applies inside it. `mes_bridge/` is not thesis code: it keeps its own
  `CHANGELOG.md` and gets no `math/protocol.md` entries. A change to `src/simulation/` is thesis code: full
  `CLAUDE.md` rules there (math/, protocol entry, zero-disturbance and negative tests).
- **No stop for approval between tasks or slices:** the per-step approval of the simulation `CLAUDE.md` is
  replaced by the slice summary comment on the PRs (user, 2026-11-22). Commit, push and draft PRs are allowed
  (user, 2026-11-22).
- **Safe when merged with no scheduler running** (MES targets `main` of a production system): the `scheduler`
  user is never seeded with a default password (credentials from the environment or a one-off script; documented
  in `docs/backend/authentication.md`); the event listener does nothing when `SCHEDULER_URL` is unset; with no
  schedule rows `GET /planning/plan` returns what it returns today plus `source`, pinned by a test.

## Prerequisites (user)

- [x] `gh` logged in (checked 2026-11-22).
- [x] Claude Code permissions allow `git push` and `gh pr …` without a prompt in both worktrees (worked 2026-11-22).
- [ ] Local MES backend on port 8080 with its database (needed from slice 1, task 1.6). 2026-11-23: 8080 runs
  an MES without `/planning/problem` (the main branch, left alone); 1.6 ran this branch's backend on 8091
  against a scratch database instead (migrated, seeded, scheduler user, dropped after).

## Each round

1. Read this file, the MES spec and both `CLAUDE.md` files.
2. Read new comments on both PRs (`gh pr view <n> --comments`; the last read time is in the log). A question
   or "stop" from the user → `## Blocked`, stop the loop.
3. `## Blocked` has an unanswered entry → stop the loop.
4. Check CI of the last push (`gh pr checks`). Red → fixing it is this round's task. The simulation repo has no
   CI: "no checks reported" is not red.
5. Take the first unchecked task of the current slice. Test first where there is logic.
6. Run the gates (below). All green, not only the new tests.
7. Update docs by each repo's rules (MES: the doc table in its `CLAUDE.md`; simulation: `math/` + protocol only
   for `src/simulation/`; `mes_bridge/CHANGELOG.md` for the bridge).
8. Tick the task, add one log line (date, task, commits, findings).
9. Commit per repo (`slice N: <what>`, attribution line from the system reminder), push.
10. Slice complete → post a summary comment on both PRs (new, findings, open, commit range), then continue.
11. Everything ticked → final summary comment on both PRs, stop the loop.

**A decision that is the user's** (scope, model change, trade-off not settled in the spec) → write it under
`## Blocked` with a recommendation, post it as a PR comment, stop the loop. Facts are never the user's job:
look them up.

**Never:** merge; force-push; push to `main`; mark a PR ready; read or write the MES database from the bridge;
touch production (`deploy/`, `docker-compose.prod.yml`); skip the zero-disturbance or negative tests;
baseline a CI error.

**Pacing:** after a round, wake again in 60 s; while waiting for CI, wake after the CI's usual duration.

## Gates

- simulation: `uv run pytest` (repo root).
- mes_bridge: `uv run pytest` in `mes_bridge/`; integration tests against `localhost:8080` when it is up. If it
  is down, say so in the log; those tests do not count as passed.
- MES backend (`backend/`): `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy app`, `alembic check`.
- MES frontend (`frontend/`, when touched or after API changes): `npm run generate_local:api` leaves no diff,
  `npm run check`, `npm run lint`, `npm test`.

## Slices

### Slice 1: boundary (export → rule → publish → Team plan)

- [x] 1.1 Commit the design docs (MES: ADR 0003, ADR 0002 status, spec, `CONTEXT.md`; simulation: this file,
  `CLAUDE.md` line). Push both branches, open one **draft** PR per repo into `main`; the description carries the
  slice checklist. PRs: MES FIDENTIS-GmbH/PROD_DATA_MES_V2____postgres-dbms#160, simulation
  PaulSeipl/factory-simulation#1.
- [x] 1.2 `mes_bridge/` skeleton: own uv project, editable path dependency on `simulation`, `CHANGELOG.md`, a test
  that `src/simulation` never imports `mes_bridge`. MES CI is unaffected (bridge lives here).
- [x] 1.3 MES: `scheduler` service user (created by `scripts/create_user.py --allow-no-worker`, never seeded; bearer login) and the `schedule` tables (append-only, variant,
  `snapshot_as_of`, steps, breaks) with migration; `PUT` / `GET /planning/schedule`, write restricted to the
  service user. Tests incl. one negative test per validation rule.
- [x] 1.4 MES: `GET /planning/problem` for the SECONDARY lane (decision 11), one read transaction, reusing the
  node gathering of `services/planning/plan.py`. Tests. **Reopened 2026-11-23:** add jobs (prints, mill jobs) with their parts and each order's secondary parts (decision 11); carrier-grain keys (B1). Done 2026-11-23.
- [x] 1.5 Split 2026-11-23 into three rounds (too big for one):
  - [x] 1.5a MES: `params` in the problem export (the `task_planning_params` rows of `SCOPE` and the AM / MILL job
    rows; an extension of decision 11, decision 8 already rests on them). Bridge: hand-written models for problem
    and schedule + contract test against a copied `openapi.json` (decision 15); a recorded problem response from the
    `two_plates` test state. MES test: params and the exported units reproduce each carrier's minutes.
  - [x] 1.5b Bridge: problem → `Instance` (schema of `src/simulation/model/instance.py`). Global step shape from
    `params` (`setup + setup_per_carrier × carriers` is the PLATE formula); per-instance values only where the format
    is per instance: print and mill as given runs (one per AM job, one per plate), `Run.duration` = exported main
    minutes; order operations `Operation.duration`. Time epoch (decision 17: Monday 00:00 Europe/Berlin of the
    bridge's start week, `Calendar.origin = 0`, minutes rounded up, aware subtraction). Calendar (decision 20) with
    today's break 12:00 / 60 min hard-coded until 4.3 (stopgap). REWORK left out until slice 3 (its predecessor QM
    is out of scope). Times before the epoch clamp to 0; an overdue due date clamps to the first cutoff at or after
    release (tardiness understated, logged). `Instance` validation is the loud failure; tested.
  - [x] 1.5c Bridge: `Snapshot` and the id map instance ids ↔ MES keys, matching how `operation_graph` and
    `snapshot()` name carrier and run operations (setup / main / removal); AM_PREP = print setup + main (handoff
    ends the setup), PART_POWDER_REMOVAL = removal, the mill chain likewise. Unit tests on the recorded response.
- [x] 1.6 Bridge: one-shot command: fetch problem → `spt` → `check_schedule` → `PUT`. Integration test against
  the local MES.
- [x] 1.7 (split 2026-11-23: 1.7a backend done in MES f0007fe; 1.7b done in MES ce7c923: the `source` label in the Team plan
  with a design pass, and the "plan is computed on read" block in `AGENTS.md`, the file the MES's `CLAUDE.md`
  points to, rewritten for ADR 0003) MES: `GET /planning/plan` serves the latest schedule with the facts overlay, `source` field, fallback to
  `fill.py` when stale. Regenerate the client. Team plan shows it (design pass first). Docs: `architecture.md`
  §8a, `CLAUDE.md` plan block.

### Slice 2: events and the controller

- [x] 2.1 simulation (thesis): `Factory` Protocol (`snapshot`, `current_plan`, `current_breaks`, `update_plan`) in
  `control`; `adapt_plan` typed against it; `arrived` documented as "the instance changed". Zero-disturbance test
  green; protocol entry; `math/05` change log.
- [ ] 2.2 Split 2026-11-23 into three rounds:
  - [x] 2.2a Bridge: `MesFactory` (the `Factory` over the MES: snapshot from the problem, the plan last sent,
    `update_plan` checks (decision 23) and publishes) and the controller step (fetch → instance changed? → `adapt_plan`
    with `arrived` = changed set of operations, decision 18). Tests against a fake MES.
  - [x] 2.2b Bridge: the long-running loop: `POST /events` (shared token), events merged per step, periodic trigger and
    safety poll, OVERDUE / PLANNED_START timers.
  - [ ] 2.2c Bridge: `anchor.json`, `decisions.jsonl` per variant; restart check against `GET /planning/schedule`
    (decision 22).
  Original text: Bridge: `MesFactory` implementing it; long-running loop with `POST /events` (shared token), event queue
  merged per step, periodic trigger and safety poll, OVERDUE / PLANNED_START timers; `anchor.json`,
  `decisions.jsonl`; restart check against `GET /planning/schedule` (decision 22); instance change → complete
  rescheduling (decision 18).
- [ ] 2.3 MES: `after_commit` listener posting events (decision 14), background, fire and forget; tests that a
  rollback sends nothing. Docs.
- [ ] 2.4 End-to-end test: start, handoff, finish of a task in the local MES produce a new schedule.

### Slice 3: PRIMARY lane, QM join, job tasks

- [ ] 3.1 Problem export for the PRIMARY lane and the QM cross-lane join; order tail.
- [ ] 3.2 Job tasks per decision 8 (estimator until the job exists, then the entered estimate); rework as instance
  change.
- [ ] 3.3 Scope config (decision 9): MES planning setting for planned task types; `SchedulerConfig` JSON in the
  bridge.

### Slice 4: breaks

- [ ] 4.1 MES: break settings in `planning_setting` (migration, `GET/PUT /planning/settings`, settings UI).
- [ ] 4.2 MES: `fill.py` plans one break per worker and day (rule + test in `test_planning_fill.py`).
- [ ] 4.3 Bridge: calendar from the problem incl. breaks (decision 20); schedule PUT carries breaks.
- [ ] 4.4 Frontend: breaks as gaps in My plan, the ribbon and Team plan (design pass first).

### Slice 5: CP-SAT, frozen horizon, fallback

- [ ] 5.1 Bridge: CP-SAT (and the GA, `planners/ga.py`) selectable in `SchedulerConfig`, with time limit.
- [ ] 5.2 Frozen horizon `t + time limit` (decision 19).
- [ ] 5.3 MES: "scheduler offline" notice in the frontend; staleness threshold as a setting.

### Slice 6: bound and free

- [ ] 6.1 Bridge: pins from assignments (decision 4), two variants with their own anchors.
- [ ] 6.2 MES: `GET /planning/plan?variant=`; frontend switch and suggestions; accepting writes an assignment
  through the existing `PUT`.

## Known unknowns (facts to look up, not decisions)

- Does `repair_plan` fail when the current plan holds operations missing from the instance? (Decision 18 assumes
  it does.)
- Can `fill.py` take one break per worker without a structural change?
- Does the MES test setup tolerate an `after_commit` listener (session fixtures, rollbacks)?
- ~~Does the seed data hold orders past `DATA_PREP_SECONDARY`?~~ No (2026-11-23, scratch database from
  `initial_data.py`): the integration round trip publishes an empty schedule. An arrived order is seeded for
  the end-to-end test 2.4.
- ~~Is `OrderPart.quadrant` set for every secondary part from `DATA_PREP_SECONDARY` on?~~ Checked 2026-11-23: only
  when the submit sends `part_quadrant_assignments` (optional, default `{}`); the export reads `TaskPart.quadrant`
  and keeps job keys for a print with a part lacking one. Unique per plate within an AM job: yes (user).
- What does the bridge do when the MES facts themselves break a model rule (a worker on two tasks at once, a
  step started before its predecessor finished)? `check_schedule` flags violations among frozen operations too,
  so decision 23 would block every publish while such a fact is in the snapshot. Look at real task data in 1.6;
  if it happens, the policy (e.g. publish when every violation is among frozen operations, log the rest) is a
  Blocked entry.
- How does a rework clone or a repeated step map to a unique `Operation.id` within an order?
- Do scrap and the rework clone change a `WorkTask` or `Equipment` row? If not, the listener misses them and
  only the safety poll catches them; extend the listener to those rows.

## Later (not in the slices; user, 2026-11-23)

- The planner receives plate status and assigns physical plates to the carriers. It does not form carriers: the
  composition (which parts on which plate of a print) stays given.
- Plate sets: an AM job points to a `build_plate_set_id`; one load uses plates of one set only (enforced in the
  MES); once refurbishment is due, the set is unusable until it is refurbished, and it can be refurbished only
  when all its plates are free again (after sawing, or unused; the MES has states for this). A resource
  constraint the thesis model does not have yet.

## Blocked

### B1 (2026-11-23, task 1.5): grain of the mapping MES ↔ `Instance` — **answered 2026-11-23**

**Answer (user, chat 2026-11-23), with the facts it rests on:**
- **Grain, not durations.** The MES holds the real data; the bridge takes every minute from
  `GET /planning/problem`, never from `data/generator/fidentis.json`. MES plan logic and params are partly
  outdated; updating them is separate from this integration.
- **Carrier = one plate of one print, key `carrier:<am_job_id>:<quadrant>:<TASK>`** (user: "this, or the plate
  id?"; settled on the facts): the key must exist from the arrival (`DATA_PREP_SECONDARY` done) on, but
  `OrderPart.build_plate_id` is stamped only at `AM_PREP`, references the physical plate (`config.build_plate`),
  which is reused across prints, and will become a planner decision (see Later). So the physical plate is a
  resource attribute of a carrier step (like `equipment_id`), not part of its identity. A reprint overwrites
  `OrderPart.quadrant` and is an instance change. Run-level steps stay `job:<id>:<TASK>`, order steps
  `order:<id>:<TASK>`.
- **A job's load is splittable** (one task per job is today's ad-hoc MES planning). With carrier keys a split
  oven load is two keys, a cross-print s-batch several keys in one window; `schedule_step` stays unique on
  (schedule, key).
- **MES change limited to the problem export and the schedule** (user: yes). `fill.py` keeps its job grain as
  the fallback; its overhaul is a later task. Until then 1.7 shows scheduled carrier steps and falls back to
  job-grain fill steps.
- **One mill job per plate** (8-telescope cap per plate = the `DATA_PREP_SEC_MILL` cap); until a worker forms
  the mill jobs, assume one per plate.
- **Durations per carrier (no thesis change in slice 1).** Carrier-bound steps already vary per carrier with
  parts or telescopes: `per_carrier` runs (mill, QM, rework, saw, Gegenbetten, separation) take
  `base + Σ Part.times` (`model/instance.py`, `operation_graph`, per-carrier branch); the bridge sets `Part.times` so each
  carrier's sum equals the MES minutes. Only `runs="none"` carrier steps (clean, blast, oven) take one value per
  step, by the user's decision of 2026-11-17 (full base per plate, `math/21` §4). The bridge fails loudly if the
  MES gives such a step different minutes per carrier (shortcut: lifted by per-carrier durations for batch steps,
  a thesis format change, once the MES computes them per part or telescope).

**Corrections to the first two versions:** durations were never the gap (`Operation.duration` and `Part.times`
carry per-instance minutes). The secondary mill time is no mismatch: MES 120 per secondary part = simulation 30
per telescope (`math/21` §4, 2026-11-16); the earlier table compared parts with telescopes.

## Log

PR comments read until: 2026-11-23T13:40Z

| Date | Task | Commits | Findings |
|---|---|---|---|
| 2026-11-22 | design | — | Design interview done; spec, ADR 0003 and this plan written, not committed. |
| 2026-11-22 | 1.1 | MES fe447ab, sim b711ade | Docs committed, branches pushed, draft PRs MES #160 and sim #1 opened. Both branches contain their `main`. Local MES on 8080 is down (needed from task 1.6). |
| 2026-11-22 | 1.2 | sim f4545d4 | `mes_bridge/` uv project (editable path dep, own `uv.lock`; root `uv.lock` unchanged), `CHANGELOG.md`, AST boundary test + detector self-test. Gates: simulation 1807 passed, bridge 2 passed. No PR comments. |
| 2026-11-22 | 1.3 | MES 4bdad16 | `orders.schedule` / `schedule_step` / `schedule_break` + migration `af51e148a37c` (round trip and `alembic check` clean on a scratch DB, dropped after); `PUT` (201, scheduler only, else 403) / `GET /planning/schedule` (latest per variant). MES has no roles: publish is restricted by `settings.SCHEDULER_USERNAME`; 422 via `GateError` (house pattern). 19 tests, one negative per rule. Gates: backend 1195 passed, ruff/format/mypy clean; client regenerated, svelte-check 0/0, lint 0 errors, vitest green. Docs: `authentication.md` (service account), `architecture.md` §8a note. Findings: `npm run check` rewrites `src/i18n/*` line endings (restore, not commit); frontend `node_modules` now installed in the worktree. |
| 2026-11-23 | 1.4 | MES 41bbf81 | `GET /planning/problem` (`services/planning/problem.py`, `schemas/problem.py`): `build_plan` split into `gather` + fill (planning tests 96 green before the export was added); `ARRIVAL` = done `DATA_PREP_SECONDARY` (arrival = its `finished_at`), `SCOPE` = SECONDARY lane `DATA_PREP_SEC_MILL`..`SECONDARY_PLATE_REMOVAL` + `REWORK`; done steps stay in the instance (`done`) with real times in the snapshot, a done step without a task (skipped REWORK) is left out; one REPEATABLE READ read-only transaction via `SnapshotDBSession` (tests override it; isolation checked on a fresh session). 11 tests (shared print node, pre-arrival order excluded, no open predecessor cut off, running / handed-off / finished snapshot, machine options). Gates: backend 1206 passed, ruff/format/mypy clean; client regenerated, svelte-check 0/0, lint 0 errors, vitest 116. Findings: (a) `fill.py` books a job's machine for every job-level step (also powder removal, cleaning); the export uses the step's params `resource` instead, so plan and schedule differ there until 1.7; (b) `_MACHINE_TYPE` maps only AM and MILL, OVEN / COM steps get no machine options; (c) until 3.1 no order finishes inside the instance (QM and tail are out), tardiness from `spt` is meaningless; (d) accepted-not-started tasks set the plan's worker but are not exported yet (needed for bound pins, 6.1); (e) 1.5 needs a recorded response: build it from the `two_nested` test state. |
| 2026-11-23 | 1.5 (blocked) | — | MES CI green on 41bbf81. Mapping onto `Instance` needs a model decision (Blocked B1): the format carries per-instance durations only via `Run.duration`, MES grains differ (plate steps per print, mill per plate), secondary mill jobs never mix prints. 1.4 reopened: `jobs with their parts` (decision 11) missing from the export. Loop stopped. |
| 2026-11-23 | B1 rewritten | — | First B1 blamed durations; wrong (`Operation.duration`, `per_carrier` + `Part.times` carry per-instance minutes). User: grain matters, MES data is the source, job loads must be splittable, one mill job per plate (8-telescope cap). Found: `build_plate_id` is the physical plate, stamped at AM_PREP; carrier id = (AM job, quadrant). Remaining question: carrier-grain keys, MES change limited to export + schedule, no thesis change in slice 1. `fixed 66` is current on every branch (math/21). |
| 2026-11-23 | B1 answered | — | Carrier key `carrier:<am_job_id>:<quadrant>:<TASK>` (plate id is a later planner decision and a resource attribute), MES change limited to export + schedule, no thesis change in slice 1: `per_carrier` steps already vary per carrier via `Part.times`, clean/blast/oven constant per plate by the 2026-11-17 decision. Corrected: mill 120 per part = 30 per telescope, no mismatch. Plate sets and planner-formed carriers recorded under Later. |
| 2026-11-23 | B1 follow-up | — | User corrections: the planner will assign physical plates, not form carriers; a plate set due for refurbishment is unusable until refurbished, which needs all its plates free; quadrant unique per plate per AM job. |
| 2026-11-23 | 1.4 (reopened) | MES d38956c | Export at carrier grain: plate steps after the print and the secondary mill chain (`CARRIER_STEPS`: cleaning, heat treatment, blasting, mill prep, plate removal, rework) split per carrier (AM job, `TaskPart.quadrant`), key `carrier:<am job>:<quadrant>:<task>`; minutes (`_durations` on the carrier's parts), done state (all its parts DONE), tasks and predecessors (own plate) per carrier; assignments fan out; the mill chain keeps its key when the mill job forms. `parts` (units, carrier), `jobs` (kind, machine, entered minutes, plate set), `carriers` (parts, mill job) added. Schedule accepts carrier keys (5 negative/positive tests). A job's machine now binds only steps of its kind. 13 new tests. Gates: backend 1219 passed, ruff/format/mypy clean; client regenerated, svelte-check 0/0, lint 0 errors, vitest 116. Findings: (f) PLATE units count distinct `build_plate_id`, unset before AM_PREP, so the job-level AM_PREP / PART_POWDER_REMOVAL of a 4-plate print are computed for 1 plate (also in `fill.py`); the bridge can count the print's carriers instead (1.5); (g) a running carrier task has an expected end only when it is the gathered node's task, else None; (h) assignment fan-out has no test; (i) a plate whose parts sit in several mill jobs reports no mill job (not intended, user). |
| 2026-11-23 | 1.5 split | — | 1.5 split into 1.5a (params export, models, contract, recording), 1.5b (`Instance`), 1.5c (`Snapshot`, id map). Decided on the facts: global step shape from exported params, not inferred from node minutes (finding f would make inference silently wrong); print and mill as given runs; REWORK out of the slice-1 instance; break 12:00 / 60 min as a stopgap until 4.3. MES CI green on d38956c. |
| 2026-11-23 | 1.5a | MES 9a3b829, sim (this commit) | MES: `params` in `GET /planning/problem` (the rows of `SCOPE` and the AM / MILL job rows, `ProblemParamsOut`); test that params + exported units reproduce every carrier's minutes. Bridge: `mes_bridge.api` (problem and schedule models, `extra="forbid"`), `tests/test_contract.py` against `tests/data/openapi.json` (caught a real drift on the first run: `ScheduleOut.created_at` is nullable), two recorded responses (`problem_mill_prep.json`, `problem_printing.json`) from the MES test helpers via a temporary test. Gates: MES backend 1220 passed, ruff/format/mypy clean, client regenerated, svelte-check 0/0, lint 0 errors, vitest 116; bridge 26 passed; simulation 1807 passed. Findings: (j) the recordings' `as_of` is the DB clock while the helpers' task times use a fixed NOW, so `as_of` lies after the task times by the recording delay (harmless; 1.5c must not assume `as_of` = NOW); (k) the MES `_mill_data_prep` test helper now sets a start time, so done mill data preps reach the snapshot. |
| 2026-11-23 | 1.5b | sim (this commit) | `mes_bridge.instance.build_instance` (plates = carriers, print and mill as given runs, plate steps without runs, s-batches for cleaning and blasting from the MES linear form, step shape from `params`, run and order minutes from the operations; epoch, calendar, due cutoffs). Both recordings map, compile, plan with `spt` and pass `check_schedule` (0 violations). 19 new tests (hand values, epoch / DST / clamp, due cutoffs incl. weekend and overdue, one negative per `MappingError` rule, a V14 failure surfacing). Gates: bridge 45 passed, simulation 1807 passed; MES CI green on 9a3b829. Findings: (l) the format needs a carrier chain to end in a separating operation (V14); slice 1 stops before SAWING, so the last carrier operation in scope takes `role="separate"` (validation only, no planning effect; slice 3 maps SAWING); (m) the oven has no machine in the export (finding b), so it is a worker step with an unattended rest and no p-batch: unlimited parallel ovens until OVEN is mapped; (n) a given run may be planned on any printer / mill of its step, not only its job's machine (the step's options are global); bound pins (6.1) or a format change fix it; harmless with one printer and one mill; (o) shift = daily minutes + the hard-coded break, so a worker keeps the capacity `fill.py` plans with. |
| 2026-11-23 | 1.5c | MES ace061b, sim (this commit) | `mes_bridge.state`: `id_map` (MES key → compiled operations: AM_PREP = print setup + run, the handoff in between; PART_POWDER_REMOVAL = removal; mill chain likewise) and `build_snapshot` (finished / running, expected end ≥ t + 1). Both recordings replan with `spt` from the snapshot and pass `check_schedule` (0 violations). 11 new tests incl. 4 negative. MES: `_mill_data_prep` test helper takes a worker and a finish time. Gates: bridge 56 passed, MES backend 1220 passed, simulation 1807 passed. Findings: (p) the first recordings broke model rules themselves (one worker on two overlapping tasks, the print before its mill data preps), and `check_schedule` flagged them although they are facts: added as a known unknown for 1.6 (decision 23 could block every publish); recordings re-made with a consistent timeline by `tests/data/record_problems.py`, now checked in; (q) a running carrier task without an MES expected end (export finding g) gets start + planned, at least t + 1. 1.5 complete. |
| 2026-11-23 | 1.6 | sim (this commit) | `mes_bridge.once` (login → problem → instance + snapshot → `spt` → `check_schedule` → `PUT` BOUND; `--dry-run`; violations printed, not published) and `mes_bridge.client` (stdlib HTTP). 10 unit tests against a fake MES replaying the recordings (a print step attended until its handoff, the oven 35 attended + 180, facts that break C12 block the publish, empty problem, dry run, auth failures). Integration: this branch's MES on 127.0.0.1:8091 with a scratch database `mes_bridge_it` (`alembic upgrade head`, `initial_data.py`, `create_user.py --allow-no-worker` with a generated password from a scratch file), `tests/test_integration.py` passed (login, problem, publish, read back), dropped after; `mes_db` not touched; 8080 is the main-branch MES, left alone. Gates: bridge 66 passed + 1 integration (passed against 8091, skipped without `MES_IT_URL`), simulation 1807 passed. Findings: (r) the seed has no arrived order, so the integration round trip publishes 0 steps: planning on real wire data first in 2.4; (s) the plan's breaks are not published until 4.3; (t) epoch = Monday of the run's week (one-shot), the long-running loop keeps it from its start (2.2). |
| 2026-11-23 | 1.7a | MES f0007fe | `services/planning/served.py`: a fresh BOUND schedule (STALE_AFTER 30 min, shortcut until 5.3) is pinned into `fill.py` (one-line change: fixed nodes book from max(now, start); fill test); a gathered node is replaced only when all its exported steps are scheduled; started steps keep their facts, a past unstarted start goes back to the fill. `PlannedStepOut.source`, `PlanOut.scheduler` (NONE / ONLINE / OFFLINE). `problem.export_nodes` extracted for reuse. 9 new tests incl. 'no schedule = fill as before' (decision 16). Gates: backend 1230 passed, ruff/format/mypy clean, client regenerated, svelte-check 0/0, lint 0 errors, vitest 116. Stopped here: usage limit. |
| 2026-11-23 | 1.7b | MES ce7c923 | Design pass (`frontend-design`, inside Carbon): the brief fixes the look, so the pass decided wording and place only: one "Planned by" row (Scheduler / MES) in the planned-bar popover, right after the period; no tag or colour, which would compete with the area colours of the bars. i18n en / de. `AGENTS.md` plan block rewritten for ADR 0003 (the MES `CLAUDE.md` is empty; `AGENTS.md` carries the rules). Gates: svelte-check 0/0, lint 0 errors, vitest 116; MES CI green on f0007fe. **Slice 1 complete**: summary comment on both PRs. |
| 2026-11-23 | 2.1 | sim (this commit) | `simulation.control.rescheduling.Factory` (Protocol: `snapshot`, `current_plan`, `current_breaks`, `update_plan`), `adapt_plan` typed against it, `arrived` documented as "the instance changed". `tests/test_factory.py` (4, incl. zero disturbance through `execute`). math/05 §5 and change log, protocol entry (90); no written thesis section mentions the interface. Gates: simulation 1811 passed, bridge 66. MES CI green on ce7c923. Finding: `adapt_plan` used only these four calls, so its body is unchanged. |
| 2026-11-23 | 2.2a | sim (this commit) | 2.2 split into 2.2a/b/c. `mes_bridge.factory`: `MesFactory` (the `Factory` over the MES) and `step` (changed set of operations → `adapt_plan(arrived=True)`; the thesis tool decides, no bridge-side copy). 7 tests against the shared fake MES. Gates: bridge 73 passed + 1 integration skipped (no MES), simulation 1811 passed. Findings: (u) `adapt_plan` compares the repaired and the current plan position by position (`_same`), so a factory must return its plan in a stable order: the DES uses operation order, `MesFactory` now too (an unchanged state republished before); (v) the arrival path of `adapt_plan` hands the old plan, which may name operations no longer in the instance, to the planner and the budget count; `dispatch_planner` ignores it and the count only looks up known operations, so it is safe for the rules; check again for CP-SAT and the GA warm start (5.1). |
| 2026-11-23 | 2.2b | sim (this commit) | `mes_bridge.runner`: event server (`POST /events`, shared token), `Runner` (events merged per step; next wake = earliest of OVERDUE, PLANNED_START, period, safety poll 5 min; a failing step is logged and retried), CLI; `MesClient` re-login on 401. 12 tests (the event server on a local socket). Gates: bridge 85 passed + 1 skipped, simulation 1811 passed. Findings: (w) the MES recomputes a running step's expected end as now + 15 min at the floor on every export, so OVERDUE wakes about every 15 min while a step overruns, not every minute as in the DES (13 §3); fine for a proposal, the safety poll bounds it anyway; (x) the bridge listens on 127.0.0.1 by default; the MES must reach it, so a deployment sets `--host` and the MES's `SCHEDULER_URL` (2.3). |
