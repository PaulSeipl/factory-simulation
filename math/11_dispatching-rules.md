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
- $\rho_o$: ready time of $o$ (release and completion of all predecessors)
- $f_m$: time at which machine $m$ becomes free in the partial schedule
- $W_m$: load of machine $m$, the total processing time assigned to $m$ so far
- $B_m$: backlog of machine $m$, processing time assigned to $m$ but not yet scheduled
- $w_k$: remaining work of order $k$, $\sum \underline{p}_o$ over its unscheduled operations
- $\ell_o$: longest remaining path from $o$ (inclusive) to the end of its order, measured with $\underline{p}$
- $m(o)$: machine assigned to $o$

## 3. Algorithm and rules

Schedule generation (`dispatch`):

1. $\rho_o \leftarrow r_{k(o)}$, $f_m = W_m = B_m \leftarrow 0$, $w_k \leftarrow \sum_{o \in O_k} \underline{p}_o$. Every operation without predecessor becomes ready (in index order). With an assignment rule it is assigned immediately: $m(o) \leftarrow$ rule, $W_{m(o)} \mathrel{+}= p_{o,m(o)}$, $B_{m(o)} \mathrel{+}= p_{o,m(o)}$.
2. While ready operations exist:
   - candidates: pairs $(o, m)$ with $o$ ready and $m = m(o)$ (separate rules) or $m \in M_o$ (joint)
   - $t \leftarrow \min$ over candidates of $\max(\rho_o, f_m)$
   - among the candidates with $\max(\rho_o, f_m) = t$, the sequencing rule chooses the one with the smallest key; ties are broken by the smaller operation index, then the smaller machine index
   - $S_o = t$, $C_o = t + p_{o,m}$, $f_m = C_o$, $w_{k(o)} \mathrel{-}= \underline{p}_o$; separate rules: $B_m \mathrel{-}= p_{o,m}$; joint: $W_m \mathrel{+}= p_{o,m}$
   - for every successor $s$: $\rho_s \leftarrow \max(\rho_s, C_o)$; once all its predecessors are scheduled, $s$ becomes ready (and is assigned)

Every generated schedule satisfies C1–C5 by construction ($t \ge \rho_o \ge r_{k(o)}$, $t \ge f_m$, $m \in M_o$, operations become ready only after their predecessors). The tests verify this with the feasibility checker for every combination on all instances.

An operation becomes ready, and is assigned, as soon as its last predecessor is *scheduled* (its completion time is then known), not when that predecessor finishes. Assignments therefore happen in scheduling order. In the DES, assignment will happen at the completion event; with disturbances the two orders can differ.

**Assignment rules** (ties: shorter $p_{o,m}$, then lower machine index):

| Rule | Choice |
|---|---|
| Least load | $\arg\min_{m \in M_o} W_m$ |
| ECT | $\arg\min_{m \in M_o} \max(\rho_o,\ f_m + B_m) + p_{o,m}$ |

ECT estimates the completion time of $o$ on $m$. The backlog $B_m$ is **own**: without it, operations assigned at the same moment would all see the same idle machine, because work already queued there but not yet scheduled would be invisible. $f_m + B_m$ is an estimate; the queue order on $m$ is decided later by the sequencing rule.

**Sequencing rules** (key, smallest first; ties: lower operation index, then lower machine index):

| Rule | Key | Meaning |
|---|---|---|
| SPT | $p_{o,m}$ | shortest processing time of the pair |
| FIFO | $(\rho_o,\ p_{o,m})$ | ready longest; SPT as tie-breaker |
| MWKR | $(-w_{k(o)},\ p_{o,m})$ | most work remaining in the order; SPT as tie-breaker |
| LRP | $(-\ell_o,\ p_{o,m})$ | longest remaining path; SPT as tie-breaker |
| EDD | $(d_{k(o)},\ p_{o,m})$ | earliest due date of the order ([06](06_due-dates.md)); SPT as tie-breaker; orders without due date after all others (key $(1, 0, p)$ instead of $(0, d, p)$), so without any due date EDD equals SPT |

$$\ell_o = \underline{p}_o + \max_{(o,s) \in P} \ell_s \qquad (\max \emptyset = 0)$$

computed once per instance in reverse topological order. For chains, $\ell_o = w_{k(o)}$ whenever $o$ is the next operation of its order, so MWKR and LRP coincide on all Brandimarte instances; they differ only for DAGs, where $w_k$ sums all remaining work and $\ell_o$ follows the longest path.

$W_m$ counts all processing time assigned to $m$, including finished operations: least load balances total workload, not the current queue. $w_k$ and $\ell_o$ use $\underline{p}_o$ because the machines of unscheduled operations are not yet known.

**[source needed]** SPT, FIFO, MWKR, workload- and completion-time-based machine assignment are classical rules; none of the papers read so far defines them. LRP is an own adaptation of MWKR to DAG precedence. A survey of priority rules and Birgin et al. (2015, list scheduling for the FJSP with DAG precedence, cited in Lunardi et al., 2020) should be read and cited.

**Runs** ([03](03_loads.md)): a run (setup, main operation, removal) is dispatched as one unit. Its first operation stands for the whole run with the run's total duration per machine; when it is chosen, the three operations are placed back to back on one machine, so C8 and C9 hold by construction. Shortcut: assignment rules see only the first operation's duration. **Batches** ([03](03_loads.md)): greedy batching: when an operation of a batch step is chosen at $t$ on $m$, the ready operations of a batch step that fit on $m$ with the same duration join in the order of the sequencing rule, up to the capacity; no waiting to fill. From a snapshot, a partly started run (e.g. setup done, print running) is placed first: its remaining operations follow back to back on its machine.

## 4. Objective function

Rules do not optimize an objective directly; the schedule is evaluated afterwards with the objective of choice (see [01](01_basic-fjsp.md), §4).

## 5. Implementation in code

Module `simulation.planners.dispatching`: `dispatch(ci, sequencing, assignment=None) -> list[Assignment]`; sequencing rules `spt`, `fifo`, `mwkr`, `lrp`, `edd` (registry `SEQUENCING_RULES`); assignment rules `least_load`, `ect` (registry `ASSIGNMENT_RULES`); `assignment=None` is the joint mode. Rules read the dispatcher state `DispatchState` ($\rho$, $f$, $W$, $B$, $w$, $\ell$).

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

**SPT + ECT** (makespan 13). Assignments with estimated completion $\max(\rho_o, f_m + B_m) + p_{o,m}$:

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

**From a snapshot** (complete rescheduling, [05](05_rescheduling-frozen-part.md)): `dispatch(ci, sequencing, assignment, snapshot)` keeps the frozen operations unchanged, initializes $f_m$ with $\max(t, \text{(expected) end of frozen operations on } m)$, $\rho_o$ with $\max(r_{k(o)}, t, \text{(expected) end of frozen predecessors})$, counts frozen operations in $W_m$ and removes them from $w_k$. All other rules work unchanged. Hand-computed example (test `test_joint_spt_from_snapshot_matches_hand_computation`), joint SPT on `toy-dag-3x4` at $t = 5$ with a1 finished [0,3), a2 running on M3 (expected end 6), b1 running on M1 (overrun, expected end 6):

| Step | $t$ | Pairs with start $t$ | Chosen | Scheduled |
|---|---|---|---|---|
| 1 | 6 | c1/M1 (3), c1/M3 (2), a3/M4 (2), b2/M2 (3), b2/M3 (3), b3/M1 (4) | a3/M4 (tie on 2 with c1/M3, lower index) | [6, 8) |
| 2 | 6 | c1/M1, c1/M3 (2), b2/M2, b2/M3, b3/M1 | c1/M3 | [6, 8) |
| 3 | 6 | b2/M2 (3), b3/M1 (4) | b2/M2 | [6, 9) |
| 4 | 6 | b3/M1 (4) | b3/M1 | [6, 10) |
| 5 | 8 | c2/M4 (4) (c2/M2 only from 9) | c2/M4 | [8, 12) |
| 6 | 10 | b4/M2 (3) (b4/M4 only from 12) | b4/M2 | [10, 13) |

Makespan 13. The checker with snapshot confirms C1–C7; every rule combination from a mid-run snapshot of mk01 is feasible as well (tests).

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

- ECT with backlog $f_m + B_m$ is an estimate and an own choice; alternatives (only $f_m$, or the queue simulated in sequencing order) are not compared.
- Due-date rules (EDD, slack) need due dates, which are not yet in the instance format.
- The rule set is a first baseline, not a claim about which rules are best.

## 7. Sources

- Active and semi-active schedules: Dauzère-Pérès et al. (2024), p. 414.
- Rule definitions and schedule generation: own formulation; literature still to be added (see section 3).
- Birgin et al. (2015) Check

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-19 | uncommitted | Non-delay dispatching with SPT, FIFO, LRP (pair ranking). |
| 2026-10-19 | uncommitted | Replaced by separate assignment rule (least load) and sequencing rules (SPT, MWKR); FIFO and LRP removed; new hand-computed example and results. |
| 2026-10-19 | uncommitted | FIFO and LRP restored; assignment rule ECT (with backlog) added; joint mode (no assignment rule) restored as `assignment=None`; three hand-computed examples; full result table. |
| 2026-10-29 | uncommitted | Dispatching from a snapshot (frozen part, machine availability, start not before t); hand-computed example. |
| 2026-10-30 | uncommitted | EDD sequencing rule; hand examples in `tests/test_objectives.py`: one machine, X (p 3, d 3) and Y (p 1, d 10): SPT makes X 1 late, EDD none; EDD + ECT on the toy with due dates 10/11/10: c2 before b4 on M2 at t = 8, b4 [10, 13), $\sum T = 2$. |
| 2026-11-02 | uncommitted | Runs dispatched as one unit (C8, C9). |
| 2026-11-02 | uncommitted | Dispatching continues partly started runs from a snapshot. |
| 2026-11-03 | uncommitted | Greedy batching for batch steps. |
