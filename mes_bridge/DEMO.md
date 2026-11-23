# Showcase: the scheduler in the MES

A demo of the integration: three orders arrive, the scheduler (CP-SAT) plans them with breaks, and the MES shows the
plan in My plan, the dashboard and Team plan. Then you change things (assignments, the break window, a machine, a
started or overrunning task, the scheduler going down) and watch the plan follow.

Everything runs locally against a **demo database** (`mes_demo`), never `mes_db`. The MES of this branch runs on
port **8091**, the bridge on **8766**, and the frontend on **5173**. Your normal MES on 8080 is not touched. Stop
any other frontend on 5173 first, because the backend allows CORS only from `localhost:5173`.

## 0. The two worktrees

| What | Path | Branch |
|---|---|---|
| Bridge (this repo) | `C:\Users\pauls\code\fidentis\simulation\.claude\worktrees\planner-api-loop-design-e38416` | `claude/planner-api-loop-design-48aa31` |
| MES | `C:\Users\pauls\code\fidentis\PROD_DATA_MES_V2____postgres-dbms\.claude\worktrees\planner-api-loop-design-d4a13c` | its `claude/planner-api-loop-design-*` branch |

They are ordinary folders, so `cd` into them; no checkout is needed. To work on them in an editor, open each folder.
Once, if needed: `uv sync` in `mes_bridge\` and in the MES `backend\`, and `npm install` in the MES `frontend\`.

```powershell
$SIM = "C:\Users\pauls\code\fidentis\simulation\.claude\worktrees\planner-api-loop-design-e38416"
$MES = "C:\Users\pauls\code\fidentis\PROD_DATA_MES_V2____postgres-dbms\.claude\worktrees\planner-api-loop-design-d4a13c"
```

## 1. Start everything with one command

```powershell
cd $SIM\mes_bridge
.\demo.ps1            # first run: creates the demo database, then starts everything
.\demo.ps1 -Reset     # a fresh demo database, then starts everything
.\demo.ps1 -Solver rule   # the dispatching rule (SPT) instead of CP-SAT
.\demo.ps1 -Stop      # stops the three servers
.\demo.ps1 -Drop      # stops them and drops the demo database
```

The script opens one Windows Terminal window with three panes (MES on the left, bridge top right, frontend bottom
right), waits until the frontend answers, and opens http://localhost:5173. It refuses to start while a port is
busy. If the MES worktree is somewhere else, set `$env:MES_WORKTREE` first.

On the first run (or with `-Reset`) it creates the demo database `mes_demo` (`tests/e2e/demo_db.py setup`):
- migrates it and seeds the admin (`admin` / `admin`)
- three active workers: **Timo, Lukas, Quirin**, each with password `fidentis_<Name>`, e.g. `Timo` / `fidentis_Timo`.
  The other seeded workers are retired.
- shift: **08:00 to 17:30** (8 h 30 min including the break), overtime up to 19:30 (120 min)
- one printer (**Printer 1**) and one mill (**Mill 1**)
- the `scheduler` service account with a generated password
- three orders that arrived today, each on its own print, due in 2, 3 and 4 days:
  - D001: two secondary teeth
  - D002: two teeth with both a primary and a secondary part, so the PRIMARY lane and the QM join show
  - D003: three secondary teeth

The generated secrets go to `%TEMP%\mes_demo_secrets.ps1`.

## 2. By hand: three terminals

This is what the script does, in case you want to restart one piece. Dot-source the secrets in terminals 1 and 2
first: `. "$env:TEMP\mes_demo_secrets.ps1"`.

**Terminal 1: MES backend (this branch)**
```powershell
. "$env:TEMP\mes_demo_secrets.ps1"
cd $MES\backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8091
```

**Terminal 2: the bridge**
```powershell
. "$env:TEMP\mes_demo_secrets.ps1"
cd $SIM\mes_bridge
.\.venv\Scripts\python.exe -m mes_bridge.runner --url http://127.0.0.1:8091 --port 8766 --state-dir $env:TEMP\mes_demo\state --config tests\e2e\demo_cpsat.json
```
It may start before the MES; it waits for it. Within about 20 s it prints `BOUND start ...: 1 published` and the
same line for FREE. `demo_cpsat.json` selects CP-SAT (10 s per solve) and a policy that reschedules completely when
a repair shifts a step by more than 60 min. Leave out `--config` to see the dispatching rule (SPT) instead. The
bridge writes every decision to `$env:TEMP\mes_demo\state\<variant>\decisions.jsonl`: REPAIR or REPLAN, why, how
many steps moved, the solver's status. That file is handy to show next to the UI.

**Terminal 3: frontend**
```powershell
cd $MES\frontend
$env:PUBLIC_API_URL = "http://localhost:8091"
npm run dev
```
Open http://localhost:5173.

## 3. The showcase, step by step

Use two browser windows: one as **admin** (planner view) and one as a worker, e.g. **Timo** (`fidentis_Timo`).

1. **The plan exists.** As Timo, the dashboard shows "Your work, Timo": the next step, today's ribbon with the
   break hatched, and what comes after. *My plan* lists the next days with times, breaks, "Ready" / "Waiting
   (after X, expected done hh:mm)", the machine, "machine runs alone until", and the open time per day. As admin,
   go to *Planning → Team plan*: today and the next 2 days per worker. Switch *Group by* to Machine to see the
   printer and the mill. Nothing is planned before 08:00; work runs past 17:30 only as overtime (up to 19:30).
2. **Breaks are planned.** Every worker gets one break per day in the window from *Planning → Settings* (default
   12:00, 60 min), and no task is planned over it. Change the window to e.g. 12:30–13:30 with 45 min and press
   *Save break*. Within about 15 s My plan shows the new break and the tasks move around it (the setting wakes the
   scheduler, and a new calendar is a complete rescheduling).
3. **Assignments: Plan vs. Free plan.** Open an order (*Orders* → the order → its planning tab) and assign a step
   to someone the plan did not choose. The scheduler re-solves within seconds: the **Plan** (BOUND) follows the
   assignment (a pin). The **Free plan** (FREE) is what the scheduler would do without assignments. In Team plan,
   *Suggestions from the free plan* lists that step ("Lukas instead of Timo · 1:30 h earlier"). **Accept** writes
   the free plan's choice as the assignment, the plan follows, and the suggestion disappears. Suggestions appear
   only for steps that have an assignment, and only for steps in the Team plan's window (today + 2 days).
4. **A worker starts a step.** As Timo, press *Start* on the dashboard. This opens the queue's start dialog
   (pick the parts). The step moves to "Now" with *Resume*, and the plan shows it as running from now on. A step
   started early or on time moves nothing (the repair keeps planned gaps).
5. **An overrun.** Start the print (*Prepare AM system for print*) and hand it off with a much longer run than
   planned. The print's successors (powder removal, cleaning, …) move behind its new end. If a step shifts by more
   than 60 min, the policy triggers a complete rescheduling, which often wins most of the delay back by
   reassigning work. `decisions.jsonl` shows the REPAIR (e.g. +1140 min) followed by the REPLAN.
6. **A machine goes down.** *Equipment* → *Printer 1* → set status DOWN. With only one printer there is nowhere
   to move the prints: they stay on Printer 1 and the bridge logs a warning in its pane. To show the move, first add a
   second printer under *Equipment* (type AM system), then set Printer 1 DOWN: every print that has not started
   moves to the new printer within seconds. A print already running stays (the MES binds its job to that printer).
   Set it back to available afterwards.
7. **The scheduler goes down.** In Settings set *Scheduler offline after* to 1 min, then stop the bridge pane
   (Ctrl+C). After a minute, My plan, the dashboard and Team plan say *Scheduler offline · last schedule from
   hh:mm*, and the plan comes from the MES's own rules. Restart it (arrow up, Enter): the notice disappears and the plan is the scheduler's
   again. Set the threshold back to 30 afterwards.
8. **Solver choice (optional).** Stop the bridge, restart it without `--config` (dispatching rule) or with a copy of
   `demo_cpsat.json` with `"kind": "ga"`, and compare the plans in Team plan.

## 4. The same, checked automatically

`tests/e2e/demo_scenario.py` runs steps 1–7 over the MES's HTTP API with 22 checks. It creates its own database
(`mes_demo_scenario`), starts the MES (8091) and the bridge (8766), and cleans everything up. Stop the demo servers
first (the ports must be free).

```powershell
cd $MES\backend
uv run python $SIM\mes_bridge\tests\e2e\demo_scenario.py
```

Expected: `22 / 22 checks passed` in about 4 minutes. `--keep` leaves the MES and the database running afterwards.

## 5. Known limitations (worth saying in a demo)

- Breaks: the MES does not record when a worker actually took a break. The bridge assumes today's break was taken
  at the earliest clear start in its window.
- A task left open in the MES over the whole break window past the day's end makes CP-SAT infeasible (rule C14^f).
  The bridge then falls back to the dispatching rule for that solve. Tasks running unattended (a handed-off print)
  are not affected.
- Bound and free are two independent solves. Without assignments they may differ arbitrarily, which is why
  suggestions are limited to assigned steps.
- Cleaning and sand blasting are serial batches across orders. My plan shows one row per order with the batch's
  time, so two "Clean part" rows at the same time are one batch, not two parallel tasks.
- The bridge republishes its unchanged plan as a keep-alive when the last publication is older than half the
  staleness setting (and once after each restart), so a quiet but healthy scheduler is never shown as offline. Cost:
  one extra schedule row per variant every 15 min at the default 30 min.
