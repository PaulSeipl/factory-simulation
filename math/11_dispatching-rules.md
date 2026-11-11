# 11 Dispatching rules

Files `1x` describe solution methods; files `0x` describe model components.

## 1. Prose description

Dispatching rules build a schedule step by step without search. They serve as a baseline for the GA and CP-SAT and, later, as the decision logic inside the DES.

In the FJSP every operation needs two decisions: which machine (assignment) and when relative to the other operations on that machine (sequencing). Two ways of making them are implemented:

1. **Separate rules.** An *assignment rule* fixes the machine as soon as an operation becomes ready (least load or ECT); a *sequencing rule* then chooses among the operations that can start earliest on their assigned machine. Schedule generation is non-delay *with respect to the assignment*: a machine never stays idle while an operation assigned to it could start, but an operation may wait for its assigned machine although another eligible machine is idle. This matches a DES in which an operation is routed to a machine queue when it becomes ready.
2. **Joint (no assignment rule).** The earliest possible start is taken over all pairs (ready operation, eligible machine); the sequencing rule ranks the pairs that can start then, and so chooses operation and machine together. This is non-delay over all machines: no eligible machine stays idle while a ready operation could start on it.

Sequencing rules: SPT, FIFO, MWKR, LRP, EDD. Every sequencing rule can be combined with every assignment variant (least load, ECT, joint).

Limitation: for a regular criterion an optimal schedule is contained in the set of active schedules (Dauzère-Pérès et al., 2024, p. 414, citing French, 1982). Rule-based schedules of this kind need not contain an optimal schedule **[source needed]**. The toy example shows this (section 5).

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

- $\underline{p}_o = \min_{m \in M_o} p_{o,m}$: shortest processing time of $o$
- $\underline{S}_o$: ready time of $o$ (release and completion of all predecessors)
- $\phi_m$: time at which machine $m$ becomes free in the partial schedule
- $V_m$: load of machine $m$, the total processing time assigned to $m$ so far
- $V^{\mathrm{q}}_m$: backlog of machine $m$, processing time assigned to $m$ but not yet scheduled
- $\mathrm{wr}_k$: remaining work of order $k$, $\sum \underline{p}_o$ over its unscheduled operations
- $\ell_o$: longest remaining path from $o$ (inclusive) to the end of its order, measured with $\underline{p}$
- $m(o)$: machine assigned to $o$

## 3. Algorithm and rules

Schedule generation (`dispatch`):

1. $\underline{S}_o \leftarrow r_{k(o)}$, $\phi_m = V_m = V^{\mathrm{q}}_m \leftarrow 0$, $\mathrm{wr}_k \leftarrow \sum_{o \in O_k} \underline{p}_o$. Every operation without predecessor becomes ready (in index order). With an assignment rule it is assigned immediately: $m(o) \leftarrow$ rule, $W_{m(o)} \mathrel{+}= p_{o,m(o)}$, $B_{m(o)} \mathrel{+}= p_{o,m(o)}$.
2. While ready operations exist:
   - candidates: pairs $(o, m)$ with $o$ ready and $m = m(o)$ (separate rules) or $m \in M_o$ (joint)
   - $t \leftarrow \min$ over candidates of $\max(\underline{S}_o, \phi_m)$
   - among the candidates with $\max(\underline{S}_o, \phi_m) = t$, the sequencing rule chooses the one with the smallest key; ties are broken by the smaller operation index, then the smaller machine index
   - $S_o = t$, $C_o = t + p_{o,m}$, $\phi_m = C_o$, $\mathrm{wr}_{k(o)} \mathrel{-}= \underline{p}_o$; separate rules: $V^{\mathrm{q}}_m \mathrel{-}= p_{o,m}$; joint: $V_m \mathrel{+}= p_{o,m}$
   - for every successor $o'$: $\underline{S}_{o'} \leftarrow \max(\underline{S}_{o'}, C_o)$; once all its predecessors are scheduled, $o'$ becomes ready (and is assigned)

Every generated schedule satisfies C1–C5 by construction ($t \ge \underline{S}_o \ge r_{k(o)}$, $t \ge \phi_m$, $m \in M_o$, operations become ready only after their predecessors). The tests verify this with the feasibility checker for every combination on all instances.

An operation becomes ready, and is assigned, as soon as its last predecessor is *scheduled* (its completion time is then known), not when that predecessor finishes. Assignments therefore happen in scheduling order. In the DES, assignment will happen at the completion event; with disturbances the two orders can differ.

**Assignment rules** (ties: shorter $p_{o,m}$, then lower machine index):

| Rule | Choice |
|---|---|
| Least load | $\arg\min_{m \in M_o} V_m$ |
| ECT | $\arg\min_{m \in M_o} \max(\underline{S}_o,\ \phi_m + V^{\mathrm{q}}_m) + p_{o,m}$ |

ECT estimates the completion time of $o$ on $m$. The backlog $V^{\mathrm{q}}_m$ is **own**: without it, operations assigned at the same moment would all see the same idle machine, because work already queued there but not yet scheduled would be invisible. $\phi_m + V^{\mathrm{q}}_m$ is an estimate; the queue order on $m$ is decided later by the sequencing rule.

**Sequencing rules** (key, smallest first; ties: lower operation index, then lower machine index):

| Rule | Key | Meaning |
|---|---|---|
| SPT | $p_{o,m}$ | shortest processing time of the pair |
| FIFO | $(\underline{S}_o,\ p_{o,m})$ | ready longest; SPT as tie-breaker |
| MWKR | $(-\mathrm{wr}_{k(o)},\ p_{o,m})$ | most work remaining in the order; SPT as tie-breaker |
| LRP | $(-\ell_o,\ p_{o,m})$ | longest remaining path; SPT as tie-breaker |
| EDD | $(d_{k(o)},\ p_{o,m})$ | earliest due date of the order ([06](06_due-dates.md)); SPT as tie-breaker; orders without due date after all others (key $(1, 0, p)$ instead of $(0, d, p)$), so without any due date EDD equals SPT |

$$\ell_o = \underline{p}_o + \max_{(o,o') \in P} \ell_{o'} \qquad (\max \emptyset = 0)$$

computed once per instance in reverse topological order. For chains, $\ell_o = \mathrm{wr}_{k(o)}$ whenever $o$ is the next operation of its order, so MWKR and LRP coincide on all Brandimarte instances; they differ only for DAGs, where $\mathrm{wr}_k$ sums all remaining work and $\ell_o$ follows the longest path.

$V_m$ counts all processing time assigned to $m$, including finished operations: least load balances total workload, not the current queue. $\mathrm{wr}_k$ and $\ell_o$ use $\underline{p}_o$ because the machines of unscheduled operations are not yet known.

**[source needed]** SPT, FIFO, MWKR, workload- and completion-time-based machine assignment are classical rules; none of the papers read so far defines them. LRP is an own adaptation of MWKR to DAG precedence. A survey of priority rules and Birgin et al. (2015, list scheduling for the FJSP with DAG precedence, cited in Lunardi et al., 2020) should be read and cited.

**Runs** ([03](03_carriers.md)): a run (setup, main operation, removal) is dispatched as one unit. Its first operation stands for the whole run with the run's total duration per machine; when it is chosen, the three operations are placed back to back on one machine, so C8 and C9 hold by construction. Shortcut: assignment rules see only the first operation's duration. **Batches** ([03](03_carriers.md)): greedy batching: when an operation of a batch step is chosen at $t$ on $m$, the ready operations of a batch step that fit on $m$ with the same duration join in the order of the sequencing rule, up to the capacity; no waiting to fill. From a snapshot, a partly started run (e.g. setup done, print running) is placed first: its remaining operations follow back to back on its machine.

**Workers** ([04](04_workers.md)). Every share $\eta$ of an operation (whole, prefix, suffix) gets one worker from $W_o$; the worker time of a share is `share_interval` (whole $[S_o, C_o)$, prefix $[S_o, S_o + a^{\mathrm{pre}}_o)$, suffix $[C_o - a^{\mathrm{suf}}_o, C_o)$). Per worker the dispatcher keeps its booked share intervals and its worker load $V_z$ (sum of booked share lengths).
- **Earliest start of a candidate** $(o, m)$: the smallest $t \ge \max(\underline{S}_o, \phi_m)$ (machine-less: $t \ge \underline{S}_o$) such that every share of $o$ started at $t$ finds a worker in $W_o$ who is free for the whole share interval. Found by a fixpoint: per share the earliest gap of a qualified worker, shifted back by the share's offset; $t$ moves to the latest of these until it no longer changes. Non-delay ranks the candidates by this $t$, so a candidate never claims a start its workers cannot keep.
- **Gaps, not append-only** (deviation from plan item 3, own, 2026-11-06): workers are booked into gaps of their busy intervals, machines stay append-only. Reason: a suffix share (oven removal) is booked when the oven run is planned, hours before it happens; append-only would block its worker for the whole oven program.
- **Worker choice** per share at the chosen $t$: among the free qualified workers the one with the least $V_z$, then the lowest index. Prefix and suffix may get different workers.
- **Batches:** the shares of a batch are booked once (one loading, one removal); every member carries the same workers.
- **Runs:** the head (setup) waits for its own workers; the following parts are placed one after the other on the run's machine, each at the earliest $t \ge$ end of the previous part at which its workers are free. A waiting removal keeps the machine blocked ($\phi_m$ = end of the last part), which C9 allows. Setup and removal choose their workers independently.
- **Operations without machine** ($O^{\emptyset}$, duration $p_o$) wait only for $\underline{S}_o$ and their workers; assignment rules skip them.
- The assignment rules (least load, ECT) stay machine-based: they do not see worker delays (limitation of the baseline).
- **From a snapshot** (phase 3 task 4, without calendar): the started shares of frozen operations keep their workers (C7) and are booked first (a batch once); then every pending share of a frozen operation (worker `None` in the snapshot: the removal of a running oven) gets the free qualified worker with the least $V_z$ at its expected interval $[\tilde C_o - a^{\mathrm{suf}}_o, \tilde C_o)$, the same for all members of the batch. If no qualified worker is free then (a disturbance: the only qualified worker is on an overrunning share), the suffix is booked at the earliest time a qualified worker is free and the operation, its batch, its machine and its successors end later: a forced overstay (C7$^o$, [04](04_workers.md) §3). Before 2026-11-09 `dispatch` raised `ValueError` here. The parts of a partly started run wait for their workers as above. With a calendar (2026-11-09, breaks Task 4) the pending removal is booked exactly as the checker computes $C_o$ in C7$^o$: in the shift window **with** overtime, blocked only by the frozen part (started shares with their snapshot lengths, started breaks), before any break and any new share; e.g. a removal expected at 17:36 keeps its end, a removal expected at 12:00 tomorrow keeps it and that day's break of its worker moves to 12:01. Since 2026-11-11 the pending removals come from `planners.repair.forced_removals` (C7$^o$ in a fixed order: earliest possible start, then earliest due date, then index, each clear of the removals booked before it) with the rule's worker choice kept: among the qualified workers free at the forced start the one with the least $V_z$ (callback `choose`). Only the order changed: before, the removals were booked in snapshot order, which could give the only free worker to two overlapping removals (`tests/test_competing_removals.py`); a single pending removal is booked as before.
- **Calendar** (phase 3 task 3, revised 2026-11-09): a worker is free for a share interval only if it lies within one working day's shift **without overtime**, $[h^{\mathrm{S}}, h^{\mathrm{E}}]$, and outside that worker's break of that day $[\mathrm{br}_{z,\nu}, \mathrm{br}_{z,\nu} + p^{\mathrm{br}})$ (gap search over the bookings plus the break). The break $\mathrm{br}_{z,\nu}$ is a pure function of $(z, \nu)$ and the frozen part (`break_at`, memoized): the break started by $t$ if there is one; otherwise the earliest start $\ge h^{\mathrm{B}-}$ (on the snapshot's day also $\ge t$) clear of the frozen part and the pending removals. Without a snapshot it is always 12:00, so the plans equal the earlier fixed-12:00 version (30 start plans with breaks on the two calendar instances and 195 worker-free plans compared, identical). After the window (since 2026-11-09, C14$^f$ extended by the user): the earliest clear start is itself the forced postponement (nothing fits in the window next to the frozen part and the pending removals); no break is booked only on the snapshot's day with $t$ after the window and no frozen share of the worker before it (no break can be owed, as new shares all start after the window; a worker idle until 16:00 takes a share then). The earlier `ValueError` (a break owed but none possible) is gone. The rule plans no overtime and no postponed breaks of its own; both stay for the DES and CP-SAT. Machines run at any time: a mill or print run may continue overnight, and its attended removal waits until 08:00 with the machine blocked (C9). `dispatch_plan(...)` returns `Plan(assignments, breaks)`: one break per worker and day with one of its shares from the snapshot's day on, plus the snapshot's breaks; `dispatch` returns the assignments only. (`default_breaks` was removed: one source for the breaks.) A share longer than both shift parts raises `ValueError`; so does an operation whose shares can never lie in the shifts together (e.g. loading and removal of a 14-hour oven program), detected when no fit exists within two weeks after the last booking (the calendar repeats weekly).

## 4. Objective function

Rules do not optimize an objective directly; the schedule is evaluated afterwards with the objective of choice (see [01](01_basic-fjsp.md), §4).

## 5. Implementation in code

Module `simulation.planners.dispatching`: `dispatch(ci, sequencing, assignment=None) -> list[Assignment]`; sequencing rules `spt`, `fifo`, `mwkr`, `lrp`, `edd` (registry `SEQUENCING_RULES`); assignment rules `least_load`, `ect` (registry `ASSIGNMENT_RULES`); `assignment=None` is the joint mode. Rules read the dispatcher state `DispatchState` ($\underline{S}$ `ready_at`, $\phi$ `machine_free`, $V$ `load`, $V^{\mathrm{q}}$ `backlog`, $\mathrm{wr}$ `work_left`, $\ell$ `remaining_path`).

Hand-computed examples (test `test_spt_on_toy_dag_matches_hand_computation`), SPT on `toy-dag-3x4`, one per assignment variant.

**SPT + least load** (makespan 15). Assignments ($W_{M1..M4}$ after each):

| After | Assignment |
|---|---|
| start | a1 → M1 (tie on load 0, $p$ 3 < 5): 3,0,0,0 · b1 → M3 (0 < 3): 3,0,4,0 · c1 → M1 (3 < 4): 6,0,4,0 |
| a1 scheduled | a2 → M2 (0 < 4): 6,4,4,0 |
| b1 scheduled | b2 → M2 (tie on load 4 and $p$ 3, lower index): 6,7,4,0 · b3 → M4 (0 < 6): 6,7,4,3 |
| a2 scheduled | a3 → M4 (only option): 6,7,4,5 |
| c1 scheduled | c2 → M4 (5 < 7): 6,7,4,9 |
| b2 scheduled | b4 → M2 (7 < 9): 6,10,4,9 |

Sequence: a1 M1 [0,3) · b1 M3 [2,6) · a2 M2 [3,7) · c1 M1 [4,7) · b3 M4 [6,9) · b2 M2 [7,10) · a3 M4 [9,11) (SPT over c2) · b4 M2 [10,13) · c2 M4 [11,15).

**SPT + ECT** (makespan 13). Assignments with estimated completion $\max(\underline{S}_o, \phi_m + V^{\mathrm{q}}_m) + p_{o,m}$:

| After | Assignment |
|---|---|
| start | a1: M1 3, M2 5 → M1 · b1: M1 max(2, 0+3)+2 = 5, M3 2+4 = 6 → M1 · c1: M1 max(4, 0+5)+3 = 8, M3 4+2 = 6 → M3 |
| a1 [0,3) | a2: M2 3+4 = 7, M3 max(3, 0+2)+3 = 6 → M3 |
| b1 [3,5) | b2: M2 5+3 = 8, M3 max(5, 0+4)+3 = 8 → M2 (tie on value and $p$, lower index) · b3: M1 5+4 = 9, M4 5+3 = 8 → M4 |
| a2 [3,6) | a3 → M4 (only option) |
| b3 [5,8) | b4: M4 max(8, 8+2)+2 = 12, M2 max(8, 8+0)+3 = 11 → M2 |
| c1 [6,8) | c2: M2 max(8, 8+3)+2 = 13, M4 max(8, 8+2)+4 = 14 → M2 |

Sequence: a1 M1 [0,3) · b1 M1 [3,5) (SPT over a2 at $t = 3$) · a2 M3 [3,6) · b2 M2 [5,8) · b3 M4 [5,8) · c1 M3 [6,8) · a3 M4 [8,10) · c2 M2 [8,10) · b4 M2 [10,13).

**SPT, joint** (makespan 12): the sequencing rule ranks (operation, machine) pairs that can start at $t$.

| Step | $t$ | Pairs with start $t$ | Chosen | Scheduled |
|---|---|---|---|---|
| 1 | 0 | a1/M1 (3), a1/M2 (5) | a1/M1 | [0, 3) |
| 2 | 2 | b1/M3 (4) | b1/M3 | [2, 6) |
| 3 | 3 | a2/M2 (4) | a2/M2 | [3, 7) |
| 4 | 4 | c1/M1 (3) | c1/M1 | [4, 7) |
| 5 | 6 | b2/M3 (3), b3/M4 (3) | b2/M3 (tie, lower index) | [6, 9) |
| 6 | 6 | b3/M4 (3) | b3/M4 | [6, 9) |
| 7 | 7 | c2/M2 (2) | c2/M2 | [7, 9) |
| 8 | 9 | a3/M4 (2), b4/M4 (2), b4/M2 (3) | a3/M4 (tie, lower index) | [9, 11) |
| 9 | 9 | b4/M2 (3) | b4/M2 | [9, 12) |

A feasible schedule with makespan 11 exists (`tests/test_feasibility.py`). Least load loses most: b2 goes to M2 (busy until 7) instead of M3, and M4 ends up with three operations. ECT sees the queued work but still lets b1 take M1 at $t = 3$ ahead of a2, which then runs on M3 and delays c1. Joint loses one unit in step 2: non-delay forces b1 onto M3 at $t = 2$ (4 units) instead of waiting for M1 (free at 3, 2 units).

On the toy instance all four sequencing rules give the same makespan per assignment variant (15 / 13 / 12): the instance is too small for the rules to diverge. The tests use dedicated conflict instances for that.

**From a snapshot** (complete rescheduling, [05](05_rescheduling-frozen-part.md)): `dispatch(ci, sequencing, assignment, snapshot)` keeps the frozen operations unchanged, initializes $\phi_m$ with $\max(t, \text{(expected) end of frozen operations on } m)$, $\underline{S}_o$ with $\max(r_{k(o)}, t, \text{(expected) end of frozen predecessors})$, counts frozen operations in $V_m$ and removes them from $\mathrm{wr}_k$. All other rules work unchanged. Hand-computed example (test `test_joint_spt_from_snapshot_matches_hand_computation`), joint SPT on `toy-dag-3x4` at $t = 5$ with a1 finished [0,3), a2 running on M3 (expected end 6), b1 running on M1 (overrun, expected end 6):

| Step | $t$ | Pairs with start $t$ | Chosen | Scheduled |
|---|---|---|---|---|
| 1 | 6 | c1/M1 (3), c1/M3 (2), a3/M4 (2), b2/M2 (3), b2/M3 (3), b3/M1 (4) | a3/M4 (tie on 2 with c1/M3, lower index) | [6, 8) |
| 2 | 6 | c1/M1, c1/M3 (2), b2/M2, b2/M3, b3/M1 | c1/M3 | [6, 8) |
| 3 | 6 | b2/M2 (3), b3/M1 (4) | b2/M2 | [6, 9) |
| 4 | 6 | b3/M1 (4) | b3/M1 | [6, 10) |
| 5 | 8 | c2/M4 (4) (c2/M2 only from 9) | c2/M4 | [8, 12) |
| 6 | 10 | b4/M2 (3) (b4/M4 only from 12) | b4/M2 | [10, 13) |

Makespan 13. The checker with snapshot confirms C1–C7; every rule combination from a mid-run snapshot of mk01 is feasible as well (tests).

**With workers** (tests `tests/test_dispatching_workers.py`, SPT joint; first three without calendar):
- `toy-workers` (calendar removed): k2 packaging [0, 20) by A (tie in load, lower index; SPT 20 < 60); print P [0, 60) by B (A busy for the prefix [0, 15)); Gegenbetten [60, 150) by A (only A qualified); k1 packaging [150, 170) by B ($V_A = 50 > V_B = 15$). Makespan 170.
- Carrier instance (two plates, oven batch with prefix 1 and suffix 1, attended mill runs): prints [0, 2), [2, 4); L1 oven alone [2, 7) (L2 not yet ready), loading W1, removal W2 ($V$ 0 < 1); at 7 L2 oven (SPT 5 < run 6) [7, 12), W1 (tie, index) and W2 (1 < 2); L1 mill setup [7, 8) by W2 in the gap before its removal at 11; L1 removal [12, 13) W1; L2 run from 13, setup W1 (tie), removal [18, 19) W2. Makespan 19.
- With a second printer both plates share one oven run [2, 7), one set of workers (W1, W2) for both members.
- With the calendar ($t = 0$ Monday 08:00): one packaging of 60 minutes released Friday 11:30 runs 13:00–14:00 (would cross 12:00), break of A Friday 12:00, due Friday 12:00 → 1 missed cutoff; released Friday 17:00 it runs Monday 08:00–09:00 (no overtime), on time for Monday 12:00. Carrier instance with a 600-minute mill program: L1 mill [8, 608) ends 18:08, removal Tuesday 08:00 by W1, M blocked until 1441; L2 run from 1441, its program ends Tuesday 18:02, removal Wednesday 08:00 by W2; breaks W1 Monday and Tuesday, W2 Monday and Wednesday.
- From a snapshot with the calendar (breaks Task 4, `tests/test_rule_snapshot_calendar.py`, by hand): one worker, A's break taken at 12:20 after a slow prefix, snapshot 12:30 → k1 packaging 13:20 (not 13:00); A on a frozen share until 12:40, snapshot 11:10 → break 12:40, next share 13:40; the share runs until 13:45, snapshot 13:10 (expected end 311) → forced break at 311, next share 371; a prefix overrunning past 13:00 (snapshot share length 231) → forced break at 311; removals expected at 17:36 and at 12:00 tomorrow keep their ends. Sweep: 5 instances working around 12:00, the shift end and overnight × 6 disturbed seeds ($\sigma = 0.6$, late offsets up to 30) × 12 snapshot times over the realized run × 15 rules pass the checker against the snapshot with the returned breaks, and the DES accepts the SPT plan (coverage measured: taken and moved breaks, pending removals, 7 forced overstays).
- All 15 rule combinations on `toy-workers` (with its calendar) and on the night carrier instance pass the checker with the plan's breaks (`dispatch_plan`, C1–C14) and replay unchanged, breaks included.
- From a snapshot of the carrier rule plan at $t = 9$ (L1 mill running, L2 oven running with its removal pending): booked loads W1 2, W2 2 → L2 removal [11, 12) W1 (tie, index); L1 removal [12, 13) W2; L2 run setup [13, 14) W1, removal [18, 19) W2. On `toy-workers` with Gegenbetten at factor 2, snapshot at 70: Gegenbetten [60, 150) stays with A, k1 packaging [150, 170) B. Every rule combination from 10 snapshots × 5 disturbed seeds ($\sigma = 0.5$) on both instances passes the checker against the snapshot (C6, C7).
- All 15 rule combinations on both instances pass the checker (C1–C12) and replay unchanged in the DES without disturbance. Without workers all 195 plans (Mk01–Mk10 and three toys × 15 combinations) are identical to the version before (checked once, scratch comparison).

Results on the Brandimarte instances (makespan, own computation; LL = least load, J = joint):

| | mk01 | mk02 | mk03 | mk04 | mk05 | mk06 | mk07 | mk08 | mk09 | mk10 |
|---|---|---|---|---|---|---|---|---|---|---|
| SPT / LL | 52 | 46 | 230 | 90 | 201 | 103 | 229 | 568 | 397 | 290 |
| SPT / ECT | 42 | 32 | 221 | 73 | 197 | 79 | 176 | 563 | 379 | 247 |
| SPT / J | 55 | 55 | 268 | 78 | 224 | 82 | 227 | 601 | 431 | 375 |
| FIFO / LL | 47 | 39 | 209 | 82 | 188 | 95 | 204 | 532 | 354 | 293 |
| FIFO / ECT | 42 | 31 | 204 | 75 | 188 | 74 | 158 | 532 | 345 | 237 |
| FIFO / J | 47 | 31 | 217 | 76 | 189 | 79 | 176 | 531 | 369 | 279 |
| MWKR / LL | 49 | 38 | 217 | 80 | 183 | 97 | 207 | 523 | 328 | 276 |
| MWKR / ECT | 42 | 30 | 204 | 70 | 184 | 73 | 150 | 523 | 311 | 227 |
| MWKR / J | 48 | 33 | 204 | 75 | 186 | 88 | 190 | 523 | 327 | 266 |
| LRP / * | = MWKR (chains) | | | | | | | | | |

ECT gives the best or a tied makespan of the three assignment variants in 28 of 30 (sequencing rule, instance) cases; the exceptions are FIFO on mk08 (joint 1 unit better) and MWKR on mk05 (least load 1 unit better). No comparison with best-known values from the literature yet; these must be taken from a cited source, not from memory.

## 6. Assumptions and open points

- ECT with backlog $\phi_m + V^{\mathrm{q}}_m$ is an estimate and an own choice; alternatives (only $\phi_m$, or the queue simulated in sequencing order) are not compared.
- Due-date rules (EDD, slack) need due dates, which are not yet in the instance format.
- The rule set is a first baseline, not a claim about which rules are best.
- Workers: assignment rules ignore workers; ECT's estimate inside `make_ready` sees $\phi_m = t + p$ of a run even when its removal later waits for a worker (slight underestimate). From a snapshot with workers, `dispatch` raises `NotImplementedError` until phase 3 task 4 (frozen shares do not occupy workers yet).

## 7. Sources

- Active and semi-active schedules: Dauzère-Pérès et al. (2024), p. 414.
- Rule definitions and schedule generation: own formulation; literature still to be added (see section 3).
- Birgin et al. (2015) Check

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-19 | e8617db | Non-delay dispatching with SPT, FIFO, LRP (pair ranking). |
| 2026-10-19 | e8617db | Replaced by separate assignment rule (least load) and sequencing rules (SPT, MWKR); FIFO and LRP removed; new hand-computed example and results. |
| 2026-10-19 | e8617db | FIFO and LRP restored; assignment rule ECT (with backlog) added; joint mode (no assignment rule) restored as `assignment=None`; three hand-computed examples; full result table. |
| 2026-10-29 | 17d05a8–28ac70f | Dispatching from a snapshot (frozen part, machine availability, start not before t); hand-computed example. |
| 2026-10-30 | 17d05a8–28ac70f | EDD sequencing rule; hand examples in `tests/test_objectives.py`: one machine, X (p 3, d 3) and Y (p 1, d 10): SPT makes X 1 late, EDD none; EDD + ECT on the toy with due dates 10/11/10: c2 before b4 on M2 at t = 8, b4 [10, 13), $\sum T = 2$. |
| 2026-11-02 | ee3b2b1–cd7ca2b | Runs dispatched as one unit (C8, C9). |
| 2026-11-02 | ee3b2b1–cd7ca2b | Dispatching continues partly started runs from a snapshot. |
| 2026-11-03 | 31b7574–91ebc7c | Greedy batching for batch steps. |
| 2026-11-06 | 78e228d | Workers without calendar: shares booked into worker gaps, worker choice by least worker load, batch shares once, runs part by part, machine-less operations; hand examples. |
| 2026-11-07 | 78e228d | Calendar in the rule: shares within the shift without overtime, fixed 12:00 break, `default_breaks`, night runs with morning removal; hand examples. |
| 2026-11-08 | 78e228d | From a snapshot with workers (no calendar): frozen shares occupy their workers, pending removals get a worker; hand examples. |
| 2026-11-09 | ef6f798 | Forced overstay for a pending removal without a free worker instead of `ValueError`. |
| 2026-11-09 | ef6f798 | Symbols renamed (protocol 2026-11-09 (24)): ready time $\rho_o$ → $\underline{S}_o$, machine free time $f_m$ → $\phi_m$, load $W_m$ → $V_m$, backlog $B_m$ → $V^{\mathrm{q}}_m$, remaining work $w_k$ → $\mathrm{wr}_k$, successor $s$ → $o'$, worker load $V_w$ → $V_z$, $W_\eta$ → $W_o$. |
| 2026-11-09 | 7274636 | From a snapshot with the calendar: breaks as bookings per worker and day (`break_at`), pending removals as in C7$^o$, `dispatch_plan` returns the breaks, `default_breaks` removed; hand examples and sweep. |
| 2026-11-09 | 7274636 | No break owed for a worker whose first share of the day starts after the window (C14 revised in [04](04_workers.md)): no more "no new share that day". |
| 2026-11-09 | uncommitted | C14$^f$ extended (user): a break after the window at the earliest clear start, also when a pending removal is the cause; no `ValueError` any more. |
| 2026-11-11 | uncommitted | Pending removals in the order of `forced_removals` (C7$^o$, user), worker still by least load. |
| 2026-11-09 | uncommitted | Shift-window search moved to `calendar.shift_window` (shared with the repair, [05](05_rescheduling-frozen-part.md)); behaviour unchanged. |
