# 06 Due dates

## 1. Prose description

Every dental order has a delivery date to the dentist; production has to finish the order before it. The model gets a **due date** $d_k$ per order. It is soft: finishing later is allowed but tardy (penalized by a due-date objective), not infeasible. Due dates are per order, not per operation, and without weights or priorities for now (express orders may follow).

The penalty functions follow Pinedo (2022, `5Y6PACF8`, ch. 2, PDF p. 32; printed page not checked): lateness $L_k = C_k - d_k$, tardiness $T_k = \max(L_k, 0)$, unit penalty $U_k = 1$ if $C_k > d_k$, else 0. Dauzère-Pérès et al. (2024, `ZSNHKWD6`, p. 414) use the same three for due-date criteria in the FJSP (definitions in their Table 1).

**Generating due dates.** The Brandimarte instances have no due dates, and company data is not available yet. Due dates are therefore set from the work content of an order with a tightness factor, as in Li et al. (2026, `6GGUPZNL`, p. 11):
$$D_i = A_i + \Big(\sum_{j} t_{i,j}\Big) \cdot DDT$$
with arrival $A_i$ (our release $r_k$), $t_{i,j}$ the processing time of operation $j$ averaged over its eligible machines (p. 13; the extracted text uses $t_{i,j}$ and $p_{i,j}$ for it **[uncertain]**), and the due date tightness $DDT$ drawn per job from $\{0.5, 1, 1.5\}$. The sum is the time the order needs if it never waits, which holds for chains (all jobs in Li et al. are chains).

**Own adaptation for precedence graphs.** For an order with parallel branches (split / join, the two-path reconvergence at QM) the branches can run at the same time on different machines; the sum then overestimates the shortest possible lead time. The work content is replaced by the **longest path** $\Lambda_k$ through the order's precedence graph, weighted with the average processing times. For chains $\Lambda_k$ equals the sum, so the rule coincides with Li et al.; for graphs it keeps the meaning of the tightness: $\mathrm{DDT}_k < 1$ makes the due date unreachable even for an order processed alone with average machines, $\mathrm{DDT}_k > 1$ leaves slack for waiting.

Example (toy instance, order B released at 2): b1 averages 3, then b2 (3) and b3 (3.5) in parallel, then b4 (2.5). $\Lambda_B = 3 + 3.5 + 2.5 = 9$ (the sum would be 12); with $\mathrm{DDT}_B = 1$: $d_B = 2 + 9 = 11$.

**Calibration with a reference plan (own, default for experiments).** $\Lambda_k$ ignores waiting for busy machines, so it does not scale with the load of an instance: with Li et al.'s set $\{0.5, 1, 1.5\}$ almost every mk01 order is late, and $\mathrm{DDT}_k = 0.5$ promises an order in half the time it needs even if it were processed alone, which is not meaningful for dental production. Due dates are therefore set relative to the flow time of each order in a **reference plan** (a feasible plan of the instance, here the best dispatching plan for the makespan): $C^{\mathrm{ref}}_k - r_k$ instead of $\Lambda_k$, with $\mathrm{DDT}_k \ge 1$. Then the reference plan is on time, every instance has a plan without tardiness, and tardiness in an experiment comes from disturbances or from weaker planning, the effects the thesis compares. $\mathrm{DDT}_k$ is the slack against a decent plan ($\mathrm{DDT}_k = 1.2$: 20 % more time than that plan needs). Company delivery dates would replace both bases.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

| Symbol | Meaning |
|---|---|
| $d_k$ | due date of order $k$ (soft), in `time_unit`, $d_k \ge r_k$ |
| $p^{\mathrm{avg}}_o$ | average processing time of $o$ over its eligible machines: $\frac{1}{\lvert M_o \rvert} \sum_{m \in M_o} p_{o,m}$ |
| $\Lambda_k$ | longest path through the precedence graph of order $k$ with weights $p^{\mathrm{avg}}_o$ |
| $\mathrm{DDT}_k$ | due-date tightness of order $k$ |
| $L_k$, $T_k$, $U_k$ | lateness, tardiness, unit penalty of order $k$ |

## 3. Constraints

None: the due date is soft. Validation of the instance: $d_k \ge r_k$ (a due date before the release is a data error).

Due-date generation:
$$\varphi_o = \max_{(q, o) \in P} \varphi_q + p^{\mathrm{avg}}_o \ \ (\max \emptyset = 0), \qquad \Lambda_k = \max_{o \in O_k} \varphi_o, \qquad d_k = r_k + \big\lfloor \mathrm{DDT}_k \Lambda_k + \tfrac{1}{2} \big\rfloor$$
($\varphi_o$: earliest finish of $o$ relative to the release if the order never waits; local to this formula.)
With a reference plan:
$$d_k = r_k + \big\lfloor \mathrm{DDT}_k (C^{\mathrm{ref}}_k - r_k) + \tfrac{1}{2} \big\rfloor, \qquad \mathrm{DDT}_k \ge 1 \ \Rightarrow\ C^{\mathrm{ref}}_k \le d_k$$
($\mathrm{DDT}_k (C^{\mathrm{ref}}_k - r_k) \ge C^{\mathrm{ref}}_k - r_k$ is an integer lower bound, so rounding cannot fall below it.)
$\mathrm{DDT}_k$ is drawn uniformly per order from a given set (Li et al.: $\{0.5, 1, 1.5\}$ with $\Lambda_k$; with a reference plan e.g. $\{1, 1.2, 1.5\}$); rounding half up keeps $d_k$ integer like all times.

## 4. Objective function

Two due-date objectives, alternatives to the makespan (the makespan stays the default). Let $\mathcal{K}^d \subseteq \mathcal{K}$ be the orders with a due date (orders without one are not penalized; an instance without any due date is rejected for these objectives) and $C_k = \max_{o \in O_k} C_o$:

(O1) Total tardiness:
$$\min \sum_{k \in \mathcal{K}^d} T_k, \qquad T_k = \max(C_k - d_k,\ 0)$$

(O2) Number of tardy orders:
$$\min \sum_{k \in \mathcal{K}^d} U_k, \qquad U_k = 1 \iff C_k > d_k$$

(O1') Total tardiness **with a work calendar** ([04](04_workers.md)): the due date is a shipping date, $d_k \in \Gamma$, and tardiness counts missed shipping cutoffs:
$$T_k = \left|\{\, c \in \Gamma : d_k \le c < C_k \,\}\right|$$
Completion by the cutoff of the due date is on time; by the next working day's cutoff 1 day late; a missed Friday cutoff shipped on Monday is 1 day late (no cutoff on weekends). (O2) is unchanged, since $T_k > 0 \iff C_k > d_k$ in both units. Instances without a calendar keep (O1) in minutes.

Both are regular (non-decreasing in the completion times), so an optimal schedule is semi-active, as for the makespan; the brute-force oracle of the tests relies on this. Maximum lateness $\max_k L_k$ follows as a metric ([23](23_metrics.md)).

(O3) Lexicographic combination: minimize $f_1$, among its minimizers $f_2$, and so on (weighted sum and lexicographic order as a priori approaches for the FJSP: Dauzère-Pérès et al., 2024, p. 416; primary / secondary criterion: Fowler & Mönch, 2022, p. 7). CP-SAT optimizes one linear objective, so the order is encoded as one weighted sum that is **exactly** lexicographic:
$$\min\ \theta_1 f_1 + \theta_2 f_2 + \dots + f_n, \qquad \theta_n = 1,\quad \theta_i = 1 + \sum_{j > i} \theta_j\, \operatorname{spr}(f_j)$$
(weights of objectives written $\theta$ as in Pinedo, 2022, `5Y6PACF8`, PDF p. 95, where $\theta_1 \gamma_1 + \theta_2 \gamma_2$ tends to $\mathrm{Lex}(\gamma_1, \gamma_2)$ as $\theta_2 \to 0$), where the spread $\operatorname{spr}(f)$ bounds the difference of the values of any two solutions of one CP-SAT model. Then one unit of $f_i$ outweighs every possible change of $f_{i+1}, \dots, f_n$. Spreads, with the static horizon $H$ of [12](12_cp-sat.md) §2:
- $\operatorname{spr}(C_{\max}) = H$. Static model: $C_{\max} \in [0, H]$. Model from a snapshot at $t$ with horizon $H_t = \max(r_{\max}, t, \max_o E_o) + \sum_{o \text{ free}} \max_m p_{o,m}$: if a free operation exists, every solution ends after $t$, so the spread is at most $H_t - t$; a running operation's expected end exceeds $t$ by at most its planned duration, which is not counted among the free ones, hence $H_t - t \le r_{\max} + \sum_o \max_m p_{o,m} = H$.
- $\operatorname{spr}(\sum T) = |\mathcal{K}^d| \cdot H$ (each $T_k$ changes at most as much as $C_k$); $\operatorname{spr}(\sum U) = |\mathcal{K}^d|$.
- With a calendar (O1'): $\operatorname{spr}(\sum T) = |\mathcal{K}^d| \cdot (\lfloor H / 1440 \rfloor + 1)$. $C_k$ varies within a window of length at most $H$ (argument above), and cutoffs are at least 1440 minutes apart, so such a window holds at most $\lfloor H / 1440 \rfloor + 1$ of them.

Example: total tardiness, then makespan: $\min\ (H + 1) \sum_k T_k + C_{\max}$. On mk01 with loose due dates ($\mathrm{DDT} \in \{1.5, 2, 2.5\}$) CP-SAT returns $\sum T = 0$ and $C_{\max} = 40$ (optimal, 0.2 s), where total tardiness alone stopped at $C_{\max} = 52$. The value reported by CP-SAT is the weighted sum; the single levels are evaluated separately. For more levels the weights grow multiplicatively (three levels (tardy orders, total tardiness, makespan) on mk10: top weight about $2 \cdot 10^8$, objective values up to about $4.5 \cdot 10^9$, still within the 64-bit integers of CP-SAT; the effect on search performance has not been measured).

**CP-SAT mapping** (`simulation.objectives`):
- $C_k$: `add_max_equality` over the ends of the operations of $k$ without successors (the others end earlier by C3).
- $T_k$: integer variable with `add_max_equality`$(T_k, \{C_k - d_k, 0\})$, exact.
- $T_k$ with a calendar (O1'): one Boolean $\lambda_{k,c}$ per cutoff $c \in \Gamma$ with $d_k \le c \le H$, reified in both directions ($C_k \le c$ if $\neg \lambda_{k,c}$, $C_k \ge c + 1$ if $\lambda_{k,c}$), $T_k = \sum_c \lambda_{k,c}$; exact for every solution (test `test_day_tardiness_cpsat_agrees`). About one Boolean per order and working day of the horizon.
- $U_k$: Boolean with $C_k \le d_k$ if $\neg U_k$ and $C_k \ge d_k + 1$ if $U_k$ (both reified directions). With only the first one, a non-optimal solution could carry $U_k = 1$ for an order that is on time, and the solver's objective value would differ from the evaluation; both directions make the value exact for every solution (tested on mk01 with a 0.5 s limit).

## 5. Implementation in code

- `simulation.model.instance.Order.due_date: NonNegativeInt | None` (None: no due date, e.g. Brandimarte); validation `due_date >= release` in `Instance.check_references` (negative test `due_date_before_release`). Schema version 0.3 (`schemas/instance-0.3.json`).
- `simulation.due_dates.lead_time_bound(order)` ($\Lambda_k$, topological order via `graphlib`) and `assign_due_dates(instance, tightness, seed)`: copy of the instance with $d_k$; $\mathrm{DDT}_k$ from its own random stream (`"due-{seed}"`), so that adding due dates changes nothing else of a generated instance. Brandimarte `.fjs` files stay unchanged; due dates are added in memory or stored as JSON instances.
- Carrier instances ([03](03_carriers.md)): in $\Lambda_k$ a carrier operation counts with the average of its step's machines plus setup and removal (the constant, not the run estimate); with a reference plan, entries of carriers and runs count for every order they serve.
- Generator: parameter `due_date_tightness` (default empty: no due dates) ([21](21_instance-generator.md)).
- With a work calendar: validation $d_k \in \Gamma$; `assign_due_dates` rounds the computed value **up** to the next cutoff (`calendar.next_cutoff`), with the same random draws as without a calendar; `TOTAL_TARDINESS` evaluates (O1') (`calendar.days_late`), its CP-SAT part and spread as in §4; `run_metrics` adds `tardy_days` and keeps `total_tardiness` in minutes as a metric (gradient within a day). Tests: `tests/test_day_tardiness.py` (boundary minutes 240 → 0, 241 → 1, 1680 → 1, 1681 → 2; weekend 1 day; CP-SAT optimum 2 on a chain ending at 1700, also lexicographic with makespan; spread 2; rounding; metric).
- `CompiledInstance.due_date`: tuple per order index (None: no due date).
- Objectives `TOTAL_TARDINESS`, `TARDY_ORDERS` in `simulation.objectives` (evaluation + CP-SAT expression + spread); usable everywhere an `Objective` is accepted: `solve`, `cpsat_planner`, `best_dispatch`.
- `lexicographic(f_1, ..., f_n)` builds (O3) from any objectives (name e.g. `total_tardiness>makespan`); `Objective.spread(ci)` and `static_horizon(ci)` ($H$).
- Dispatching rule EDD ([11](11_dispatching-rules.md)).
- Feasibility checker and DES: unchanged, since due dates are soft (Definition of Done: nothing to check, nothing to simulate).
- Tests (`tests/test_due_dates.py`): $\Lambda$ of a chain (toy A 9.5, mk01 J1 $4.5 + 3 + 3 + 4 + 1 + 5 = 20.5$) and of parallel branches (toy B 9); hand example with $\mathrm{DDT} = 1$: $d_A = 0 + 9.5 \to 10$, $d_B = 11$, $d_C = 4 + 5.5 \to 10$; reproducibility per seed; generator adds due dates only when asked.
- Tests (`tests/test_objectives.py`): hand values on the toy plan (order ends A 8, B 11, C 10): due dates 10/11/10 give $\sum T = 0$; due dates 5/7/7 ($\mathrm{DDT} = 0.5$) give $\sum T = 3 + 4 + 3 = 10$, $\sum U = 3$; only B with $d_B = 9$: $\sum T = 2$; CP-SAT optimum on the toy with $\mathrm{DDT} = 0.5$ equals a brute-force oracle over all semi-active schedules for both objectives; the CP-SAT value equals the evaluation also for time-limited mk01 solutions; rescheduling with `cpsat_planner(objective=lexicographic(TOTAL_TARDINESS, MAKESPAN))` runs feasibly; lexicographic optimum on the toy equals the brute-force minimum of the tuples $(\sum T, C_{\max})$ and $(\sum U, C_{\max})$, and the reported value is $(H + 1)\sum T + C_{\max}$; the three-level value orders five schedules exactly like the tuples; mk01 loose: $(0, 40)$.

**Results on mk01 with due dates from $\Lambda_k$** (first version, before the calibration; own computation, one run). Static CP-SAT plans (5 s, optimal):

| tightness | objective | $C_{\max}$ | $\sum T$ | tardy |
|---|---|---|---|---|
| $\{0.5, 1, 1.5\}$ | makespan | 40 | 107 | 7 |
| $\{0.5, 1, 1.5\}$ | total tardiness | 43 | 46 | 5 |
| $\{1.5, 2, 2.5\}$ | makespan | 40 | 16 | 2 |
| $\{1.5, 2, 2.5\}$ | total tardiness | 52 | 0 | 0 |

Under disturbances ($\sigma = 0.3$, $q = 0.5$, $a = b = 5$, 10 seeds), mean $\sum T$ with repair only vs. CP-SAT rescheduling ($\delta_C = 2$, $\delta_S = 10$) for the same objective: tight 186 → 135 (tardiness objective) vs. 248 → 185 (makespan objective); loose 41 → 19 vs. 86 → 39. With the tight set 9–10 of 10 orders are late in every policy.

**Results on mk01 with calibrated due dates** (notebook `04_rescheduling`; reference: best dispatching plan, makespan 42; own computation, one run). Static CP-SAT plans (5 s, optimal):

| $\mathrm{DDT}_k$ | objective | $C_{\max}$ | $\sum T$ | tardy |
|---|---|---|---|---|
| 1 | makespan | 40 | 77 | 5 |
| 1 | total tardiness, then makespan | 42 | 0 | 0 |
| $\{1, 1.2, 1.5\}$ | makespan | 40 | 53 | 4 |
| $\{1, 1.2, 1.5\}$ | total tardiness, then makespan | 40 | 0 | 0 |

Under disturbances (as above, 10 seeds), $\mathrm{DDT}_k \in \{1, 1.2, 1.5\}$: $\sum T$ with repair only 152 (makespan plan) / 74 (lexicographic plan); with CP-SAT rescheduling for the same objective 91 / 33, $L_{\max}$ 32 / 9, realized makespan 52 / 60. Rescheduling for tardiness first halves the total tardiness at the price of a longer makespan.

## 6. Assumptions and open points

- **Ties of the tardiness objectives (resolved by (O3), §4):** with reachable due dates many schedules have $\sum T = 0$; CP-SAT proves optimality and stops at the first one, regardless of makespan or flow time (loose mk01: makespan 52 instead of 40). CP-SAT optimizes one linear objective (calling `minimize` again replaces it, checked with OR-Tools 9.15); several criteria are combined a priori by a weighted sum or a lexicographic order, both used for the FJSP (Dauzère-Pérès et al., 2024, p. 416; primary / secondary criterion $\gamma_1/\gamma_2$: Fowler & Mönch, 2022, `H6SPCTKI`, p. 7). Exact lexicographic order in one solve: minimize $(H + 1)\sum_k T_k + C_{\max}$, since $C_{\max} \le H$ (horizon). Tried on loose mk01: $\sum T = 0$ and $C_{\max} = 40$, optimal in 0.2 s. Alternative: two solves, the second with $\sum T \le T^*$ and the first solution as hint (needs $T^*$ proven optimal, otherwise it is only the best found value).
- **Hard deadlines:** a constraint $C_k \le d_k$ instead of a penalty makes the model infeasible as soon as one order cannot be on time; proving infeasibility can take the whole time limit and returns no plan. A first run with hard deadlines and a fallback to the soft model gives the same plan as the lexicographic objective when all orders can be on time, at the cost of a second solve otherwise; the lexicographic objective covers both cases in one solve. Hard deadlines may still fit individual orders (e.g. express orders), with all others soft.
- **Trigger on the planner's objective:** implemented ($\delta_f$, [05](05_rescheduling-frozen-part.md) §3). For a lexicographic objective $\Delta f$ is measured in its weighted units; a threshold on the primary objective (e.g. $\sum T$) is easier to interpret.
- **Tightness calibration (implemented, §1):** due dates relative to a reference plan. Still open: the slack has to match the disturbance level; with $\mathrm{DDT}_k \le 1.5$ and the disturbances of the notebook ($\sigma = 0.3$, offsets up to 5 min) 6–7 of 10 mk01 orders are late in every policy. The reference plan depends on the dispatching rules (another reference, e.g. a CP-SAT plan, gives other due dates).
- The tightness distribution is taken from Li et al. (2026) without justification for dental production; to be replaced by company data (delivery dates, typical lead times) when available.
- $\Lambda_k$ ignores waiting and machine conflicts; with many orders even $\mathrm{DDT}_k = 1.5$ may be tight. The share of tardy orders depends on the load of the instance.
- Average processing time over eligible machines, not the fastest machine: a planner may beat $\Lambda_k$.
- No weights / priorities (express orders) yet.
- Due dates are fixed when an order is released; changed delivery dates during execution are not modeled.

## 7. Sources

- Lateness, tardiness, unit penalty: Pinedo (2022), PDF p. 32; Dauzère-Pérès et al. (2024), p. 414.
- Due date from work content and tightness factor: Li et al. (2026), p. 11.
- Own: longest path instead of the sum for orders with parallel branches; rounding half up; calibration with a reference plan.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-30 | uncommitted | Due date per order in the instance format (schema 0.3), validation, generation from the longest path with tightness factor, generator parameter. |
| 2026-10-30 | uncommitted | Objectives total tardiness and number of tardy orders (evaluation and CP-SAT), EDD rule, due dates in `CompiledInstance`. |
| 2026-10-30 | uncommitted | Results on mk01 (static and under disturbances); open points ties, trigger vs. objective, calibration. |
| 2026-10-30 | uncommitted | Open points: lexicographic objective (tried on mk01), hard deadlines, todo trigger on the planner's objective, calibration with a reference plan. |
| 2026-10-30 | uncommitted | (O3) lexicographic combination as exact weighted sum with spreads; `lexicographic()`; tests against brute force. |
| 2026-10-30 | uncommitted | Calibration: due dates relative to the flow times of a reference plan, $\mathrm{DDT}_k \ge 1$; results on mk01 with the lexicographic objective. |
| 2026-10-30 | uncommitted | Todo trigger on the planner's objective done (see 05). |
| 2026-11-09 | uncommitted | Symbols renamed (protocol 2026-11-09 (24)): tightness $\theta_k$ → $\mathrm{DDT}_k$ (as Li et al.'s DDT), level weights $w_i$ → $\theta_i$ (Pinedo, 2022), spread $s(f)$ → $\operatorname{spr}(f)$. |
| 2026-11-05 | uncommitted | With a work calendar ([04](04_workers.md)) a due date must be a shipping cutoff $d_k \in \Gamma$ (validation); rounding in the generation and tardiness in days follow. |
| 2026-11-05 | uncommitted | (O1') tardiness in missed shipping days: evaluation, CP-SAT (one Boolean per cutoff), spread, rounding of generated due dates up to cutoffs, metric `tardy_days`. |
| 2026-11-02 | uncommitted | Due dates for carrier instances (lead-time bound with carrier steps; reference plans with carrier and run entries). |
