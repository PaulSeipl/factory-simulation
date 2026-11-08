# 05 Rescheduling and frozen part

## 1. Prose description

In production the plan is executed under disturbances: operations take longer or shorter than planned, and workers start them earlier or later. The plan therefore has to be adapted during execution. The thesis follows the **predictive-reactive** strategy: a plan is generated in advance and revised when events occur. Completely reactive scheduling (no plan, rules decide on the fly) and robust pro-active scheduling (a plan that absorbs disturbances in advance) are the other two strategies named in the literature (Li et al., 2021, PDF p. 5; Dauzère-Pérès et al., 2024, p. 415; Ouelhadj & Petrovic, 2009, pp. 419–420).

Two kinds of revision are distinguished (Ouelhadj & Petrovic, 2009, p. 419; Vieira et al., 2003, pp. 54–55):

- **Schedule repair:** a local adjustment of the current plan; cheap, and the plan stays stable. Right-shift rescheduling postpones remaining operations by the time needed to make the schedule feasible again (Vieira et al., 2003, p. 54).
- **Complete rescheduling (regeneration):** all operations not yet processed are scheduled anew (Vieira et al., 2003, p. 55). Pinedo (2022, p. 494) warns that a plan generated from scratch may differ completely from the original one and cause confusion on the shop floor; minor disruptions may need only a simple change, major ones substantial changes.

**Policy of the thesis (version 1):** at every event the plan is repaired (cheap); only if the repair causes a substantial change is a complete rescheduling triggered. This is a variant of the hybrid policy, which reschedules periodically and additionally when special events occur (Vieira et al., 2003, pp. 51–52 **[uncertain: page]**; Ouelhadj & Petrovic, 2009, p. 420); here exceptions are detected by thresholds on the effect of the repair instead of by event type. Implemented: the repair, the thresholds and the complete rescheduling with dispatching rules; complete rescheduling with CP-SAT follows.

**Roles.** The DES is the factory: it executes the plan it receives, under the disturbances of the scenario, and decides nothing. Repair and complete rescheduling are done by the **planning tool** (the application layer between planner and MES), which observes the factory only through the snapshot and sends it a new plan. Terminology (binding, `CLAUDE.md`): **repair** = shift repair (left/right shift, machine assignment and order per machine unchanged; "schedule repair" in Vieira et al., 2003); **complete rescheduling** = a planner generates a new plan for all operations not yet started ("regeneration" in Vieira et al., 2003).

The **frozen part** of the factory at time $t$ consists of the operations that have already started (finished or running). They cannot be changed by any revision of the plan. Later also started loads belong to it.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

- $t$: current time (rescheduling point)
- $\bar S_o, \bar C_o$: start and completion of $o$ in the **current plan** (the plan last sent to the MES), $\bar C_o = \bar S_o + p_{o,\bar m(o)}$ for operations not started
- $\bar S'_o, \bar C'_o$: start and completion of $o$ in the **repaired plan**
- $B(o)$: blockers of $o$: its predecessors $\{q : (q,o) \in P\}$ and the operation $\operatorname{prev}(o)$ planned directly before it on $\bar m(o)$
- $\tilde C_o$: expected completion of a running operation ([13](13_des.md))

## 3. Constraints and repair rule

Every revised plan must satisfy, in addition to C1–C5 of [01](01_basic-fjsp.md):

(C6) No operation that has not started is planned before the current time.
$$\bar S'_o \ge t \qquad \forall o \text{ not started at } t$$

(C7) The frozen part is unchanged: finished operations keep their realized times, running operations their machine and realized start.
$$\bar m'(o) = \bar m(o),\ \bar S'_o = \hat S_o \qquad \forall o \text{ started at } t$$

With workers and a calendar, C6 and C7 also hold for breaks (C6$^b$, C7$^b$), and a forced postponement past the
break window is allowed (C14$^f$); see [04](04_workers.md) §3.

**Shift repair.** Machine and order per machine stay as planned. Known end of a blocker:
$$E_q = \begin{cases} \hat C_q & q \text{ finished} \\ \tilde C_q = \max(\hat S_q + p_{q,\bar m(q)},\ t+1) & q \text{ running} \\ \bar C'_q & q \text{ not started (already repaired)} \end{cases}$$

For every operation not started, in the order of $\bar S_o$ (a feasible plan lists blockers first):
$$\beta_o = \max\big(r_{k(o)},\ \max_{q \in B(o)} \bar C_q\big) \quad \text{(old block)}, \qquad \beta'_o = \max\big(t,\ r_{k(o)},\ \max_{q \in B(o)} E_q\big) \quad \text{(new block)}$$
$$\bar S'_o = \begin{cases} \beta'_o & \text{if } \bar S_o = \beta_o \quad \text{(tight: moves with its blocker, earlier or later)} \\ \max(\bar S_o,\ \beta'_o) & \text{otherwise (gap: kept unless the blocker now ends later)} \end{cases}, \qquad \bar C'_o = \bar S'_o + p_{o,\bar m(o)}$$

Consequences:

- Without any deviation $\beta'_o = \beta_o$ and the plan is unchanged; gaps in the plan (e.g. of a CP-SAT plan) are kept. This keeps the zero-disturbance test valid.
- An early finish pulls only the operations forward that were waiting for it (left shift); a late finish pushes them back (right shift).
- C6 holds since $\beta'_o \ge t$; C7 holds since started operations are not touched; C3–C5 hold for the planned durations by construction.
- A batch (operations of a batch step with the same machine and planned start, [03](03_carriers.md)) moves as one: within the batch nobody waits for a fellow member, and all members start at the latest start any of them needs.
- The repair uses only the snapshot information (realized past, starts of running operations, planned durations), never the scenario.

**Trigger.** At every repair that changes the plan, three metrics compare the repaired plan with the **anchor** $\bar S^A_o, \bar C^A_o$: the plan the last complete rescheduling settled on (accepted: its new plan; rejected: the repaired plan it was compared with), at first the start plan:
$$\Delta C = \max_o \bar C'_o - \max_o \bar C^A_o \quad \text{(deviation of the projected makespan)}, \qquad \Delta S = \max_{o \in N} |\bar S'_o - \bar S^A_o| \quad \text{(largest start deviation)}$$
$$\Delta S_{\mathrm{mean}} = \frac{1}{|N|} \sum_{o \in N} |\bar S'_o - \bar S^A_o| \quad \text{(mean start deviation)}, \qquad N = \{o \text{ not started}\}$$
A complete rescheduling is triggered if $|\Delta C| > \delta_C$ or $\Delta S > \delta_S$ or $\Delta S_{\mathrm{mean}} > \delta_{S,\mathrm{mean}}$. Each threshold is optional (`None`: that trigger is off), so the max and the mean can be compared in an ablation. Left shifts count as well: a substantial improvement is also a substantial change (direction of the triggers: open, §6).

Why the mean next to the max: the max reacts to a single operation, however many others stay on time; the mean is the average shift an order, worker or carrier planned on these start times has to absorb. The total $\sum_{o \in N} |\bar S'_o - \bar S^A_o|$ (Wu et al., 1993, `TLCUQTJ9`, PDF p. 4: total start time deviation) is not used: it falls over a run since $N$ shrinks, and it grows with the instance, so one threshold would have to depend on $|N|$; the mean is that total divided by $|N|$. The completion of the last operation is already covered by $\Delta C$, so a delay of 3 minutes that pushes 40 operations by 3 minutes each is $\Delta C = 3$, $\Delta S = 3$, $\Delta S_{\mathrm{mean}} \approx 3$, but a sum of 120. Sources for the idea: a trigger when the progress differs from the schedule by more than a limit (Vieira et al., 2003, `H76SDH6L`, PDF p. 13, printed p. 49–50 **[uncertain: page]**), start-time deviation as the stability measure (Wu et al., 1993, `TLCUQTJ9`, PDF p. 2–4, there as an objective, not as a trigger; Shiau et al., 2026, `F5VQRD7Z`, PDF p. 12, mean, max and sum). No source found for the max or the mean as a trigger against an anchor: own design.

**Trigger on the planner's objective.** If the planner optimizes another objective $f$ than the makespan (e.g. total tardiness, [06](06_due-dates.md)), the makespan threshold may fire too late or for the wrong reason. A third metric compares the projected value of $f$:
$$\Delta f = f(\text{repaired plan}) - f(\text{anchor}), \qquad \text{trigger if } |\Delta f| > \delta_f$$
Example (test `test_trigger_on_the_planners_objective`): toy plan, due dates A 10, B 11, C 10, a3 takes 8 instead of 2. At $t = 9$ a3 is expected to end at 10 (A on time), b4 (next on M4) moves to $[10, 12)$ and B becomes 1 late: $\Delta f = 1$ fires with $\delta_f = 0$, while $\Delta C = 1$ does not exceed $\delta_C = 2$ (the makespan trigger fires only at $t = 11$).

**Periodic safety net (hybrid policy).** Independently of the thresholds, a complete rescheduling is triggered at the latest $\tau$ minutes after the last one (time of the anchor): at $t \ge t_A + \tau$, as long as operations are not started yet. Event-driven triggers plus a periodic one form the hybrid policy (Vieira et al., 2003, pp. 51–55; Ouelhadj & Petrovic, 2009, pp. 419–420). A triggered rescheduling restarts the period. Since the factory may have no event at $t_A + \tau$, the planning tool asks the DES for that time point (WAKE event, [13](13_des.md) §3). Examples (tests `test_periodic_safety_net_without_disturbance`, `test_period_restarts_after_a_triggered_rescheduling`): toy plan without disturbance, $\tau = 4$: reschedulings at 4 and 8 (b4 starts at 9, nothing to plan after it), CP-SAT keeps all machines; with b1 taking 4 instead of 2 and $\delta_C = 1$: periodic at 4, threshold at 6, periodic at 10 (not 8).

Each REPLAN record lists its triggers (`makespan`, `shift`, `mean_shift`, `objective`, `period`).

Hand-checked (test `test_mean_shift_trigger_next_to_the_max_shift_trigger`): toy plan, b1 takes 4 instead of 2, repair only (anchor = start plan). At $t = 5$ the operations not started are a3, b2, b3, b4, c1, c2; b2, b3, b4, c2 start 1 later: $\Delta S = 1$, $\Delta S_{\mathrm{mean}} = 4/6$. At $t = 6$ (a3 and c1 start only after the repair) the same four start 2 later: $\Delta S = 2$, $\Delta S_{\mathrm{mean}} = 8/6$. With $\delta_{S,\mathrm{mean}} = 0.5$ the first complete rescheduling is at $t = 5$ (`mean_shift`); with $\delta_S = 1$ it is at $t = 6$ (`shift`).

The anchor is deliberately not the reference (the plan last sent to the MES, used for the change budget). Measured against the reference, each repair is compared only with the previous repair, and many small deviations never exceed the threshold (drift, observed on mk01: with $\delta_C = 2$ almost no rescheduling while the makespan grew by far more, §5). Measured against the anchor, the deviations add up until a complete rescheduling looks at the plan again. After a rejected rescheduling the anchor moves as well, so that the same deviation does not trigger the planner again at every following time point.

Hand-checked (tests `test_small_repairs_add_up_against_the_anchor`, `test_anchor_moves_to_the_plan_of_a_complete_rescheduling`): toy plan (makespan 11), b1 takes 4 instead of 2, $\delta_C = 1$, planner SPT. The repairs at $t = 5$ and $t = 6$ each change the projected makespan by 1; the deviation from the anchor is 1, then 2 > 1, so a complete rescheduling happens at $t = 6$. With b1 taking 5, the rescheduling at $t = 6$ returns a plan with makespan 14; the new plan expects b1 to end at 7; at $t = 7$ b1 is overdue (OVERDUE event, [13](13_des.md) §3) and the repair deviates from the new plan by 1 (against the start plan it would be 4), so no further rescheduling; realized makespan 15.

Overrun without other events (tests `test_overrun_is_seen_every_minute_after_the_planned_end`, `test_overrun_triggers_rescheduling_without_other_events`): a3 planned $[6, 8)$ on M4 takes 8. From $t = 9$ every OVERDUE event moves b4 (next on M4) by one minute; repair alone realizes b4 in $[14, 16)$. With $\delta_C = 2$ the deviation from the anchor reaches 3 at $t = 11$, the rule planner moves b4 to M2 $[11, 14)$, realized makespan 14.

**Complete rescheduling.** The planner receives the snapshot at $t$ (frozen part with realized or expected times, [13](13_des.md) §6) and the repaired plan, and returns a new complete plan. The new plan must satisfy C1–C7 (checked with the feasibility checker against the snapshot); C2 is not checked for frozen operations, since they carry realized or expected times.

**Acceptance** (option (b); stability as an objective follows later). Let $\kappa$ be the change budget and $\chi$ the number of operations not started whose machine differs between the new and the repaired plan. The new plan is accepted iff
$$\chi \le \kappa$$
If the plan is rejected, the repaired plan stays and is the reference; otherwise the new plan replaces it. The projected makespan of the new plan is recorded but is deliberately no acceptance criterion: the makespan is not the only relevant objective (see the observation in section 5).

## 4. Objective function

Not affected by the repair. Complete rescheduling will use the objective of [01](01_basic-fjsp.md) §4; stability is to enter as an objective term later (section 6).

## 5. Implementation in code

- `simulation.planners.repair.shift_repair(ci, t, machine, order_on, planned_start, planned_end, start, end)`: the repair rule on index arrays. It receives no realized durations and no scenario, so it cannot leak future information.
- `simulation.planners.repair.repair(ci, snapshot, plan)`: the repair with the planner interface (wraps `shift_repair`).
- The planning tool: `simulation.control.rescheduling.execute(ci, plan, scenario, policy)` with `ReschedulingPolicy(planner, max_makespan_change, max_shift, max_mean_shift, change_budget, objective, max_objective_change, period)` (validated: `objective` and `max_objective_change` together, `period` > 0); the anchor is `Anchor(plan, t)`. Per time point of the DES, after its events and before anything starts: snapshot, repair, thresholds $\delta_C$, $\delta_S$, $\delta_{S,\mathrm{mean}}$ against the anchor (kept by `execute`, returned by `adapt_plan`), complete rescheduling with the planner, acceptance with budget $\kappa$, `Simulation.update_plan(new plan)`. Its decisions are recorded separately from the factory log: `REPAIR` (change caused by this repair: `makespan_change`, `max_shift`, `mean_shift`; deviation from the anchor that the trigger uses: `makespan_deviation`, `shift_deviation`, `mean_shift_deviation`) and `REPLAN` (accepted, changed assignments, projected makespan before and after). `planner=None` means repair only.
- The DES (`simulation.sim.des.Simulation`) accepts a new plan only if it satisfies C1–C7 against its own snapshot; released operations are not moved any more ([13](13_des.md) §3).
- Planner interface: `planner(ci, snapshot, current_plan) -> new complete plan`; dispatching rules via `simulation.planners.dispatching.dispatch_planner(sequencing, assignment)`, which runs `dispatch(..., snapshot)` ([11](11_dispatching-rules.md) §5); CP-SAT via `simulation.planners.cpsat.cpsat_planner(time_limit, change_budget, ...)` with the change budget as a constraint ([12](12_cp-sat.md) §7).
- The feasibility checker with snapshot: `check_schedule(ci, plan, snapshot)` reports C6 and C7 ([01](01_basic-fjsp.md) §5).
- The frozen part as seen by a planner: `simulation.sim.snapshot` ([13](13_des.md) §6).

Hand-computed examples on `toy-dag-3x4` (tests `tests/test_repair.py`, `tests/test_des.py`), plan of [13](13_des.md) §5 (makespan 11):

| Disturbance | Without repair | With repair |
|---|---|---|
| none (also with a gap: c2 planned at 9 instead of 8) | plan | plan, no repair |
| a1 takes 2 instead of 3 | makespan 11 | tight chain moves 1 earlier: a2 [2,5), b1 [2,4), b2 [4,7), b3 [4,8), a3 [5,7), c1 [5,7), b4 [8,10), c2 [7,9); makespan 10 |
| same, c2 with gap | – | c2 keeps [9,11) |
| b1 takes 4 instead of 2 | makespan 13 | same realized schedule; repairs at t = 5 and 6 (b1 overruns), makespan change +1 each |
| a2 starts 2 late | a2 [5,8), makespan 12 | same; the delay is counted once |

Complete rescheduling on the same plan, b1 takes 4 instead of 2, $\delta_C = 0$, planner joint SPT ([11](11_dispatching-rules.md)):

| Policy | Rescheduling | Realized makespan |
|---|---|---|
| repair only | – | 13 |
| with rescheduling | t = 5: projected 13 instead of 12, accepted; t = 6: 14, accepted | 14 (worse than repair only) |
| with rescheduling, budget $\kappa = 0$ | both rejected (2 changed machines each) | 13 |

**Observation:** a rule-based complete rescheduling of a good plan can make the makespan worse than simply repairing it. An earlier version rejected such plans (improvement condition); it was removed because the makespan is not the only relevant objective, and stability is to enter the objective later.

Starting instead from the weaker plan SPT + least load (makespan 15), b1 takes 6 instead of 4, planner ECT + SPT: repair alone realizes 17; at $t = 6$ the new plan projects 14 < 16 and is accepted; realized makespan 14.

With CP-SAT as planner the same cases give: good plan 13 (all machines kept, no worse than repair); weak plan 16 / 15 / 14 for $\kappa = 0 / 1 / 2$ ([12](12_cp-sat.md) §7). The budget trades stability against makespan.

On the Brandimarte instances with random disturbances ($\sigma = 0.3$, start offsets $q = 0.5$, $a = b = 5$, 2 seeds, best dispatching plan, $\delta_C = 2$, $\delta_S = 10$, planner ECT + SPT, no budget) 36 complete reschedulings were triggered and accepted; all realized schedules satisfy C1, C3, C4, C5 (tests).

mk01, 10 scenarios per setting (seeds 0–9), best dispatching plan as start plan (planned 42), mean realized makespan (notebook `04_rescheduling`, own computation, one run; trigger against the anchor):

| policy | durations only ($\sigma = 0.3$) | durations + offsets ($q = 0.5$, $a = b = 5$) |
|---|---|---|
| no planning tool | 46.1 | 58.7 |
| repair only | 45.3 | 58.7 |
| rule SPT + ECT, $\delta_C = 2$, $\delta_S = 10$ | 44.3 (1.6 reschedulings) | 55.0 (5.7) |
| CP-SAT 0.5 s, $\delta_C = 2$, $\delta_S = 10$ | 43.7 (1.6) | 51.7 (6.1) |
| CP-SAT, $\delta_C = 0$ | 42.8 (8.4) | 50.0 (21.0) |
| CP-SAT $\kappa = 5$, $\delta_C = 0$ | 41.9 (7.9) | 50.3 (21.3) |

With the OVERDUE event the means are unchanged on mk01 (overruns are seen through other events soon enough there); only the numbers of reschedulings rise slightly. Before the anchor, $\delta_C = 2$ triggered 0.1 reschedulings per run with offsets and realized 58.7 (drift). Repair alone gains nothing with start offsets: late workers keep the plan behind, so an operation is rarely ready before its planned start (no use for a left shift).

## 6. Assumptions and open points

- The reference is always the plan last sent to the MES, i.e. after every repair the repaired plan, after an accepted rescheduling the new plan.
- **Tight starts and further resources:** "tight" is decided with the modeled blockers only (release, predecessors, previous operation on the same machine). Once workers and loads are modeled, a planned start may be tight because of them (e.g. a worker becomes available); the repair must then include them as blockers, otherwise it pulls such operations forward.
- **Accumulated drift:** observed on mk01 with the trigger measured against the reference (§5). Fixed by the anchor (§3); in addition the periodic safety net $\tau$ (§3, implemented 2026-10-30). The choice of $\tau$ is open (experiments).
- **Direction of the triggers (open, user's objection 2026-11-04):** $\Delta C$, $\Delta S$ and $\Delta f$ are two-sided: a repaired plan that is better than the anchor also triggers. Argument for it (own, untested): an early finish frees capacity that the repair cannot use beyond left-shifting tight operations (machines and order stay), a complete rescheduling might. Against it: for tardiness the value cannot fall below 0, so a trigger from 1 to 0 has nothing to gain; for the makespan the gain is speculative. Candidate: $\Delta f > \delta_f$ one-sided (only a projected worsening), the makespan and shift triggers decided by an ablation (two-sided vs. one-sided).
- **Ablation of the start-shift trigger (open):** max ($\delta_S$) vs. mean ($\delta_{S,\mathrm{mean}}$) vs. both vs. neither on mk01 (notebook `04_rescheduling`); the mean is implemented (2026-11-04), not yet evaluated.
- **Dynamic threshold (later):** a threshold that depends on the state, e.g. relative to the remaining work, $\lvert \Delta C \rvert > \delta \cdot (\max_o \bar C^A_o - t)$. Own idea, no source yet **[uncertain]**; to be checked in the literature before use.
- **Stability:** a new plan with too many changed machine (later worker) assignments is not wanted. Implemented for dispatching rules: a plan exceeding the budget $\kappa$ is rejected and the repaired plan kept. Implemented for CP-SAT: the budget as a constraint (ε-constraint, Dauzère-Pérès et al., 2024, p. 416), so that the planner finds the best plan within it ([12](12_cp-sat.md) §7). Planned for the GA. Later stability as an objective term (Dauzère-Pérès et al., 2024, p. 415).
- **Frozen horizon (later):** operations of the plan in force that start within $[t, t+F]$ are also kept at a complete rescheduling; new orders and the rest are planned around them. Open: keep start times, or only machine and sequence. Literature check (2026-10-30):
  - Zotero (collection MA), check before Shiau et al. (2026) was added: no source used the term. Closest: Pinedo (2022, `5Y6PACF8`, ch. 17, PDF p. 483, 487, exercise 17.7 on PDF p. 493; printed pages not checked) describes interactive systems in which a user freezes single jobs and reoptimizes the rest around them, optionally with tolerances so that frozen jobs may still move a little.
  - Not in the library, found by web search, metadata checked, full text not read **[uncertain]**: Sridharan, V., Berry, W. L., & Udayabhanu, V. (1987). Freezing the master production schedule under rolling planning horizons. *Management Science*, 33(9), 1137–1149. https://doi.org/10.1287/mnsc.33.9.1137 (freezing method, freeze interval length, planning horizon length as decision variables; order-based freezing better than period-based); Blackburn, J. D., Kropp, D. H., & Millen, R. A. (1986). A comparison of strategies to dampen nervousness in MRP systems. *Management Science*, 32(4), 413–429. https://doi.org/10.1287/mnsc.32.4.413 (freezing and change costs dominant). Both are MPS/MRP level, not shop-floor scheduling; to be added to Zotero and read before citing.
  - Industry (no scientific source): an MES/APS vendor documentation describes a "frozen period" in which the replanning tries to keep resource assignments and sequences, not start times, and replans normally if it becomes infeasible (Critical Manufacturing help, Replanning).
  - In the library since 2026-10-30: Shiau, Chen & Fan (2026, `F5VQRD7Z`, preprint, not peer-reviewed). Full rescheduling under a frozen horizon $H$: operations starting within $H$ after the event keep **machine and start time**; operations directly hit by the event are excluded from the frozen set, and once a step of a job is released, all its later steps are released too (p. 10, "Every operation of F keeps its machine and start time", p. 17). Their validation shows the trade-off: on their small instance a full rescheduling recovers 62.5 % of the event damage for $H \le 4$ h, while for $H \ge 8$ h every full candidate is worse than right-shift repair (Table 11, p. 21). They motivate $H$ as the span genuinely committed on the shop floor (material kitted, set-ups done), not a constant.
  - Related guard (same source, p. 13): **anti-thrashing**, a minimum interval between two full reschedulings unless the event is severe. It is the counterpart of our periodic safety net (a maximum interval).
- **OVERDUE (resolved 2026-10-30):** before, an operation running past its planned end was only noticed at the next unrelated event (toy: a3 planned end 8, actual 14; no repair between 10 and 14). Now an OVERDUE event fires at the expected end, then every minute ([13](13_des.md) §3). Open: a re-estimated remaining time instead of the minute steps (fewer repairs, needs a model of the remaining time).
- **Periodic safety net (todo):** see drift above.
- **Metrics:** basic set implemented in [23](23_metrics.md) (2026-10-30); still open: tardiness (no due dates), sequence deviation, stability between plan revisions.
- Repair and rescheduling take no simulated time; computation time is to be recorded (Li et al., 2021, PDF p. 2, stress the response time).
- **Robust pro-active scheduling for the QM rework loops (later):** QM steps may send parts back to remilling, possibly several times. The routing itself is then uncertain (operations may occur zero, one or several times), which needs changes in instance format, scenario and DES. Inserting idle time is one rule for robust schedules (Pinedo, 2022, p. 497).

## 7. Sources

- Strategies (completely reactive, predictive-reactive, robust pro-active): Li et al. (2021), PDF p. 5; Dauzère-Pérès et al. (2024), p. 415; Ouelhadj & Petrovic (2009), pp. 419–420.
- Repair vs. complete rescheduling, right-shift, policies periodic/event-driven/hybrid, nervousness: Vieira et al. (2003), pp. 51–55; Ouelhadj & Petrovic (2009), pp. 419–420.
- Confusion caused by regenerated plans; robustness measure with unchanged sequences; idle-time rule: Pinedo (2022), pp. 494–497.
- Own: the tight/gap rule of the shift repair (left and right shift), the trigger metrics and thresholds measured against the anchor, the acceptance rule (change budget), the start rule for offsets: late offsets count from actual readiness ([13](13_des.md) §3), the separation of DES and planning tool.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-29 | uncommitted | Shift repair (left and right shift, gaps kept) at every time point of the DES; C6, C7; trigger metrics logged; open points thresholds, drift, stability, QM rework. |
| 2026-10-29 | uncommitted | Thresholds trigger a complete rescheduling with a planner on the snapshot; acceptance with change budget and improvement condition; checker C6/C7; examples. |
| 2026-10-30 | uncommitted | Roles: repair and complete rescheduling done by the planning tool (`simulation.control.rescheduling`), not the DES; improvement condition removed (observation kept); terminology repair / complete rescheduling; open point tight starts with workers and loads. |
| 2026-10-30 | uncommitted | CP-SAT as planner for the complete rescheduling, change budget as constraint; results for the toy cases. |
| 2026-10-30 | uncommitted | Brandimarte count recomputed after the late-offset rule changed (13 §3). |
| 2026-10-30 | uncommitted | mk01 comparison of the policies over 10 scenarios (notebook). |
| 2026-10-30 | uncommitted | Trigger measured against the anchor (plan of the last complete rescheduling, at first the start plan) instead of the plan last sent; fixes the drift. Dynamic threshold noted for later. |
| 2026-10-30 | uncommitted | mk01 results with the anchored trigger, durations only and with offsets. |
| 2026-10-30 | uncommitted | Literature check for the frozen horizon; open points OVERDUE event and metrics. |
| 2026-10-30 | uncommitted | OVERDUE event: overruns are seen every minute after the planned end; hand-checked toy cases. |
| 2026-10-30 | uncommitted | Metrics moved to 23; planner time in REPLAN records. |
| 2026-10-30 | uncommitted | Trigger on the planner's objective ($\delta_f$) and periodic safety net ($\tau$, hybrid policy, WAKE event); hand-checked toy cases. |
| 2026-10-30 | uncommitted | Frozen horizon and anti-thrashing from Shiau et al. (2026) recorded as open points. |
| 2026-11-03 | uncommitted | Repair moves batches as one. |
| 2026-11-08 | uncommitted | C6 and C7 for breaks, forced postponement (reference to [04](04_workers.md) §3). |
| 2026-11-04 | uncommitted | Mean start deviation $\Delta S_{\mathrm{mean}}$ as a third trigger (`max_mean_shift`), max kept for the ablation; sources for deviation triggers; open: direction of the triggers. Tardiness-trigger examples in notebook `04_rescheduling`. |
