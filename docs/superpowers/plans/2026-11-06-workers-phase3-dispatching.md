# Workers, phase 3: dispatching rule with workers and calendar — plan

**Goal:** the list-scheduling rules (`planners/dispatching.py`, all sequencing × assignment combinations) produce
plans with worker shares, machine-less operations and the work calendar; every rule plan passes the checker
(C1–C14) and, replayed in the DES without disturbances, equals itself.

**Spec:** `docs/superpowers/specs/2026-11-05-workers-shifts-design.md` §7 (rule: breaks at 12:00, no overtime, a
simple baseline). Working style: one task at a time, tests, result, approval (`CLAUDE.md`). CP-SAT, repair and
rescheduling keep their guard until phase 4.

## Behavior (decisions; mine marked)

1. **Worker choice (spec §7):** for every share the qualified worker who allows the earliest start, ties by least
   worker load, then lowest index. A run's setup and removal choose their workers independently (user: may differ).
2. **Earliest start of a candidate (mine):** the smallest $t \ge$ ready time and machine free time such that every
   share interval (prefix/whole from $t$, suffix ending at $t + p$) lies within one working day in
   $[h^{\mathrm{S}}, h^{\mathrm{E}}]$ (no overtime), outside the break $[h^{\mathrm{B}-}, h^{\mathrm{B}-} + L^{\mathrm{B}})$,
   and after its worker is free. Found by moving $t$ forward until all conditions hold (each step jumps to the next
   possible time; finite because the calendar repeats weekly). Machines run at any time: an unattended print can
   run overnight.
3. **Non-delay as before:** among all candidates, the earliest start wins; the sequencing rule breaks ties.
   ~~Workers are scheduled append-only like machines~~ **Changed in task 2 (mine, 2026-11-06):** workers are booked
   into gaps of their busy intervals; machines stay append-only. Append-only would block the worker of an oven
   removal (suffix, booked when the oven run is planned) for the whole oven program.
4. **Runs (C8, C9):** setup → main → removal on one machine, each part at its own earliest start; the removal of a
   print that ends at night waits until 08:00, the printer stays blocked (allowed by C9).
5. **Batches:** greedy as today; the batch's shares are planned once.
6. **Breaks (spec §7):** every worker breaks at 12:00 on every working day with shares; the rule never schedules a
   share into 12:00–13:00. The breaks are returned by a helper `default_breaks(ci, plan)` (mine: `dispatch` keeps
   its return type `list[Assignment]`; how breaks travel through the planner interface is a phase 4 question).
7. **Assignment rules (least load, ECT) stay machine-based** (mine): they do not see worker delays; recorded as a
   limitation of the baseline.

## Tasks

### Task 1: Calendar availability helper
- `calendar.next_start(cal, t, length, latest)`: earliest $s \ge t$ with $[s, s + \text{length})$ inside one working
  day's $[h^{\mathrm{S}}, \text{latest}]$ and not overlapping the break window start $[h^{\mathrm{B}-}, h^{\mathrm{B}-} + L^{\mathrm{B}})$.
- Tests by hand: within the morning; pushed past the break; pushed to the next morning; Friday → Monday; a length
  longer than a shift half (before/after the break) → raises (cannot be planned without overtime or preemption).

### Task 2: Shares and machine-less operations in the rule (no calendar)
- Remove the dispatching guard; worker state per worker (free time, load); rules 1, 3, 5 and runs (rule 4 without
  calendar); machine-less operations (no machine, only workers).
- Tests: hand plan on `toy-workers.json` (calendar ignored by removing it in the test) and on the carrier instance
  with the oven batch; all 15 rule combinations pass the checker and the zero-disturbance replay.

### Task 3: Calendar in the rule
- Rule 2 with `next_start` (no overtime), runs waiting for the morning, `default_breaks`.
- Tests: by hand: a share pushed past 12:00–13:00; a print ending at night with removal at 08:00 next day and the
  printer blocked; Friday → Monday; all rule combinations on `toy-workers.json` and on a calendar version of the
  carrier instance pass the checker (with `default_breaks`) and the zero-disturbance replay; tardiness in days.

### Task 4: From a snapshot
- Frozen operations keep their workers; their shares occupy the workers; a pending oven removal (worker `None` in
  the snapshot) gets a worker by rule 1.
- Tests: snapshot from the DES mid-run, rule plan from it passes the checker against the snapshot (C6, C7).
- Could move to phase 4 together with repair; kept here because the rule planner is the first rescheduling
  planner to support.
- **Done without calendar (2026-11-08).** With a calendar it raises: breaks do not travel through rescheduling
  (snapshot without breaks, planner returns only assignments, `execute` starts the DES without breaks). Needs its
  own task: realized and pending breaks in the snapshot, the rule's breaks after a snapshot (a postponed break
  today instead of the fixed 12:00), breaks in the planner interface and in `execute`.

Each task: `math/11_dispatching-rules.md`, `math/04_workers.md` §5; protocol entry.

## Decided
- **19:30 in execution** (user 2026-11-06): hard in the plan (C13); in the DES a share running past 19:30 is
  finished and counted as an overrun, not interrupted (an interrupted operation is out of scope). No DES change.
