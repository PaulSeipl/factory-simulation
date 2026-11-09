# Breaks through rescheduling, and pending removals after an overrun — plan

**Goal:** a plan revised from a snapshot of a calendar instance with workers carries its breaks, respects the
breaks already started, and is accepted by the DES; the dispatching rule plans from such a snapshot. Also fixes the
crash found 2026-11-08: a pending oven removal whose only qualified worker is still on an overrunning share.

**Context (found 2026-11-08, protocol (19)):**
- `Snapshot` has no breaks. `Planner` returns `list[Assignment]`. `execute` creates `Simulation(ci, plan, scenario)`
  without breaks and `ExecutionResult.breaks` stays empty. `Simulation.update_plan` checks without breaks. On a
  calendar instance with workers every one of these reports C14 (missing break).
- The rule's fixed 12:00 break (`next_start`) is wrong on the snapshot's day: the DES may have postponed a break
  (e.g. to 12:20), so a share planned at 13:00 overlaps it.
- `tests/test_dispatching_workers.py::test_pending_removal_without_a_free_worker_raises`: one worker, polishing
  overruns, snapshot at 8: the oven's pending removal [8, 9) has no free worker; its time is fixed by C7, so
  `dispatch` raises. The state is reachable in an ordinary run, so a rescheduling run would crash.
- `execute` with workers is blocked anyway: repair still rejects workers (phase 4). The full `execute` path is
  therefore tested in phase 4; here the pieces are tested through `Simulation`, `snapshot` and `dispatch` directly.

Working style as before: one task at a time, tests, result, approval; `math/` with the Edit tool.

## Decisions (1 open for the user, my recommendation first; 2 and 3 decided)

1. **How breaks travel with a plan.** (a) *Recommended:* a planner returns `(assignments, breaks)`. CP-SAT will
   choose break times in phase 4 (spec: breaks are decision variables), so the interface must carry them anyway.
   Touches `Planner`, `dispatch_planner`, `cpsat_planner`, `repair`, `_reschedule`, `update_plan`. (b) Planners
   keep returning assignments and a separate break placer derives the breaks; cheaper now, but blocks CP-SAT
   choosing breaks.
**Principle for 2 and 3 (user, 2026-11-08):** a planner must never cause a postponed break past the window or an
oven overstay; if the frozen part forces it (a disturbance: an overrun or a late start), there is nothing else to
do, and the plan takes the shortest possible delay. Arises only from disturbances: the rule keeps shares out of
12:00–13:00, and the DES takes a due break as soon as the worker is free, so a break is still pending after 13:00
only if the worker's frozen share runs past 13:00.

2. **Today's break when it cannot start in the window any more** — *decided by the principle:* a **forced
   postponement**. Against a snapshot the checker accepts a break after $h^{\mathrm{B}+}$ only if the worker's
   frozen share covers $h^{\mathrm{B}+}$ and the break starts exactly at that share's (expected) end. Counted by the
   metric `break_postponement`. A planner cannot postpone a break past the window on its own.
3. **Pending removal with no free worker** — *decided by the principle:* a **forced overstay**. The planned end of a
   running operation whose suffix has not started may be later than the snapshot's expected end only if no
   qualified worker is free of **frozen** shares at the expected suffix interval; then the suffix starts at the
   earliest time a qualified worker becomes free of frozen shares, and the operation ends with it (C7 relaxed for
   exactly this case, checked as "forced and shortest"). Without a disturbance the planner must keep the expected
   end and find a free worker (C7 as now). The DES already behaves like this (soft suffix, OVERSTAY). The rule
   books pending suffixes before any new share, so only frozen shares can block them.

## Behavior (with the recommendations)

- **Snapshot:** `Snapshot.breaks`: the breaks started at or before $t$, with their realized starts (a break
  running at $t$ included). Planned breaks not yet started are not in the snapshot: the planner decides them anew.
- **Checker against a snapshot** (C7 for breaks, C6 for breaks): every break of the snapshot appears unchanged;
  every other break starts at or after $t$; decision 2 for forced postponements.
- **Rule after a snapshot** (`dispatch`, `default_breaks(ci, plan, snapshot=None)`):
  - Days after the snapshot's day: as now (break at 12:00, shares kept out of 12:00–13:00).
  - The snapshot's day, per worker: a break already started is booked as a busy interval and no new one is
    placed. Otherwise the break starts at $\max(t,\ h^{\mathrm{B}-},\ \text{end of the worker's frozen share})$,
    within the window or as a forced postponement, and is booked as a busy interval before any new share.
  - So on the snapshot's day shares are kept out of the worker's actual break, not out of 12:00–13:00.
  - `dispatch` returns the breaks together with the assignments (decision 1); `default_breaks` stays for the plan
    from $t = 0$ or becomes its internal helper.
- **Pending removal:** decision 3: at the expected suffix interval if a qualified worker is free; otherwise at the
  earliest time a qualified worker is free of frozen shares. The operation's end and its successors move with it;
  for a batch, all members end together.
- **DES:** `Simulation(ci, plan, scenario, breaks)` as now; `update_plan(plan, breaks)` keeps the started breaks
  and replaces the pending ones. A running operation whose suffix has not started takes the new planned end
  (decision 3).
- **execute:** passes the start plan's breaks to the `Simulation`, hands the planner's breaks to `update_plan`,
  and fills `ExecutionResult.breaks` with `sim.realized_breaks()` (currently left empty).

## Tasks

### Task 1: Snapshot breaks and the checker
- `Snapshot.breaks` filled by `snapshot()` from the DES break state. Checker against a snapshot: started breaks
  unchanged, other breaks at or after $t$, the forced postponement of decision 2.
- Tests by hand: snapshot at 12:30 with A's break realized at 12:20 (from `toy-workers` with Gegenbetten slowed);
  one negative test per new check (started break moved, a new break before $t$, a postponement past the window not
  forced by a frozen share, a forced postponement that starts later than the frozen share's end).

### Task 2: Pending removal (decision 3)
- C7 relaxed for a running operation with a pending suffix (checker, `math/05`, `math/04` C7 note); the rule
  books that suffix at the earliest free time; the DES takes the new end.
- Tests: `test_pending_removal_without_a_free_worker_raises` becomes the hand case (removal at 9, oven ends at 10
  instead of 9, mill runs shift by one minute). Negative tests → C7: the end moved earlier; moved for an operation
  whose suffix has started; moved although a qualified worker was free (not forced); moved later than the earliest
  free time (not shortest).

### Task 3: Planner interface and DES plan update with breaks (decision 1)
- `Planner` returns `(assignments, breaks)`; `dispatch_planner`, `cpsat_planner` (no breaks yet, empty: CP-SAT
  still rejects workers), `repair` (passes the current breaks), `_reschedule`, `update_plan(plan, breaks)`,
  `execute` (start breaks, realized breaks in `ExecutionResult`).
- Tests: every existing rescheduling test unchanged in its results (the worker-free instances carry no breaks);
  `update_plan` keeps a started break and replaces a pending one; `ExecutionResult.breaks` equals the realized
  breaks on a calendar instance without rescheduling.

### Task 4: The rule from a snapshot with a calendar
- Remove the guard; the snapshot's day as above; `dispatch` returns breaks.
- Tests by hand: snapshot at 12:30 with A's break at 12:20 realized: A's next share at 13:20, not 13:00; snapshot at
  11:00 with A on a frozen share until 12:40: break at 12:40, next share at 13:40; snapshot at 13:30 with B's break
  not taken and B on a frozen share until 13:45: forced postponement at 13:45. Sweep: every rule combination from
  10 snapshots × 5 disturbed seeds on `toy-workers` and the night carrier instance passes the checker against the
  snapshot with the returned breaks, and `Simulation.update_plan` accepts it.

Each task: `math/04_workers.md`, `math/05_rescheduling-frozen-part.md`, `math/11_dispatching-rules.md`,
`math/13_des.md` as affected; **symbol-clash check of `math/` against `notation.md`** (user todo 2026-11-08: after
every task, every phase, and at the end); protocol entry. Thesis: no affected section written yet (checked 2026-11-08:
`seipl27/Text/kapitel1.tex` is empty).

## Not in this plan
- Repair with workers and the full `execute` path on calendar instances (phase 4).
- CP-SAT choosing break times (phase 4).
