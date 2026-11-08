# Notation

Central list of all symbols. New symbols are added **here first**; a symbol is never assigned twice.
Introduced in: [01](01_basic-fjsp.md) = `01_basic-fjsp.md`.

## Sets and indices

| Symbol | Meaning | Code | Introduced |
|---|---|---|---|
| $\mathcal{K}$, $k$ | set of orders, order index | `Instance.orders`, `CompiledInstance.order_ids` | [01](01_basic-fjsp.md) |
| $O$, $o$ | set of all operations, operation index (global) | `CompiledInstance.op_keys` / `op_index` | [01](01_basic-fjsp.md) |
| $O_k \subseteq O$ | operations of order $k$ | `Order.operations` | [01](01_basic-fjsp.md) |
| $k(o)$ | order(s) that operation $o$ serves: one for order operations, all orders on the carrier(s) for carrier and run operations ([03](03_carriers.md)) | `CompiledInstance.op_orders` | [01](01_basic-fjsp.md) |
| $M$, $m$ | set of machines, machine index | `Instance.machines`, `CompiledInstance.machine_ids` | [01](01_basic-fjsp.md) |
| $M_o \subseteq M$ | eligible machines of operation $o$, $M_o \neq \emptyset$ | keys of `Operation.options` | [01](01_basic-fjsp.md) |
| $O^{\emptyset} \subseteq O$ | operations without a machine (manual steps, rest); $M_o = \emptyset$, fixed duration $p_o$ | `Operation.duration` | [04](04_workers.md) |
| $W$, $w$ | set of workers, worker index | `Instance.workers` | [04](04_workers.md) |
| $\mathcal{A}_o$, $\eta$ | worker shares of operation $o$ (whole, prefix, suffix), share index ($\sigma$ is taken by the scenarios) | `Operation.worker`, `CarrierStep.worker`, `setup_attended`, `removal_attended` | [04](04_workers.md) |
| $W_\eta \subseteq W$ | workers qualified for share $\eta$ (default all) | `WorkerShare.qualified` | [04](04_workers.md) |
| $P \subseteq O \times O$ | precedence pairs $(o, o')$: $o$ must finish before $o'$ starts; only $k(o) = k(o')$ | `Operation.predecessors` | [01](01_basic-fjsp.md) |
| $\Pi_k$ | parts of order $k$, each with a type | `Order.parts` | [03](03_carriers.md) |
| $\mathcal{B}$, $b$ | carriers (build plates with their parts) | `Instance.carriers` | [03](03_carriers.md) |
| $\Pi(b)$, $\mathcal{K}_b$, $\mathcal{B}_k$ | parts on carrier $b$; orders with parts on $b$; carriers holding parts of order $k$ | `Carrier.parts` | [03](03_carriers.md) |
| $\tau(b)$, $\tau(o)$, $\mathcal{B}_k^\tau$ | kind of carrier $b$ (type of its parts, e.g. blank: primary); part type carrier operation $o$ carries; carriers of kind $\tau$ holding parts of order $k$ | `carrier_kinds`, `Operation.carries` | [03](03_carriers.md) |
| $\operatorname{sc}(o)$ | scope of a route operation: order, a part type, or carrier | `Operation.scope` | [03](03_carriers.md) |
| $\mathcal{R}$, $G_R$ | runs (machine runs over several carriers); operations of run $R$ in sequence (setup, main, removal) | `Instance.runs`, `CompiledInstance.machine_groups` | [03](03_carriers.md) |
| $p_\pi$, $p_R$, $p^0$, $\lambda$, $\Pi(R)$ | time of part $\pi$ alone in a run step; duration of the main operation of run $R$; fixed part and share of the run-duration estimator; parts of all carriers of $R$ | `Part.times`, `RunEstimator` | [03](03_carriers.md) |
| $n_k$, $Q$, $Q_R$ | size of the carried part of order $k$ (number of counted parts, dental: telescopes); carrier capacity in size units; maximum carriers per run (generator) | `CarrierGeneratorParams` | [21](21_instance-generator.md) |
| $\rho_s$ | run mode of carrier step $s$: none, given (nesting), per carrier | `CarrierStep.runs` | [03](03_carriers.md) |
| $c_s$ | batch capacity of carrier step $s$ (carriers per machine run decided by the planner, p-batch) | `CarrierStep.batch_capacity` | [03](03_carriers.md) |
| $u_j$, $S^B_j$, $z_{j,m}$, $y_{o,j}$ | CP-SAT batch slot $j$: used, start, machine choice; operation $o$ in slot $j$ | [03](03_carriers.md) |
| $\operatorname{ex}_b(o)$ | operations executing carrier operation $o$ for carrier $b$ (its own operation or the run's), with $\operatorname{first}$, $\operatorname{last}$ | `operation_graph` | [03](03_carriers.md) |
| $P^*$ | precedence pairs of the compiled graph, crossing orders only through carrier and run operations | `CompiledInstance.predecessors` | [03](03_carriers.md) |

Note: $\mathcal{K}$ instead of the common $J$ ("jobs"), because "Job" denotes a machine run in the MES (see terminology in `CLAUDE.md`).

## Parameters

| Symbol | Domain | Meaning | Code | Introduced |
|---|---|---|---|---|
| $p_{o,m}$ | $\mathbb{Z}_{>0}$ | processing time of $o$ on $m \in M_o$, in `time_unit` | values of `Operation.options` | [01](01_basic-fjsp.md) |
| $p_o$ | $\mathbb{Z}_{>0}$ | duration of an operation without machine, $o \in O^{\emptyset}$ | `Operation.duration` | [04](04_workers.md) |
| $a^{\mathrm{pre}}_o$, $a^{\mathrm{suf}}_o$ | $\mathbb{Z}_{\ge 0}$, $a^{\mathrm{pre}}_o + a^{\mathrm{suf}}_o \le \min_m p_{o,m}$ | attended prefix and suffix of $o$ (0: none; not $r_o$, which would clash with releases); a whole share occupies the worker for all of $o$ | `WorkerShare.prefix`, `suffix`, `whole` | [04](04_workers.md) |
| $d_k$ | $\mathbb{Z}_{\ge 0}$, $d_k \ge r_k$ | due date of order $k$ (soft, optional) | `Order.due_date` | [06](06_due-dates.md) |
| $r_k$ | $\mathbb{Z}_{\ge 0}$ | release time of order $k$ | `Order.release`, `CompiledInstance.release` (per operation) | [01](01_basic-fjsp.md) |

## Calendar

Times of day $h^{\cdot}$ are minutes after midnight; $t$ is the model time in minutes. Only for instances with a
calendar ([04](04_workers.md)).

| Symbol | Domain | Meaning | Code | Introduced |
|---|---|---|---|---|
| $\omega$ | $[0, 7 \cdot 1440)$ | minute of the week (Monday 00:00 = 0) at $t = 0$; default 480 (Monday 08:00) | `Calendar.origin` | [04](04_workers.md) |
| $\operatorname{day}(t)$, $\operatorname{mod}(t)$ | | day index $\lfloor (\omega + t) / 1440 \rfloor$ (day 0 = Monday of the first week; weekday $\operatorname{day}(t) \bmod 7$) and minute of the day $(\omega + t) \bmod 1440$ | `calendar.day_index`, `minute_of_day` | [04](04_workers.md) |
| $\mathcal{D}^{\mathrm{w}}$ | $\subseteq \{0, \dots, 6\}$ | working weekdays; default Monday–Friday | `Calendar.working_days` | [04](04_workers.md) |
| $h^{\mathrm{S}}$, $h^{\mathrm{E}}$ | minutes of the day | shift start and regular shift end; default 08:00, 17:30 | `Calendar.shift_start`, `shift_end` | [04](04_workers.md) |
| $\bar O$ | $\mathbb{Z}_{\ge 0}$ | maximum overtime per worker and day; default 120 | `Calendar.max_overtime` | [04](04_workers.md) |
| $h^{\mathrm{B}-}$, $h^{\mathrm{B}+}$, $L^{\mathrm{B}}$ | minutes of the day, $\mathbb{Z}_{>0}$ | window for the start of the lunch break, its length; default 12:00, 13:00, 60 | `Calendar.break_earliest`, `break_latest`, `break_length` | [04](04_workers.md) |
| $h^{\mathrm{C}}$, $\Gamma$ | minute of the day; set of times | shipping cutoff (courier pickup) and the set of cutoffs $\{t \ge 0 : \operatorname{day}(t) \bmod 7 \in \mathcal{D}^{\mathrm{w}},\ \operatorname{mod}(t) = h^{\mathrm{C}}\}$; default 12:00 | `Calendar.cutoff`, `calendar.cutoffs` | [04](04_workers.md) |

## Decision variables

| Symbol | Domain | Meaning | Introduced |
|---|---|---|---|
| $x_{o,m}$ | $\{0,1\}$ | 1 iff operation $o$ is processed on machine $m \in M_o$ | [01](01_basic-fjsp.md) |
| $S_o$ | $\mathbb{Z}_{\ge 0}$ | start time of $o$ | [01](01_basic-fjsp.md) |
| $C_o$ | $\mathbb{Z}_{\ge 0}$ | completion time of $o$ | [01](01_basic-fjsp.md) |
| $C_{\max}$ | $\mathbb{Z}_{\ge 0}$ | makespan | [01](01_basic-fjsp.md) |
| $y_{\eta,w}$ | $\{0,1\}$ | 1 iff worker $w$ serves share $\eta$ | [04](04_workers.md) |
| $I_\eta = [\underline{I}_\eta, \overline{I}_\eta)$ | interval | worker time of share $\eta$ (whole, prefix or suffix of its operation) | [04](04_workers.md) |
| $b_{w,d}$ | $\mathbb{Z}_{\ge 0}$ | break start of worker $w$ on day $d$ (not the maximum late offset $b$ of [22](22_scenarios.md)) | [04](04_workers.md) |
| $\hat b_{w,d}$ | $\mathbb{Z}_{\ge 0}$ | realized break start, started by snapshot time $t$ (part of the snapshot) | [04](04_workers.md) |

## Derived quantities (solution methods)

| Symbol | Meaning | Introduced |
|---|---|---|
| $\underline{p}_o$ | $\min_{m \in M_o} p_{o,m}$, shortest processing time of $o$ | [11](11_dispatching-rules.md) |
| $\rho_o$ | ready time of $o$ during schedule generation | [11](11_dispatching-rules.md) |
| $f_m$ | time at which machine $m$ becomes free during schedule generation | [11](11_dispatching-rules.md) |
| $W_m$ | load of machine $m$: total processing time assigned to $m$ so far | [11](11_dispatching-rules.md) |
| $B_m$ | backlog of machine $m$: processing time assigned to $m$ but not yet scheduled | [11](11_dispatching-rules.md) |
| $w_k$ | remaining work of order $k$: $\sum \underline{p}_o$ over its unscheduled operations | [11](11_dispatching-rules.md) |
| $\ell_o$ | longest remaining path from $o$ (inclusive) within its order, measured with $\underline{p}$ | [11](11_dispatching-rules.md) |
| $m(o)$ | machine assigned to $o$ by the assignment rule | [11](11_dispatching-rules.md) |
| $V_w$ | worker load of $w$: total length of the shares booked for $w$ so far ($W$ is the worker set; $V$ in [L] means operations, not ours) | [11](11_dispatching-rules.md) |

## Correspondence to the sources

The sources use different symbols. Ours are kept because $J$ ("jobs") would clash with the MES term "Job", and $k$ is our order index. [DP] = Dauzère-Pérès et al. (2024, p. 410), [K] = Kasapidis et al. (2021, pp. 4046–4049), [L] = Lunardi et al. (2020, pp. 4–5).

| Ours | [DP] | [K] | [L] | Meaning |
|---|---|---|---|---|
| $\mathcal{K}$, $k$ | $J$, $j$ | $J$, $u$ | (jobs only implicit) | orders / jobs |
| $O$, $o$ | $O$, $i$ | $\Omega$, $i$ | $V$, $i$ | operations |
| $O_k$ | (route of $j$) | $O_u$ (incl. dummy ops) | — | operations of one order |
| $M$, $m$ | $R$, $k$ | $M$, $k$ | $\{1..m\}$, $k$ | machines |
| $M_o$ | $R_i$ | $M_i$ | $F(i)$ | eligible machines |
| $p_{o,m}$ | $p_{ki}$ | $p_{i,k}$ | $p_{ik}$ | processing time |
| $P$ | $pr(i)$, $fr(i)$ (linear) | $A$; $PJ_i$, $SJ_i$ | $A$ | precedence (DAG) within an order/job |
| $r_k$ | $r_j$ (Table 1, $\beta$ field) | — | $r_i$ (per operation) | release time |
| $x_{o,m}$ | $\alpha_{ik}$ | $Y_{i,k}$ | (assignment binaries) | assignment |
| $S_o$ | $t_i$ | — | $s_i$ | start time |
| $C_o$ | (none; $t_i + \sum_k p_{ki}\,\alpha_{ik}$) | $C_i$ | — | completion time |
| (none) | $\beta_{ii'}$, $H$ | $X_{i,j,k}$, $M$ | (sequencing binaries) | sequencing binary and big-M of the MILP; not needed in the CP model |
| $C_{\max}$ | $C_{\max}$ | $C_{\max}$ | $\max_i$ `endOf`$(o_i)$ | makespan |

## Simulation (DES)

| Symbol | Meaning | Introduced |
|---|---|---|
| $\bar m(o)$, $\bar S_o$ | machine and start of $o$ in the plan | [13](13_des.md) |
| $\hat S_o$, $\hat C_o$ | realized start and completion of $o$ in the simulation | [13](13_des.md) |
| $\hat p_o$ | realized processing time of $o$ | [13](13_des.md) |
| $\operatorname{prev}(o)$ | operation planned directly before $o$ on $\bar m(o)$ | [13](13_des.md) |
| $\tilde C_o$ | expected completion of an operation running at snapshot time $t$: $\max(\hat S_o + p_{o,\bar m(o)}, t + 1)$ | [13](13_des.md) |
| $\varepsilon_o$ | disturbance factor of $o$ (realized / planned processing time before rounding) | [22](22_scenarios.md) |
| $\sigma$ | standard deviation of $\ln \varepsilon_o$ | [22](22_scenarios.md) |
| $\Delta_o$ | start offset of $o$ in minutes (< 0 early, > 0 late) | [22](22_scenarios.md) |
| $q$, $a$, $b$ | probability of no start offset; maximum early and late offset | [22](22_scenarios.md) |
| $t$ | current time / rescheduling point | [05](05_rescheduling-frozen-part.md) |
| $\bar C_o$ | completion of $o$ in the current plan | [05](05_rescheduling-frozen-part.md) |
| $\bar S'_o$, $\bar C'_o$ | start and completion of $o$ in the repaired plan | [05](05_rescheduling-frozen-part.md) |
| $B(o)$ | blockers of $o$: predecessors and $\operatorname{prev}(o)$ | [05](05_rescheduling-frozen-part.md) |
| $E_q$ | known end of blocker $q$ at time $t$ (realized, expected or repaired) | [05](05_rescheduling-frozen-part.md) |
| $\beta_o$, $\beta'_o$ | old and new block of $o$ in the shift repair | [05](05_rescheduling-frozen-part.md) |
| $\bar S^A_o$, $\bar C^A_o$ | start and completion of $o$ in the anchor: the plan of the last complete rescheduling, at first the start plan | [05](05_rescheduling-frozen-part.md) |
| $\Delta C$, $\Delta S$, $\Delta S_{\mathrm{mean}}$ | deviation of the projected makespan, largest and mean start deviation (over the operations not started) of the repaired plan from the anchor | [05](05_rescheduling-frozen-part.md) |
| $\delta_C$, $\delta_S$, $\delta_{S,\mathrm{mean}}$ | thresholds for $\lvert \Delta C \rvert$, $\Delta S$ and $\Delta S_{\mathrm{mean}}$ that trigger a complete rescheduling | [05](05_rescheduling-frozen-part.md) |
| $\Delta f$, $\delta_f$ | deviation of the planner's objective $f$ of the repaired plan from the anchor; its threshold | [05](05_rescheduling-frozen-part.md) |
| $\tau$, $t_A$ | period of the safety net; time of the anchor (last complete rescheduling, 0 for the start plan) | [05](05_rescheduling-frozen-part.md) |
| $\kappa$, $\chi$ | change budget; number of changed machine assignments of a new plan | [05](05_rescheduling-frozen-part.md) |
| $\bar C^{\text{new}}_o$ | completion of $o$ in the plan proposed by a complete rescheduling | [05](05_rescheduling-frozen-part.md) |
| $m^0(o)$, $S^0_o$ | machine and start of $o$ in the start plan of a run | [23](23_metrics.md) |
| $\hat C_k$ | realized completion of order $k$: $\max_{o \in O_k} \hat C_o$ | [23](23_metrics.md) |
| $\bar F$ | mean flow time of the orders | [23](23_metrics.md) |
| $D_S$, $D_M$ | mean absolute start deviation; number of machine changes against the start plan | [23](23_metrics.md) |
| $N_R$, $N_C$, $N_A$ | numbers of repairs, complete reschedulings, accepted complete reschedulings in a run | [23](23_metrics.md) |
| $p^{\mathrm{avg}}_o$ | average processing time of $o$ over $M_o$ | [06](06_due-dates.md) |
| $\Lambda_k$ | longest path through order $k$ with weights $p^{\mathrm{avg}}_o$ (shortest lead time without waiting) | [06](06_due-dates.md) |
| $\theta_k$ | due-date tightness of order $k$ | [06](06_due-dates.md) |
| $C^{\mathrm{ref}}_k$ | completion of order $k$ in the reference plan used to set due dates | [06](06_due-dates.md) |
| $L_k$, $T_k$, $U_k$ | lateness $C_k - d_k$, tardiness $\max(L_k, 0)$, unit penalty $[C_k > d_k]$ of order $k$ | [06](06_due-dates.md) |
| $\mathcal{K}^d \subseteq \mathcal{K}$ | orders with a due date | [06](06_due-dates.md) |
| $s(f)$, $w_i$ | spread of objective $f$ (bound on the value difference of two solutions of one model); weight of level $i$ in a lexicographic objective | [06](06_due-dates.md) |
