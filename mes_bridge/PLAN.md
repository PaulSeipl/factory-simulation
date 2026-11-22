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
- [ ] Local MES backend on port 8080 with its database (needed from slice 1, task 1.6).

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
- [ ] 1.3 MES: `scheduler` service user (seeded, bearer login) and the `schedule` tables (append-only, variant,
  `snapshot_as_of`, steps, breaks) with migration; `PUT` / `GET /planning/schedule`, write restricted to the
  service user. Tests incl. one negative test per validation rule.
- [ ] 1.4 MES: `GET /planning/problem` for the SECONDARY lane (decision 11), one read transaction, reusing the
  node gathering of `services/planning/plan.py`. Tests.
- [ ] 1.5 Bridge: hand-written models + contract test against a copied `openapi.json`; problem → `Instance`
  (schema of `src/simulation/model/instance.py`) + `Snapshot`; id map instance ids ↔ MES node keys; time epoch
  (decision 17: `Calendar.origin = 0`, the default 480 would shift everything by 8 h without an error). Unit
  tests on a recorded problem response.
- [ ] 1.6 Bridge: one-shot command: fetch problem → `spt` → `check_schedule` → `PUT`. Integration test against
  the local MES.
- [ ] 1.7 MES: `GET /planning/plan` serves the latest schedule with the facts overlay, `source` field, fallback to
  `fill.py` when stale. Regenerate the client. Team plan shows it (design pass first). Docs: `architecture.md`
  §8a, `CLAUDE.md` plan block.

### Slice 2: events and the controller

- [ ] 2.1 simulation (thesis): `Factory` Protocol (`snapshot`, `current_plan`, `current_breaks`, `update_plan`) in
  `control`; `adapt_plan` typed against it; `arrived` documented as "the instance changed". Zero-disturbance test
  green; protocol entry; `math/05` change log.
- [ ] 2.2 Bridge: `MesFactory` implementing it; long-running loop with `POST /events` (shared token), event queue
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
- Does the seed data hold orders past `DATA_PREP_SECONDARY`? If not, the integration tests seed them.
- How does a rework clone or a repeated step map to a unique `Operation.id` within an order?
- Do scrap and the rework clone change a `WorkTask` or `Equipment` row? If not, the listener misses them and
  only the safety poll catches them; extend the listener to those rows.

## Blocked

(none)

## Log

PR comments read until: 2026-11-22T22:41Z

| Date | Task | Commits | Findings |
|---|---|---|---|
| 2026-11-22 | design | — | Design interview done; spec, ADR 0003 and this plan written, not committed. |
| 2026-11-22 | 1.1 | MES fe447ab, sim b711ade | Docs committed, branches pushed, draft PRs MES #160 and sim #1 opened. Both branches contain their `main`. Local MES on 8080 is down (needed from task 1.6). |
| 2026-11-22 | 1.2 | sim (this commit) | `mes_bridge/` uv project (editable path dep, own `uv.lock`; root `uv.lock` unchanged), `CHANGELOG.md`, AST boundary test + detector self-test. Gates: simulation 1807 passed, bridge 2 passed. No PR comments. |
