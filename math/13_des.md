# 13 Discrete-event simulation (DES)

Files `1x` describe solution methods and the simulation; files `0x` describe model components.

## 1. Prose description

The DES represents the factory over time. It receives a **plan** from a planner (dispatching rules, CP-SAT, later the GA) and executes it event by event. It **decides nothing**: machine, order per machine and start times come from the plan. Planning and execution are strictly separated; the planner will only see a snapshot of the DES state, never the sampled disturbances (`CLAUDE.md`).

**Version 3 (current): execution of a plan under disturbances.** Realized processing times and start offsets come from a disturbance scenario ([22](22_scenarios.md)). The DES keeps the plan it has: when an operation runs longer, later operations wait (shifted to the right); when it runs shorter, nothing moves forward. Changing the plan (repair, complete rescheduling) is the job of the planning tool ([05](05_rescheduling-frozen-part.md)): between processing the events of a time point and starting operations it reads the snapshot and may hand the DES a new plan. Without a scenario (or with $\sigma = 0$ and no start offsets) the realized schedule equals the plan, with and without the planning tool (zero-disturbance test).

Version 1 (replay without disturbances, error on any deviation) is the special case without a scenario.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

- $\bar m(o)$, $\bar S_o$: machine and start of $o$ in the (current) plan
- $\Delta_o$: start offset of $o$ from the scenario ([22](22_scenarios.md))
- $\hat S_o$, $\hat C_o$: realized start and completion of $o$ in the simulation
- $\hat p_o$: realized processing time, $\hat p_o = \max(1, \operatorname{round}(p_{o,\bar m(o)}\, \varepsilon_o))$ with the disturbance factor $\varepsilon_o$ of the scenario ([22](22_scenarios.md)); without a scenario $\hat p_o = p_{o,\bar m(o)}$
- $\operatorname{prev}(o)$: the operation planned directly before $o$ on $\bar m(o)$ (by planned start), if any

## 3. Events and execution semantics

**Carriers and runs** ([03](03_carriers.md)): carrier and run operations are ordinary operations of the compiled graph, so the event logic is unchanged. A run blocks its machine between its main operation and a waiting removal because the DES keeps the planned order per machine: the next operation on the machine is the removal, nothing else may start before it (test `test_late_removal_blocks_the_printer`).

**Batches** ([03](03_carriers.md)): operations of a batch step planned on one machine with the same start start jointly once all are ready; the largest late offset among them delays the batch; their duration does not deviate (fixed program).

**Plan validation.** Before the run, the plan is checked with the feasibility checker (C1–C5, [01](01_basic-fjsp.md) §5). An infeasible plan raises `PlanNotExecutable` with all violations. Without this check, waiting would silently repair a broken plan (e.g. two overlapping operations would simply run one after the other).

**Execution rule.** Every operation $o$ runs on $\bar m(o)$, in the planned order per machine (no overtaking). It is **released** to the shop floor at $\bar S_o + \min(\Delta_o, 0)$, with the start offset $\Delta_o$ from the scenario ([22](22_scenarios.md)); if the planning tool updates the plan, $\bar S_o$ may still change until then, and the release time moves with it. A released operation is **ready** as soon as its predecessors are finished, its machine is idle, it is next in the planned order of its machine, and $t \ge r_{k(o)}$ (an early start must not precede the release of the order). Let $R_o$ be the first time at which $o$ is released and ready. Then

- $\Delta_o \le 0$ (on time or early): $o$ starts at $R_o$;
- $\Delta_o > 0$ (late): $o$ starts at $R_o + \Delta_o$. The worker comes $\Delta_o$ minutes late relative to the moment the operation could actually start, not relative to the planned start; meanwhile the machine stays reserved for $o$ (no overtaking). The start time is fixed once at $R_o$, so later plan updates cannot count the delay twice.

Without repair and with fixed $\bar S_o$:

$$R_o = \max\Big(\bar S_o + \min(\Delta_o, 0),\ \max_{(q,o) \in P} \hat C_q,\ \hat C_{\operatorname{prev}(o)},\ r_{k(o)}\Big), \qquad \hat S_o = R_o + \max(\Delta_o, 0), \qquad \hat C_o = \hat S_o + \hat p_o$$

**Why relative to readiness (decision 2026-10-30).** With the earlier rule (late release fixed at $\bar S_o + \Delta_o$), a late worker was absorbed whenever the operation had to wait anyway, and with repair, which moves $\bar S_o$ behind delayed predecessors, the offset was added on top of the predecessor delay: on mk01 ($q = 0.5$, $a = b = 5$) repair alone realized a makespan of 65 against 45 without repair. Relative to readiness, the delay of the worker acts the same with and without repair (on the same mk01 runs both modes now realize equal makespans), and it is not hidden by waiting time.

This keep-the-plan-and-shift-right reaction is the baseline that repair and rescheduling have to beat ([05](05_rescheduling-frozen-part.md)). With $\Delta_o = 0$ no operation starts before its planned start.

**Events** are kept in a priority queue (binary heap) ordered by $(t,\ \text{type},\ \text{insertion counter})$:

| Type | Priority at equal $t$ | Effect |
|---|---|---|
| COMPLETE | 0 | $\hat C_o = t$; machine $\bar m(o)$ becomes idle; the next operation of the planned order on that machine may start |
| LATE_START | 1 | $R_o + \Delta_o$ reached for a late operation: marks the time point at which the start step starts it |
| PLANNED_START | 2 | $\bar S_o + \min(\Delta_o, 0)$ reached: $o$ is released; a PLANNED_START event moved by a plan update is stale and skipped (named DUE before 2026-10-30; renamed to avoid confusion with due dates, [06](06_due-dates.md)) |
| WAKE | 4 | time point requested by the planning tool (`wake_at(t)`, e.g. periodic rescheduling, [05](05_rescheduling-frozen-part.md) §3); no effect in the factory |
| OVERDUE | 3 | expected end of a running $o$ reached ($\hat S_o + p_{o,\bar m(o)}$ with the planned duration, then every minute): if $o$ is still running, the next OVERDUE is scheduled at $t + 1$; if it has completed, the event is stale |

**OVERDUE.** The planning tool only acts at time points with an event. Without OVERDUE, an operation running past its planned end would only be noticed at the next unrelated event (in the worst case at its own completion), while the snapshot assumes it ends at $t + 1$. The OVERDUE event creates a time point exactly when that assumption fails: first at the planned end, then every minute, matching the expected end $\max(\hat S_o + p_{o,\bar m(o)}, t + 1)$ of the snapshot (§6). It changes nothing in the factory and carries no scenario information: it is scheduled from the planned duration, and that an operation is still running at $t$ is observable on the shop floor (an MES reports it). A better estimate of the remaining time (e.g. conditional on the distribution of the factor) would change the snapshot's expected end and the OVERDUE times together; not implemented.

Per time point $t$ the DES

1. processes **all** events at $t$,
2. gives the planning tool the chance to send a new plan (`update_plan`): it is checked against the frozen part (C1–C7) and the PLANNED_START events of operations not yet released are moved,
3. makes one start step: every released operation that is ready starts at $t$ (a late one: schedules LATE_START at $t + \Delta_o$ the first time it is ready, and starts when that time is reached); a COMPLETE event is scheduled at $t + \hat p_o$.

A start cannot enable another start at the same $t$ (it occupies a machine and completes at $t + \hat p_o > t$), so one pass suffices. Processing all events of a time point before repair and start step makes the result independent of the order in the heap among equal times: a machine finishing at $t$ is always free for an operation released at $t$ (touching intervals $[S, C)$, as in C5), and the repair sees a consistent state.

**Workers** ([04](04_workers.md), phase 2 task 1; calendar effects follow). Every share $\eta$ is served by its planned worker, in the planned order per worker (sorted by the planned start of the share; no overtaking, as for machines). An operation starts only when, in addition, the workers of its whole share and its prefix are free and this share is next in their order; the worker is busy for the realized share length (event SHARE_END). An operation with a suffix (oven removal) raises SUFFIX_DUE when its machine part ends ($t + \hat p_o - \hat a^{\mathrm{suf}}_o$); the removal starts as soon as its worker is free and next, and the operation (all members of its batch) completes $\hat a^{\mathrm{suf}}_o$ later. Waiting minutes are logged as OVERSTAY (soft suffix, user 2026-11-05); the machine stays blocked meanwhile. A batch's shares count once (its first operation carries them). Operations without machine wait only for predecessors, release and workers. Event priorities at equal time: COMPLETE, SHARE_END, SUFFIX_DUE, LATE_START, PLANNED_START, OVERDUE, WAKE, so a worker free at $t$ can start a share at $t$.

**Work calendar** (phase 2 task 2; user rules and own defaults, 2026-11-05). With a calendar, a worker starts a share only (i) on a working day at or after $h^{\mathrm{S}}$, (ii) not during or while due for a break, and (iii) if the *planned* share length fits before $h^{\mathrm{E}} + \overline{\mathrm{ot}}$ (planned, not realized: no leakage); otherwise a WAKE event is pushed for the next possible time (next shift start, end of the break), so Friday 19:20 waits until Monday 08:00. A share that then runs past $h^{\mathrm{E}} + \overline{\mathrm{ot}}$ is finished, not preempted (overrun, visible as C13 on the realized schedule). Planned breaks are taken at their planned start; a worker busy then takes it right after the current share (individual postponement, possibly beyond the window: visible as C14). The DES invents no break for a day without a planned one (the planning tool plans breaks; a missing break on such a day shows as C14). Realized breaks are returned with the result (`SimResult.breaks`), and realized share lengths with each assignment (`Assignment.share_lengths`), so that the checker evaluates the realized worker times. Overtime is read off the realized schedule (metrics, task 4).

**Swap rule** (phase 2 task 3; user 2026-11-05, tie-break own). When a share is due (the operation could start, or its machine part has ended) and its planned worker is busy (on a share or a break), a worker $z' \in W_o$ takes it if $z'$ is free now, may work now (shift window, no break due) and its next planned share starts no earlier than $t + a_\eta$ ($a_\eta$ the planned share length; planned values only, no leakage). Among several, the one with the most room before its next planned share, then the lowest index. The share moves from the planned worker's order to the front of $z'$'s remaining order, all members of a batch get $z'$, and the DES writes $z'$ into its current plan (`current_plan()`), so a later repair sees the real state. Without disturbances no worker is busy at a due share (the plan is feasible), so the rule never fires and the zero-disturbance test holds. It also applies to the oven removal and can thereby avoid an overstay. Logged as SWAP (share kind, planned and actual worker).

The log contains one START record (actual start) and one COMPLETE record per operation, and an OVERSTAY record (minutes) per delayed removal; PLANNED_START, LATE_START and OVERDUE events are internal. Decisions of the planning tool (REPAIR, REPLAN) are recorded by the planning tool ([05](05_rescheduling-frozen-part.md)).

## 4. State

`SimState` holds everything that changes during the run, as plain containers (copyable for later use, e.g. MCTS):

| Field | Meaning |
|---|---|
| `t` | simulation clock |
| `events`, `seq` | event heap and insertion counter |
| `planned_start[o]`, `planned_end[o]` | current plan $\bar S_o$, $\bar C_o$ (changed by plan updates) |
| `planned_start_at[o]` | time of the valid PLANNED_START event of $o$, none once processed |
| `running[m]` | operation running on machine $m$, or none |
| `next_pos[m]` | position of the next operation in the planned order of machine $m$ |
| `released` | operations released to the shop floor but not started |
| `start[o]`, `end[o]` | $\hat S_o$, $\hat C_o$ once known |

The realized durations, start offsets and the planned order per machine are fixed for the run and not part of the state. Workers and carriers (plates) enter together with their model components (`04_workers`, [03](03_carriers.md)).

## 5. Implementation in code

`simulation.sim.des.Simulation(ci, plan, scenario)` with `process_events()`, `start_operations()`, `snapshot()`, `current_plan()`, `update_plan(plan)`, `realized()`; `replay(ci, plan, scenario=None) -> SimResult(schedule, log)` and `run(ci, plan, scenario, until)` execute without a planning tool; `log` is a list of records `{t, type, order_id, op_id, machine}`, written as JSON Lines with `simulation.io.json_loader.write_jsonl`.

Hand-computed example (test `test_longer_operation_shifts_its_successors_and_keeps_the_machine_order`): the hand-checked plan of `toy-dag-3x4` (makespan 11), with factor 2 on b1 (all other factors 1):

| Op | Plan | Realized | Why |
|---|---|---|---|
| b1 | M1 [3, 5) | M1 [3, 7) | $\hat p = 2 \cdot 2 = 4$ |
| b2 | M2 [5, 8) | M2 [7, 10) | waits for predecessor b1 |
| b3 | M1 [5, 9) | M1 [7, 11) | waits for b1 (predecessor and machine) |
| b4 | M4 [9, 11) | M4 [11, 13) | waits for b3 |
| c2 | M2 [8, 10) | M2 [10, 12) | could start at 8 (M2 idle, c1 done), but b2 is planned before it on M2 |
| others | | unchanged | |

Realized makespan 13. With factor 0.5 on a1 instead ($\hat p = \operatorname{round}(1.5) = 2$), a1 ends at 2, but b1 still starts at its planned 3 on M1.

Tests (`tests/test_des.py`):

- Zero-disturbance: for every instance (2 toys, mk01–mk10), the best dispatching plan and a CP-SAT plan replay exactly and keep their makespan; a scenario with $\sigma = 0$ gives the same result as no scenario.
- The hand-computed example above and the faster-operation case.
- With random scenarios ($\sigma = 0.3$, 5 seeds, all instances): the realized schedule satisfies C1, C3, C4, C5 (C2 differs by design: $\hat p_o \ne p_{o,m}$), every operation stays on its planned machine, starts no earlier than planned, and the order per machine is the planned one.
- One negative test per plan violation (C1 missing/duplicate/ineligible, C2 wrong duration, C3, C4, C5): rejected before the run.
- COMPLETE before START at equal time; event log: one START and one COMPLETE per operation, in time order; JSON Lines roundtrip.

Zero-disturbance result (version 1, notebook, one run; CP-SAT with warm start and 5 s): makespan of the plan / of the executed plan.

| | toy-3x3 | toy-dag | mk01 | mk02 | mk03 | mk04 | mk05 | mk06 | mk07 | mk08 | mk09 | mk10 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| best rule | 11 / 11 | 12 / 12 | 42 / 42 | 30 / 30 | 204 / 204 | 70 / 70 | 183 / 183 | 73 / 73 | 150 / 150 | 523 / 523 | 311 / 311 | 227 / 227 |
| CP-SAT | 10 / 10 | 11 / 11 | 40 / 40 | 27 / 27 | 204 / 204 | 60 / 60 | 177 / 177 | 64 / 64 | 144 / 144 | 523 / 523 | 307 / 307 | 222 / 222 |

First robustness observation (notebook, one run, 30 scenario seeds per row, same seeds for both plans; CP-SAT with warm start and 5 s): planned makespan / mean realized makespan [min, max].

| | $\sigma$ | best rule | CP-SAT |
|---|---|---|---|
| toy-dag-3x4 | 0.1 | 12 / 12.4 [11, 14] | 11 / 11.2 [11, 13] |
| toy-dag-3x4 | 0.3 | 12 / 13.7 [11, 18] | 11 / 12.6 [10, 16] |
| mk01 | 0.1 | 42 / 43.5 [42, 46] | 40 / 41.9 [40, 44] |
| mk01 | 0.3 | 42 / 46.2 [42, 52] | 40 / 46.0 [40, 56] |
| mk06 | 0.1 | 73 / 75.7 [74, 78] | 63 / 66.5 [64, 68] |
| mk06 | 0.3 | 73 / 84.0 [77, 93] | 63 / 76.2 [70, 88] |

- The realized makespan is on average **above** the planned one although $E[\varepsilon_o] = 1$: delays propagate through precedence and machine order, while speed-ups are not passed on (no operation starts before its planned start), and the makespan is a maximum over paths. A realized makespan below the plan is possible only through a shorter last operation (toy, $\sigma = 0.3$: min 10).
- On mk01 with $\sigma = 0.3$ the advantage of the CP-SAT plan almost disappears (46.0 vs. 46.2) and its worst case is larger (56 vs. 52): a tight optimal plan has little slack. On mk06 the CP-SAT plan keeps a clear advantage. One run per row and no statistical test; this motivates replanning and robustness as thesis topics, it does not establish them.

## 6. Snapshot and frozen part

**Pausing.** `run(ci, plan, scenario, until=t)` executes the plan up to and including time point $t$ (all events at $t$ and the start step at $t$) and returns the state with clock $t$. `replay` is `run` to the end.

**Snapshot** at time $t$ (`simulation.sim.snapshot.snapshot(ci, plan, state)`): what a planner may see when it replans. Every operation is in exactly one of three groups:

| Group | Condition | In the snapshot |
|---|---|---|
| finished | $\hat C_o \le t$ | fixed: machine, $\hat S_o$, $\hat C_o$ (realized: they lie in the past) |
| running | $\hat S_o \le t < \hat C_o$ | **frozen**: machine and $\hat S_o$ fixed, expected completion $\tilde C_o$ |
| free | not started | absent: everything about it may be replanned |

**Workers in the snapshot** (phase 2 task 4). `FrozenOperation.machine` is `None` for operations without machine; their expected completion uses the fixed duration $p_o$. `FrozenOperation.workers` holds the actual worker of every started share and `None` for a share not started yet: the removal of a running oven (suffix) may still be given to another worker, by the swap rule or by rescheduling. After a swap the snapshot shows the actual worker. C7 keeps the workers of the started shares ([04](04_workers.md)). A running operation whose suffix has not started
is expected to end at $\max(\hat S_o + p_{o,\bar m(o)},\ t + a^{\mathrm{suf}}_o)$ instead of $t + 1$: its removal
cannot start before $t$ (the OVERDUE events stay on the $t + 1$ rhythm). A new plan may give that suffix another
worker and, if forced, a later end (C7$^o$); `update_plan` then takes the new worker for the share not started
(before 2026-11-09 the plan's worker was ignored for running operations). `FrozenOperation.share_lengths` (2026-11-09): per share the realized length if done (observed), at least until $t + 1$ for a running prefix, the planned length otherwise (no leakage). `Snapshot.breaks` holds the breaks started by
$t$ with their realized starts $\widehat{\mathrm{br}}_{z,\nu}$ (a postponed break with its actual start); breaks planned but not yet
started are not in the snapshot, the planner decides them anew (C6$^b$, C7$^b$, C14$^f$ in [04](04_workers.md)).

Finished and running operations together form the **frozen part** of the factory (later also started loads). The expected completion of a running operation uses the planned processing time, never the scenario:

$$\tilde C_o = \max\big(\hat S_o + p_{o,\bar m(o)},\ t + 1\big)$$

The second term covers an operation that has overrun its planned end: it is still running at $t$, so it cannot end before $t + 1$. The planner can see that the operation is running, so this is no leak. Operations that are due but waiting (e.g. for a delayed predecessor) are free.

**No information leakage.** The snapshot depends only on the past: finished operations (observed) and the starts and machines of running operations. A test changes the whole future of a scenario (factors of running operations upwards, factors of not yet started operations arbitrarily) and checks that the snapshot stays identical (mk01, 3 seeds, 4 time points).

Hand-computed example (toy plan of section 5, factor 2 on b1, $t = 5$): a1 finished M1 [0, 3); a2 running on M3 since 3, $\tilde C = 3 + 3 = 6$; b1 running on M1 since 3, planned end 5 has passed, so $\tilde C = \max(5, 6) = 6$ (realized end 7, invisible); b2 is due at 5 but waits for b1, so it is free. With factor 3 on b1 (realized end 9) the snapshot is identical.

Snapshots are Pydantic models (`Snapshot`, `FrozenOperation`) and can be stored as JSON.

## 7. Replanning and outlook

- **Breaks in a plan update (2026-11-09):** `update_plan(plan, breaks=None)` checks plan and breaks against the snapshot (C1–C7, C6$^b$, C7$^b$, C14$^f$); `None` keeps the current breaks (`current_breaks()`: taken ones with their realized start, pending ones with their planned start), otherwise the taken breaks stay and the pending ones are replaced (new wake-ups at their starts). `realized_breaks()` keeps working on the merged list.
- **Plan update (implemented):** the DES offers `snapshot()`, `current_plan()` and `update_plan(plan)` to the planning tool ([05](05_rescheduling-frozen-part.md)). An updated plan must satisfy C1–C7 against the snapshot; then machines and planned times of the operations not started are replaced, the realized durations of reassigned operations are recomputed from their factor and the new machine, the planned order per machine is rebuilt (finished operations first, then the running one, then the new plan), and the DUE events of operations not yet released are moved. Machine and order per machine are therefore part of `SimState`. The DES itself never calls a planner.
- **Further disturbances:** machine breakdowns, order arrivals (new event type RELEASE).
- Online dispatching (no plan, a rule decides at every event) is then "replan at every event with a rule planner" and needs no rule logic inside the DES.

## 8. Assumptions and open points

- Right-shift without overtaking: a machine may stay idle although a later planned operation could run; resolving this is the planner's job (replanning).
- A shorter operation does not pull successors forward (planned start is binding).
- Rounding of realized durations to integers ([22](22_scenarios.md)).

## 9. Sources

- Execution semantics, event types, state: own design following the architecture in `CLAUDE.md`.
- Right-shift as reaction to disturbances: **[source needed]**.

## 10. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-21 | `6300e52` | Version 1: event loop with replay of a plan, start check, event log; zero-disturbance tests. |
| 2026-10-21 | `bf25ab4` | Zero-disturbance makespan check extended to all instances (rule and CP-SAT plans); result table. |
| 2026-10-22 | uncommitted | Version 2: disturbance scenarios, right-shift execution keeping machine and planned order, DUE events and start step per time point, plan validated with the feasibility checker before the run. |
| 2026-10-23 | uncommitted | Pausable run (`until`), snapshot with frozen part (finished and running operations), expected completion of running operations, leakage test. |
| 2026-10-29 | uncommitted | Start offsets (early/late release, late offset fixed once), RELEASE events, repair step between event processing and start step, state with current plan; release time checked at start. |
| 2026-10-29 | uncommitted | Replanning: snapshot before the start step, plan swap (machines, order per machine, durations of reassigned operations, DUE events); machine and order moved into the state. |
| 2026-10-30 | uncommitted | DES as `Simulation` object (process_events, start_operations, snapshot, current_plan, update_plan); repair and rescheduling moved to the planning tool (math/05). |
| 2026-10-30 | uncommitted | Late start offset counted from actual readiness $R_o$ (released and ready), not from the planned start; RELEASE event replaced by LATE_START. Reason: with repair the old rule added the offset to predecessor delays (mk01: 65 vs 45). |
| 2026-10-30 | uncommitted | OVERDUE event at the expected end of a running operation (planned end, then every minute). |
| 2026-10-30 | uncommitted | Event DUE renamed to PLANNED_START (`due_at` to `planned_start_at`), no change in behavior. |
| 2026-10-30 | uncommitted | WAKE event for time points requested by the planning tool; `has_unstarted`. |
| 2026-11-02 | uncommitted | Carriers and runs run unchanged; blocking of a run through the planned order per machine. |
| 2026-11-03 | uncommitted | Batches: joint start, fixed duration. |
| 2026-11-06 | uncommitted | Snapshot with workers (phase 2, task 4): machine optional, workers of started shares, expected end of machine-less operations; `ExecutionResult.breaks`. |
| 2026-11-06 | uncommitted | Swap rule (phase 2, task 3): free qualified worker takes a due share of a busy one if it fits before its next planned share; SWAP log; tests `tests/test_des_swap.py`. |
| 2026-11-05 | uncommitted | Work calendar (phase 2, task 2): shift window with wake-ups, planned breaks taken or postponed, realized breaks and share lengths in the result; tests `tests/test_des_calendar.py`. |
| 2026-11-05 | uncommitted | Workers (phase 2, task 1): shares in planned order per worker, suffix with OVERSTAY, machine-less operations, SHARE_END and SUFFIX_DUE events; `Simulation(..., breaks)`, `replay(..., breaks)`, `SimResult.breaks`; tests `tests/test_des_workers.py`. |
| 2026-11-08 | uncommitted | `Snapshot.breaks`: breaks started by $t$ with their realized starts. |
| 2026-11-09 | uncommitted | Expected end $t + a^{\mathrm{suf}}_o$ for a pending suffix; `update_plan` takes the plan's worker for a share not started of a running operation. |
| 2026-11-09 | uncommitted | `update_plan(plan, breaks)`, `current_breaks()`: taken breaks kept, pending ones replaced. |
| 2026-11-09 | uncommitted | `FrozenOperation.share_lengths`; swap-rule worker written $z' \in W_o$; $\overline{\mathrm{ot}}$. |
