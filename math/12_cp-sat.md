# 12 CP-SAT model (static)

Files `1x` describe solution methods; files `0x` describe model components.

## 1. Prose description

A constraint programming model of the base model ([01](01_basic-fjsp.md), C1–C5), solved with OR-Tools CP-SAT. It is static: the whole instance is known at time 0, there are no disturbances. Purpose: exact solutions and lower bounds for small instances, and the reference ("oracle") against which dispatching rules and the GA are compared. Because the problem is NP-hard in the strong sense ([01](01_basic-fjsp.md), §1), optimality can only be expected up to a size that has to be determined experimentally.

The model follows the interval-based CP models of the sources (Kasapidis et al., 2021, (18)–(22); Lunardi et al., 2020, (33)–(40); Naderi & Roshanaei, 2022, (8)–(12)), which are written for IBM CP Optimizer; the transfer to CP-SAT is own.

## 2. Sets, parameters, variables

No new symbols in [notation.md](notation.md). Solver-internal objects:

- $S_o, C_o \in \{0, \dots, H\}$: start and completion of $o$ (integer variables)
- $x_{o,m} \in \{0, 1\}$: presence literal, $o$ runs on $m$
- $a_{o,m}$: optional interval of fixed size $p_{o,m}$ starting at $S_o$, present iff $x_{o,m} = 1$
- $H = \max_k r_k + \sum_{o} \max_{m \in M_o} p_{o,m}$: horizon (every operation in sequence on its slowest machine after the last release; always feasible)

## 3. Constraints

| Constraint ([01](01_basic-fjsp.md)) | CP-SAT |
|---|---|
| C1 assignment | `add_exactly_one`$(x_{o,m} : m \in M_o)$ |
| C2 non-preemption | `add`$(C_o = S_o + \sum_{m} p_{o,m} x_{o,m})$; each $a_{o,m}$ has fixed size $p_{o,m}$ |
| C3 precedence | `add`$(S_{o'} \ge C_o)$ for every $(o, o') \in P$ |
| C4 release | lower bound of the domain of $S_o$: $S_o \ge r_{k(o)}$ |
| C5 machine capacity | `add_no_overlap`$(\{a_{o,m} : m \in M_o\})$ per machine $m$ |

All optional intervals of an operation share its start variable $S_o$. The official OR-Tools FJSP example instead creates separate start/end variables per alternative and links them with `only_enforce_if` (Google OR-Tools, `flexible_job_shop_sat` example). Both are equivalent here because the processing time is fixed per machine; the shared start needs fewer variables and no reified constraints. Absent intervals are ignored by `add_no_overlap`, so only the chosen machine is occupied.

**Runs** ([03](03_carriers.md)): C8 as $x_{o,m} = x_{\operatorname{first}(G_R),m}$ for all operations of a run; C9 as one optional interval per run and machine, $[S_{\operatorname{first}(G_R)}, C_{\operatorname{last}(G_R)})$ with variable size and presence $x_{\operatorname{first}(G_R),m}$ (`new_optional_interval_var`), which replaces the intervals of the run's operations in `add_no_overlap`. Frozen operations of a run enter only through this span.

**Batches** ([03](03_carriers.md)): batch slots per family of operations (same machines, durations and capacity): slot presence $u_j$, start $S^B_j$, machine $z_{j,m}$, assignment $y_{o,j}$ (`only_enforce_if` for equal start and machine), capacity $\sum_o y_{o,j} \le c\,u_j$, one optional interval per slot and machine in `add_no_overlap` instead of the operations' intervals; symmetry breaking by slot order.

## 4. Objective function

The objective is a parameter (`simulation.objectives.Objective`): a pair of an evaluator on a finished schedule and a builder of the CP-SAT expression. A test checks that both agree on the CP-SAT solution. Implemented: the makespan $C_{\max}$ = `add_max_equality`$(C_{\max}, \{C_o\})$, `minimize`$(C_{\max})$ (default; validation on the Brandimarte instances), and with due dates total tardiness and the number of tardy orders, also combined lexicographically as one weighted sum ([06](06_due-dates.md) §4, mapping and weights there). The choice of the thesis objective is still open ([01](01_basic-fjsp.md), §4).

## 5. Implementation in code

`simulation.planners.cpsat.solve(ci, objective=MAKESPAN, time_limit=10.0, workers=8, seed=0) -> CpSatResult` with `status` (CP-SAT status name), `schedule` (list of `Assignment`, empty without solution), `objective`, `bound` (best proven lower bound) and `wall_time`.

Verification (`tests/test_cpsat.py`):

- **Independent optimality check** on the toy instances: a brute force enumerates every machine assignment and every precedence-respecting order and starts each operation as early as possible. Every semi-active schedule arises this way, and for a regular criterion such as the makespan an optimal schedule is semi-active (Dauzère-Pérès et al., 2024, p. 414). Results: toy-3x3 optimum 10, toy-dag-3x4 optimum 11; CP-SAT reports OPTIMAL with the same values.
- Every CP-SAT solution passes the feasibility checker, and the objective evaluator agrees with the CP-SAT objective value.
- mk01: CP-SAT is not worse than any dispatching rule.

Results on the Brandimarte instances (own computation, 10 s time limit, 8 workers, one run each; best rule = best of the 12 dispatching combinations of [11](11_dispatching-rules.md); warm start see section 6):

| | best rule | cold | bound | gap | warm | bound | gap |
|---|---|---|---|---|---|---|---|
| mk01 | 42 | 40 | 40 | 0.0 % | 40 | 40 | 0.0 % |
| mk02 | 30 | 26 | 26 | 0.0 % | 27 | 25 | 7.4 % |
| mk03 | 204 | 204 | 204 | 0.0 % | 204 | 204 | 0.0 % |
| mk04 | 70 | 60 | 60 | 0.0 % | 60 | 60 | 0.0 % |
| mk05 | 183 | 175 | 170 | 2.9 % | 176 | 170 | 3.4 % |
| mk06 | 73 | 66 | 37 | 43.9 % | 65 | 39 | 40.0 % |
| mk07 | 150 | 148 | 133 | 10.1 % | 145 | 133 | 8.3 % |
| mk08 | 523 | 523 | 523 | 0.0 % | 523 | 523 | 0.0 % |
| mk09 | 311 | 307 | 307 | 0.0 % | 307 | 307 | 0.0 % |
| mk10 | 227 | 251 | 183 | 27.1 % | 215 | 183 | 14.9 % |

Gap = (makespan − bound) / makespan. The optimum lies in [bound, makespan]; at gap 0 CP-SAT has proven optimality itself. No comparison with best-known values from the literature yet (these must be taken from a cited source).

**Runs are not reproducible.** With 8 workers the parallel search depends on timing: in an earlier cold run with the same settings mk02 ended at 27 with bound 25 (FEASIBLE), here at 26 with bound 26 (OPTIMAL); mk06 gave 64 / 38 and mk10 253 / 183. For reported results either use `workers=1` (slower, reproducible for a given seed **[uncertain: not tested]**) or repeat runs and report mean and spread.

Observations:

- mk03 and mk08 are solved at the best rule's value: there the rule was already optimal.
- Within 10 s, CP-SAT's bound is close to simple bounds (largest forced machine load on mk07: 133 = bound; total minimum work divided by the number of machines on mk05: 168 vs. bound 170). On instances with high routing flexibility (mk02: 4.1, mk06: 3.3 eligible machines per operation on average) the bounds are weak, because a lower bound cannot know which machine receives which work. With 60 s: mk02 27 / 26, mk06 58 / 49 (one run each).

## 6. Warm start

**What.** CP-SAT receives a complete, feasible schedule as a *solution hint*: for every operation the hinted start $S_o$, end $C_o$ and machine choice ($x_{o,m} = 1$ for the hinted machine, 0 otherwise). The hint used is the best of the 12 dispatching combinations under the objective (`simulation.planners.dispatching.best_dispatch`), so it is cheap (milliseconds) and always feasible (checker-tested, [11](11_dispatching-rules.md)).

**Why.** A cold start begins without any solution. On large instances the search may need most of the time limit to reach the quality a simple rule achieves immediately (mk10: cold 251–253 after 10 s vs. 227 for MWKR + ECT). A hint lets the search start from a good schedule and improve it.

**What it does not do.**

- A hint is **not a hard constraint**: the solver tries to stay close to it for a while and then gradually returns to its default search; partial and infeasible hints are allowed (Google OR-Tools, CP-SAT model documentation, section "Solution hinting"). "Never worse than the rule" is therefore observed, not guaranteed. A guarantee would need either an upper bound on the objective ($C_{\max} \le$ value of the hint; valid because the hint is feasible) or returning the hint if CP-SAT ends worse. Neither is implemented.
- It does **not improve the lower bound**: the bound comes from the solver's reasoning about the constraints, not from known solutions (table: bounds are the same or within ±2 of the cold run). Proving optimality is not easier with a hint.
- It can **bias** the search towards the hinted region: in the run above the warm start ended worse than the cold start on mk02 (27 vs. 26) and mk05 (176 vs. 175). Because of the run-to-run variance (section 5) one run per instance does not show whether this is systematic.

**Result (one run each, 10 s):** large improvement on the largest instance (mk10: 251 → 215, now better than the rule), small improvements on mk06 and mk07, no change where cold already proves optimality, slightly worse on mk02 and mk05.

**Use in the thesis.** For the GA and the DES the relevant setting will be rescheduling under a time limit, where a previous plan exists. That plan is a natural hint; the warm start is a first step towards that.

## 7. Complete rescheduling from a snapshot

For a complete rescheduling at time $t$ ([05](05_rescheduling-frozen-part.md)) the model is built from the snapshot:

| Constraint | CP-SAT |
|---|---|
| C7 frozen operations | start and end are constants (realized or expected times of the snapshot); a fixed interval $[\hat S_o, E_o)$ on their machine enters `add_no_overlap`; no assignment variables, no C2 |
| C6 not before $t$ | lower bound of the start variable: $S_o \ge \max(r_{k(o)}, t)$ |
| C3 with frozen predecessors | $S_{o'} \ge E_o$ with the constant end of the frozen predecessor |
| change budget $\kappa$ | with a reference plan $\bar m(o)$ (the repaired plan): $\sum_{o \text{ free}} (1 - x_{o,\bar m(o)}) \le \kappa$ |

The horizon becomes $\max(r_{\max}, t, \max E_o) + \sum_{o \text{ free}} \max_m p_{o,m}$. The budget turns stability into a constraint (ε-constraint in the sense of Dauzère-Pérès et al., 2024, p. 416): the solver finds the best plan with at most $\kappa$ changed machine assignments instead of a plan that is accepted or rejected as a whole. The repaired plan is also the hint.

`simulation.planners.cpsat.solve(..., snapshot, reference, change_budget)` and `cpsat_planner(time_limit, workers=1, seed, change_budget, objective)` with the planner interface `(ci, snapshot, current_plan) -> plan`. One worker by default, so that a run with the same seed is reproducible. Without a solution within the time limit the planner returns the current plan (**shortcut**; raise the limit if this occurs).

**Hand-checked optimum** (test `test_optimum_from_a_snapshot`): toy plan, snapshot at $t = 5$ with a1 finished [0, 3), a2 running on M3 and b1 overrunning on M1 (both expected to end at 6). b2 and b3 cannot start before 6; for b4 to end at 11, b3 must run on M4 in [6, 9) and b4 on M4 in [9, 11), but a3 (only M4, from 6) then ends at 13 or later; with b3 on M1, b4 ends at 12 at the earliest. CP-SAT returns 12 with status OPTIMAL.

**Change budget** (tests in `tests/test_rescheduling.py`): weak plan SPT + least load (makespan 15), b1 takes 6 instead of 4, repair at every time point, complete rescheduling with CP-SAT whenever the projected makespan changes ($\delta_C = 0$):

| $\kappa$ | realized makespan |
|---|---|
| repair only | 17 |
| 0 (only new times and sequences) | 16 |
| 1 | 15 |
| 2 or unbounded | 14 |

On the good toy plan (b1 takes 4 instead of 2) CP-SAT keeps all machines and realizes 13, the same as repair alone, whereas the rule-based rescheduling realizes 14 ([05](05_rescheduling-frozen-part.md) §5).

## 8. Assumptions and open points

- Warm start without guarantee (see section 6); the upper-bound variant is a one-line addition if needed.
- Trivial horizon $H$; a tighter horizon from a dispatching schedule would shrink the domains (valid only for the makespan objective).
- Time limit and number of workers are fixed for the table above; the dependency on both, and the variance between runs, are not studied systematically.
- Objectives: makespan, total tardiness, number of tardy orders; the thesis objective (possibly a combination with flow time or stability) is still to be decided ([01](01_basic-fjsp.md), §6).
- The budget counts machine changes only; changed sequences and start times are not limited (stability measures with them follow, [05](05_rescheduling-frozen-part.md) §6).

## 9. Sources

- CP models of the FJSP with arbitrary precedence / release times: Kasapidis et al. (2021), (18)–(22), p. 4049; Lunardi et al. (2020), (33)–(40), p. 8; Naderi & Roshanaei (2022), (8)–(12), p. 5.
- Semi-active schedules contain an optimum for regular criteria: Dauzère-Pérès et al. (2024), p. 414.
- OR-Tools API and the alternative formulation with `only_enforce_if` linking: Google OR-Tools, example `flexible_job_shop_sat`; solution hints: Google OR-Tools, CP-SAT model documentation; see [references.md](references.md).
- Own: transfer to CP-SAT with a shared start variable, horizon, objective interface, warm start from the best dispatching rule.

## 10. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-20 | uncommitted | Static CP-SAT model of C1–C5 with makespan objective; brute-force verification on toys; Brandimarte results. |
| 2026-10-20 | uncommitted | Warm start from the best dispatching schedule (`hint`); cold/warm result table; run-to-run variance documented. |
| 2026-10-30 | uncommitted | Complete rescheduling from a snapshot: frozen operations as fixed intervals, C6 as lower bound, change budget as constraint, `cpsat_planner`; hand-checked optimum and budget table. |
| 2026-10-30 | uncommitted | Tardiness objectives available (mapping in 06). |
| 2026-10-30 | uncommitted | Lexicographic objectives (see 06). |
| 2026-11-02 | uncommitted | Runs: C8 (equal machine choices) and C9 (span interval). |
| 2026-11-03 | uncommitted | Batches: slot formulation. |
