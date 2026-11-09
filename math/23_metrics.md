# 23 Metrics of an execution run

Files `2x` describe data generation and experiments.

## 1. Prose description

An experiment executes a start plan under a scenario with a policy of the planning tool ([05](05_rescheduling-frozen-part.md)) and compares the outcome. Vieira et al. (2003, p. 47) group rescheduling performance measures into schedule efficiency, schedule stability and cost. This file defines a basic set of the first two plus the effort of the planning tool, computed once per run from the realized schedule, the start plan and the decision log. Cost measures need cost data from the company and are left out.

- **Efficiency:** realized makespan; mean flow time of the orders (time from release to completion of the last operation; in the dental process this is the lead time of an order inside production). Tardiness is not possible yet: the instance format has no due dates.
- **Stability against the start plan:** how far the realized schedule is from the plan the shop floor was given first. Stability as "deviation from the original predictive schedule", measured by start-time deviations and by sequence deviations, goes back to Wu et al. (via Ouelhadj & Petrovic, 2009, p. 418; Vieira et al., 2003, p. 47); Dauzère-Pérès et al. (2024, p. 415) name the deviation of operation start times for the FJSP. In a flexible job shop a change of machine is a second, stronger kind of change; it is counted separately (own choice, analogous to the change budget $\kappa$ in [05](05_rescheduling-frozen-part.md)).
- **Effort / nervousness:** number of plan revisions and of complete reschedulings, and the computation time of the planner. Vieira et al. (2003, p. 46) define stability as the number of revisions a schedule undergoes during execution; Aytug et al. (2005, p. 97) interpret the number of rescheduling activities as a surrogate for the disruption to the shop floor.

The deviation of the realized schedule from the start plan mixes two causes: the disturbances themselves (also without any planning tool) and the plan changes of the planning tool. The comparison between policies on the same scenarios separates them.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

| Symbol | Meaning |
|---|---|
| $m^0(o)$, $S^0_o$ | machine and start of $o$ in the start plan |
| $\hat C_k = \max_{o \in O_k} \hat C_o$ | realized completion of order $k$ |
| $\bar F$ | mean flow time of the orders |
| $D_S$, $N_M$ | mean absolute start deviation; number of machine changes against the start plan |
| $N_R$, $N_C$, $N_A$ | number of repairs, complete reschedulings, accepted complete reschedulings in one run |

## 3. Definitions

(M1) Realized makespan:
$$\hat C_{\max} = \max_{o \in O} \hat C_o$$

(M2) Mean flow time: average time an order spends from its release to its completion.
$$\bar F = \frac{1}{|\mathcal{K}|} \sum_{k \in \mathcal{K}} \big(\hat C_k - r_k\big)$$

(M3) Mean absolute start deviation from the start plan:
$$D_S = \frac{1}{|O|} \sum_{o \in O} \big\lvert \hat S_o - S^0_o \big\rvert$$

(M4) Machine changes against the start plan:
$$N_M = \big\lvert \{ o \in O : \hat m(o) \neq m^0(o) \} \big\rvert$$

(M6) Due-date metrics, only for instances with due dates (orders $k \in \mathcal{K}^d$, [06](06_due-dates.md)): total tardiness $\sum_k T_k$, number of tardy orders $\sum_k U_k$, maximum lateness $L_{\max} = \max_k L_k$ (negative if every order is early). Computed from the realized order completions $\hat C_k$.

(M5) Effort: $N_R$ (repairs that changed the plan, i.e. plan revisions sent to the factory), $N_C$ (complete reschedulings triggered), $N_A \le N_C$ (accepted), and the total wall-clock time of the planner calls in seconds.

## 4. Objective function

Not affected: the metrics evaluate runs; the planners still minimize the makespan ([01](01_basic-fjsp.md) §4).

## 5. Implementation in code

- `simulation.metrics.run_metrics(ci, plan, result) -> dict`: one flat record per run with the keys `planned_makespan`, `makespan` (M1), `mean_flow_time` (M2), `mean_start_deviation` (M3), `machine_changes` (M4), `repairs`, `reschedulings`, `accepted_reschedulings`, `planner_time` (M5), and with due dates `total_tardiness`, `tardy_orders`, `max_lateness` (M6). The M6 keys are left out for instances without due dates, so that all rows of one experiment have the same columns (one CSV per instance set). `plan` is the start plan, `result` the `ExecutionResult` of `simulation.control.rescheduling.execute`.
- **M7 worker metrics** (instances with workers, [04](04_workers.md)): `overstay` (sum of the OVERSTAY minutes of the factory log: oven removals delayed by a busy worker), `swaps` (number of SWAP records); with a work calendar in addition, from the realized share intervals (`check.feasibility.worker_intervals`, realized share lengths) and the realized breaks (`ExecutionResult.breaks`): `overtime` $= \sum_{z,\nu} \max(0,\ e_{z,\nu} - h^{\mathrm{E}})$ with $e_{z,\nu}$ the end of worker $z$'s last share on day $\nu$ (minutes after the regular shift end), `overruns` (shares ending after $h^{\mathrm{E}} + \overline{\mathrm{ot}}$), `break_postponement` $= \sum_{\text{breaks}} \max(0, \operatorname{mod}(\mathrm{br}) - h^{\mathrm{B}-})$, `break_spread` $= \sum_\nu (\max_z \mathrm{br}_{z,\nu} - \min_z \mathrm{br}_{z,\nu})$ over the days with breaks. Own definitions; the planned objective terms (spec §5) will use the same quantities. Hand values (`tests/test_worker_snapshot_metrics.py`): packaging 19:00–19:40 → overtime 130, 1 overrun; A's break at 12:20, B's at 12:00 → postponement 20, spread 20; one swap; one-worker oven removal 3 minutes late → overstay 3; without disturbance all 0.
- The planner time is measured in `_reschedule` around the planner call (`time.perf_counter`) and stored in each `REPLAN` record as `planner_time`. It is the only non-deterministic value of a run.
- `simulation.io.json_loader.write_csv(rows, path)`: results as CSV, one row per run.
- Tests (`tests/test_metrics.py`), hand-computed on the toy plan (releases A 0, B 2, C 4):
  - no disturbance: makespan 11, order ends 8, 11, 10, $\bar F = (8 + 9 + 6)/3 = 23/3$, $D_S = 0$;
  - a3 takes 8 instead of 2, repair only: makespan 16, $\bar F = (14 + 14 + 6)/3 = 34/3$, b4 starts at 14 instead of 9, $D_S = 5/9$, $N_R = 6$;
  - same with rescheduling ($\delta_C = 2$, rule SPT): b4 on M2 $[11, 14)$, makespan 14, $\bar F = 32/3$, $D_S = 2/9$, $N_M = 1$, $N_C = N_A = 1$.

**First results** (notebook `04_rescheduling`, mk01, 10 scenarios, best dispatching plan as start plan, $\sigma = 0.3$ with start offsets $q = 0.5$, $a = b = 5$; own computation, one run):

| policy | $\hat C_{\max}$ | $\bar F$ | $D_S$ | $N_M$ | $N_C$ |
|---|---|---|---|---|---|
| no planning tool | 58.7 | 39.3 | 6.9 | 0 | 0 |
| repair only | 58.7 | 39.2 | 7.0 | 0 | 0 |
| rule SPT + ECT, $\delta_C = 2$, $\delta_S = 10$ | 55.0 | 37.2 | 5.7 | 5.2 | 5.7 |
| CP-SAT, $\delta_C = 2$, $\delta_S = 10$ | 51.7 | 40.6 | 8.1 | 8.1 | 6.1 |
| CP-SAT, $\delta_C = 0$ | 50.0 | 40.6 | 8.6 | 8.9 | 21.0 |
| CP-SAT $\kappa = 5$, $\delta_C = 0$ | 50.3 | 40.2 | 8.1 | 8.2 | 21.3 |

CP-SAT, which minimizes the makespan only, has the lowest makespan but a higher mean flow time and more machine changes than the rule planner. The budget $\kappa$ limits changes per rescheduling, not per run, so $N_M$ over a run is barely lower.

## 6. Assumptions and open points

- Due dates are generated ([06](06_due-dates.md)); which delivery dates the company actually has is still to be clarified.
- No sequence-deviation measure yet. Wu et al. (1993, `TLCUQTJ9`, p. 4) define two deviations of a new schedule: $D_o$, the total absolute deviation of the start times from the original schedule (our $D_S$ up to the factor $1/|O|$), and $D_s$, called sequence deviation, which is the total absolute deviation of the start times from the **right-shift schedule** (original sequence kept, jobs pushed right). So their sequence deviation is not a count of swapped pairs but a start-time deviation against the plan that keeps the sequence. Our analogue: the start deviation of a policy's realized schedule from the run with repair only on the same scenario (a comparison of two runs, not a single-run metric); to be added if needed.
- Candidate set of stability measures from Shiau, Chen & Fan (2026, `F5VQRD7Z`, preprint, pp. 11–12): (i) start-time shift (mean, maximum, sum), (ii) share of moved operations with a tolerance, (iii) machine changes, (iv) **sequence similarity per machine as Kendall's concordance** of the pairs of operations kept on the same machine (in per cent; original Kendall 1938 not in the library), (v) changes inside the frozen window; aggregated into a stability score in [0, 100] with weights 0.35 / 0.25 / 0.15 / 0.15 / 0.10 chosen by the authors (no calibration). (iv) is a concrete sequence-deviation measure for single runs; (i) and (iii) correspond to $D_S$ and $N_M$.
- Stability is measured only for the realized schedule against the start plan, not between successive plan revisions (e.g. the average absolute change of start and completion times per revision, Cowling & Johansson, cited in Vieira et al., 2003, p. 46; original not in the library).
- $D_S$ averages over all operations, including those that did not move; a robust alternative (share of operations that moved, maximum deviation) can be added if the distribution matters.
- Machine utilization is not computed.

## 7. Sources

- Classification efficiency / stability / cost; stability as number of revisions; deviation from the initial schedule: Vieira et al. (2003), pp. 46–47.
- Start-time and sequence deviation as stability measures: Wu et al. (1993), p. 4; Ouelhadj & Petrovic (2009), p. 418.
- Number of rescheduling activities as surrogate for shop-floor disruption: Aytug et al. (2005), p. 97.
- Deviation of operation start times as stability criterion in the FJSP: Dauzère-Pérès et al. (2024), p. 415.
- Own: machine changes as separate measure, flow time from order release, the run record.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-09 | uncommitted | Maximum overtime written $\overline{\mathrm{ot}}$ (missed in the rename). |
| 2026-11-09 | uncommitted | Symbols renamed (protocol 2026-11-09 (24)): worker $z$, day $\nu$ in M7; machine changes $D_M$ → $N_M$ (a count, like $N_R$, $N_C$, $N_A$; $D$ stays for deviations). |
| 2026-11-08 | uncommitted | Break start written $\mathrm{br}_{w,d}$ (renamed from $b_{w,d}$, [notation](notation.md)). |
| 2026-11-06 | uncommitted | M7 worker metrics: overstay, swaps; with a calendar overtime, overruns, break postponement and spread; hand values in `tests/test_worker_snapshot_metrics.py`. |
| 2026-10-30 | uncommitted | First version: M1–M5, planner time in the decision log, CSV output. |
| 2026-10-30 | uncommitted | Definition of the sequence deviation of Wu et al. (1993) read and recorded. |
| 2026-10-30 | uncommitted | M6 due-date metrics (total tardiness, tardy orders, maximum lateness); test with hand values (a3 overrun, due dates 10/11/10: lateness 4, 5, 0). |
| 2026-10-30 | uncommitted | Stability measures of Shiau et al. (2026) recorded as candidates (Kendall concordance for sequences). |
