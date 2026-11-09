# 03 Carriers, loads and runs

(File renamed from `03_loads.md` on 2026-11-06; carriers are the central concept.)

**Status:** implemented for both carrier kinds, build plates and blanks: instance format, compilation, feasibility checker; DES and dispatching; CP-SAT; run-duration estimator; rescheduling and due dates; runs per carrier; oven runs as planner-decided p-batches (C10). Generator with plates and blanks implemented ([21](21_instance-generator.md) §4a). Open: freezing at print file generation, polishing across orders (worker s-batch), the batch-step gap (§6).

## 1. Prose description

**Terminology** (user, 2026-11-02 and 2026-11-03; binding: [terminology.md](terminology.md)). A **carrier** is either a **build plate** with the secondary parts printed on it, or a **blank** with the primary parts milled from it, in both cases possibly from several orders. The parts are bound to it from the **forming** operation (print, milling of the blank) to the **separating** operation (sawing of the plate, separation from the blank) and stay bound across all operations in between: the persistent batch dependency of the thesis. A **load** keeps its meaning from `CLAUDE.md`: the units one machine run processes together, e.g. up to four carriers in one print. A **run** is that machine run. Carriers persist; loads exist only for one run.

**Data model (MES view, user 2026-11-02, chosen over explicit cross-references).**
- An order has **parts** with a type (secondary: printed on a build plate; primary: milled from a blank) and **one route**.
- **Carrier kinds** (G1, user 2026-11-03): a blank is a carrier too (primary parts of several orders, bound from milling to separation). The kind of a carrier is the type of its parts; all parts on one carrier share a type. Each carrier operation names the part type it carries (`carries`); with only one carrier kind in an order the name may be omitted.
- Every route operation has a **scope**: `order` (acts on all parts: fork and merge points), a part type (one operation for all parts of that type in the order, e.g. polishing as $s + \sum_i p_i$), or `carrier` (executed by the plate, not by the order).
- **Carriers** list their member parts; **runs** list the carriers of one machine run. Both are nesting output and given in the instance; steering nesting via priority classes is not modeled.
- Carrier operations take their durations from a step table (`carrier_steps`), not from the order.
- The carrier operations of an order form one chain **per carrier kind** from a forming to a separating operation. All orders on one carrier share the chain of its kind (same operation IDs and steps).

**One QM per carrier** (user, 2026-11-02). QM is a carrier operation. It waits for the carrier's previous operation and for the primary parts of every order on the carrier; the carrier is sawn only after its QM.

**Runs.** A run executes one carrier step for all its carriers at once: setup → main operation → removal on **one machine** (C8), and the machine is **blocked** from the start of the setup to the end of the removal, also when the removal has to wait (C9). Setup and removal are their own operations with a default time per step; the main operation runs unattended. Print runs are given by nesting; mill runs are one run per carrier (blank or plate); oven runs are decided by the planner as p-batches of up to $c_s$ carriers (C10, since 2026-11-03; §5).

**Derived synchronization.** One compiler rule replaces all explicit links between orders and carriers: a carrier operation of an order is executed by the corresponding operation of every carrier that holds parts of the order (for a run step: by the carrier's run), and the order's edges into and out of it are mapped to those operations. The four synchronization rules of the specification are instances of this rule:

| Rule | Derived edge (toy instance, `tests/test_carriers.py`) |
|---|---|
| Sync in: every order on the plate has finished its operations before forming | `design` of A and B → setup of R1 (run of L1) |
| QM per carrier waits for the primary parts of its orders | `mill` of A and B → QM of L1; only `mill` of A → QM of L2 (C has no primary part) |
| Carrier continues after its QM | QM of L1 → saw of L1 |
| Sync out: an order continues after all its carriers are separated | saw of L1 and saw of L2 → `finish` of A |

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

| Symbol | Meaning |
|---|---|
| $\Pi_k$ | parts of order $k$, each with a type |
| $\mathcal{B}$, $b$ | carriers |
| $\Pi(b)$, $\mathcal{K}_b$, $\mathcal{B}_k$ | parts on carrier $b$; orders with parts on $b$; carriers holding parts of order $k$ |
| $\tau(b)$, $\tau(o)$, $\mathcal{B}_k^\tau$ | kind of carrier $b$ (type of its parts); part type a carrier operation $o$ carries; carriers of kind $\tau$ holding parts of order $k$ |
| $\operatorname{sc}(o)$ | scope of a route operation: order, a part type, or carrier |
| $\mathcal{R}$, $G_R$ | runs; operations of run $R$ in sequence (setup, main, removal) |
| $\rho_s$ | run mode of carrier step $s$: none (one operation per carrier), given (runs from nesting), per carrier (every carrier is its own run) |
| $\operatorname{ex}_b(o)$ | operations executing carrier operation $o$ for carrier $b$: $(b, o)$, or $G_R$ if $b$ is in run $R$ of the step of $o$; $\operatorname{first}$ / $\operatorname{last}$ of it |
| $P^*$ | precedence pairs of the compiled graph (crossing orders only through carrier and run operations) |

The compiled operation set $O$ contains the order operations with $\operatorname{sc}(o) \ne$ carrier, one operation $(b, o)$ per carrier and carrier operation outside runs, and the operations of every run. $k(o)$ becomes a set of orders (the orders an operation serves).

## 3. Constraints

Compiled precedence: for every route edge $(q, o) \in P_k$ of order $k$,
$$
\begin{aligned}
&(k, q) \to (k, o) && \text{both not carrier operations}\\
&\operatorname{last}(\operatorname{ex}_b(q)) \to (k, o) \quad \forall b \in \mathcal{B}_k^{\tau(q)} && q \text{ carrier, } o \text{ not (sync out)}\\
&(k, q) \to \operatorname{first}(\operatorname{ex}_b(o)) \quad \forall b \in \mathcal{B}_k^{\tau(o)} && o \text{ carrier, } q \text{ not (sync in, primary parts at QM)}\\
&\operatorname{last}(\operatorname{ex}_b(q)) \to \operatorname{first}(\operatorname{ex}_b(o)) \quad \forall b \in \mathcal{B}_k^{\tau(o)} && \text{both carrier operations, } \tau(q) = \tau(o) \text{: same carrier}\\
&\operatorname{last}(\operatorname{ex}_{b'}(q)) \to \operatorname{first}(\operatorname{ex}_b(o)) \quad \forall b' \in \mathcal{B}_k^{\tau(q)},\ b \in \mathcal{B}_k^{\tau(o)} && \text{both carrier operations, } \tau(q) \ne \tau(o)
\end{aligned}
$$
With one carrier kind, $\mathcal{B}_k^\tau = \mathcal{B}_k$ and the rules are the previous ones. Dental route (G2): blank chain (mill, separation) → polishing of the primary parts (order operation, scope primary) → QM of the plate, so a plate's QM waits for the polished primary parts of its own orders only; the blank couples the orders on it through its run, not through the QM.
plus the chain inside each run. (C3) then reads $S_{o'} \ge C_o$ for all $(o, o') \in P^*$; C1, C2, C4, C5 apply unchanged to all compiled operations (release of a carrier or run operation: the latest release of its orders).

**Runs per carrier (G3/G4, user 2026-11-03).** $\mathcal{R} = \mathcal{R}^{\text{given}} \cup \{R_{b,s} : \rho_s = \text{per carrier},\ b \text{ passes } s\}$: a step with $\rho_s$ = per carrier (milling all parts of one carrier, milling one blank) gives every carrier $b$ its own run $R_{b,s}$ with load $\Pi(R_{b,s}) = \Pi(b)$; no nesting input is needed, the carrier is the load. Its main operation takes the estimate over $\Pi(b)$ (e.g. $p^0 = 0$, $\lambda = 1$: the sum of the part times, dental: proportional to the telescopes), otherwise the constant per machine. C8 and C9 apply to these runs unchanged. Setup, removal and estimator require $\rho_s \ne$ none (before, they were silently ignored on steps without given runs); given runs require $\rho_s$ = given, a batch step requires $\rho_s$ = none.

(C8) One machine per run: setup, main operation and removal of a run share their machine.
$$x_{o,m} = x_{o',m} \qquad \forall R \in \mathcal{R},\ o, o' \in G_R,\ m \in M$$

(C9) Blocking: a run occupies its machine from the start of its first to the end of its last operation; no other operation overlaps this span on that machine (it replaces the single intervals of $G_R$ in C5).
$$[S_{\operatorname{first}(G_R)}, C_{\operatorname{last}(G_R)}) \cap [S_{o}, C_{o}) = \emptyset \qquad \forall o \notin G_R \text{ on the same machine}$$

**Duration of a run (step 4).** The printer has one laser and an additional arm: parts are not processed fully in parallel, but a print is faster than printing them one after another. The duration of a print run depends on its whole load (all parts on all its carriers) and lies between the p-batch and the s-batch extremes:
$$\max_{\pi \in \Pi(R)} p_\pi \;\le\; p_R \;\le\; \sum_{\pi \in \Pi(R)} p_\pi$$
with $p_\pi$ the time of part $\pi$ printed alone. The main operation of run $R$ takes, in this order: the duration reported by nesting for its layout (most accurate); otherwise the estimate
$$p_R = \min\Big(\sum_\pi p_\pi,\ \max\big(\max_\pi p_\pi,\ p^0 + \big\lfloor \lambda \sum_\pi p_\pi + \tfrac12 \big\rfloor\big)\Big), \qquad p^0 \ge 0,\ \lambda \in [0, 1]$$
(a fixed part plus a load-dependent part, clamped to the two bounds); otherwise the constant per machine of the step. **The form of the estimator and its parameters are assumptions** to be validated with Fidentis data; the estimate is the same on every eligible printer (identical printers assumed). Oven runs are true p-batches: the program fixes the duration, independent of the number of carriers (constant per machine).

**Batches decided by the planner (oven, user 2026-11-03).** An oven run holds up to 3 carriers and processes them in parallel (p-batch): all start and end together, and the oven program fixes the duration, independent of the number of carriers. Unlike print runs, which nesting gives, the grouping into oven runs is a planner decision. Decisions: the program duration does not deviate in the simulation (only the start can be late); loading and unloading are inside the program time (no own operations); any carriers may share an oven run (one program); the dispatching rule starts an oven run with the carriers that are ready (greedy, step 2).

(C10) Batches: operations of a batch step $s$ with capacity $c_s$ may share a machine only as one machine run: same machine, same start (and end, since the duration is fixed), at most $c_s$ operations; otherwise C5 applies.
$$[S_o, C_o) \cap [S_{o'}, C_{o'}) \neq \emptyset \ \Rightarrow\ S_o = S_{o'},\ C_o = C_{o'} \qquad \forall o, o' \text{ of step } s \text{ on the same machine}, \qquad \big\lvert\{o : S_o = S,\ \text{machine } m\}\big\rvert \le c_s$$

**Acyclicity.** Within one order the route is acyclic (validated). Across orders, every compiled edge either stays in one order's route or moves forward along the common carrier chain, so the graph is acyclic as long as runs group the same chain position on all their carriers. A run that groups a step at different positions (e.g. oven before QM on one carrier, QM before oven on another, both grouped) creates a cycle; instance validation checks the compiled graph for cycles (test `m_cycle_through_runs`).

## 4. Objective function

Not affected. Order-based objectives use the order completions $C_k = \max_{o: k \in k(o)} C_o$ (in code: `CompiledInstance.op_orders`).

## 5. Implementation in code

- **Instance format 0.4** (`simulation.model.instance`, `schemas/instance-0.4.json`): `Order.parts` (`Part(id, type)`), `Operation.scope` (default `order`), `Operation.role` (`form` / `separate`, carrier operations only), `Operation.options` optional (none for carrier operations); `Instance.carrier_steps` (`CarrierStep(options, setup, removal)`), `Instance.carriers` (`Carrier(id, parts)` with parts as `(order_id, part_id)`), `Instance.runs` (`Run(id, step, carriers)`).
- **Validation**, one negative test each (`tests/test_carriers.py`): duplicate part IDs; unknown scope; carrier operation with options; unknown carrier step; options missing; role outside carrier operations; carrier operations not one chain from `form` to `separate`; unknown machine in a carrier step; IDs shared by orders, carriers, runs; unknown part; part on two carriers; carrier operations without a carried part and vice versa; different carrier routes on one carrier; run with unknown step or carrier, with a carrier not passing its step, a carrier in two runs of one step, a carrier without run for a run step; cycle in the compiled graph.
- **Compilation**: `operation_graph(instance)` (the derivation rule) and `compile_instance`. Owners in `op_keys` are orders, carriers and runs; `op_order` was replaced by `op_orders` (orders served); new `machine_groups` (run operations). Users of the order index adapted: objectives (order completion), dispatching (MWKR uses the largest remaining work of the orders served, EDD the earliest due date), visualization.
- **Checker** (`simulation.check.feasibility`): `run_on_several_machines` (C8), `machine_overlaps` with the blocked span of each run (C9; a pair involving a span is reported as C9).
- **Schedule format**: unchanged; `Assignment.order_id` holds the owner (order, carrier or run ID).
- **Order completion** $C_k$ (objectives, metrics): latest end over all operations serving $k$, incl. carrier and run operations (`op_orders`); metrics count flow times per order, not per owner.
- **DES** ([13](13_des.md)): no change in the event logic. Joint execution is implicit (one operation per carrier and run). C9 holds in execution because the DES keeps the planned order per machine (no overtaking): after the main operation of a run the next operation on its machine is the run's removal, so nothing else starts there while the removal waits. Scenarios cover every compiled operation ([22](22_scenarios.md)).
- **Dispatching** ([11](11_dispatching-rules.md)): a run is dispatched as one unit. Its first operation stands for the run with the run's total duration per machine; when chosen, setup, main operation and removal are placed back to back on one machine (C8, C9 by construction).
- **CP-SAT** ([12](12_cp-sat.md)): C8 as equality of the machine choices, $x_{o,m} = x_{\operatorname{first}(G_R),m}$ for every operation of the run; C9 by one optional interval per run and machine from $S_{\operatorname{first}(G_R)}$ to $C_{\operatorname{last}(G_R)}$ (variable size, presence $x_{\operatorname{first}(G_R),m}$) that replaces the intervals of the run's operations in `add_no_overlap`. Frozen run operations enter only through the span (their constant start or end), so a partly started run is continued on its machine.
- **Batches, step 1** (2026-11-03): `CarrierStep.batch_capacity` ($c_s \ge 2$; no setup, removal or estimator; no given runs for that step); `CompiledInstance.batch_capacity` per operation (1 for all others); checker: operations of a batch step with identical machine, start and end form one interval (C5 between machine runs), more than $c_s$ in one run is C10. Tests (`tests/test_batches.py`): joint oven run of L1 and L2 on the mini instance feasible; staggered overlap is C5; without batching a joint run is C5; three carriers in a run of capacity 2 is C10; three negative tests.
- **Batches, step 2** (2026-11-03): a **batch** of a plan is the set of not-started operations of a batch step on one machine with the same planned start (`simulation.sim.des.planned_batches`).
  - DES: a batch starts jointly when all its operations are released and ready; the largest late start offset of its operations delays the whole batch; the program duration does not deviate (scenario factors ignored for batch steps).
  - Dispatching (greedy, user decision): when an operation of a batch step is chosen at $t$ on $m$, the operations of a batch step ready by $t$ that may use $m$ with the same duration join, in the order of the sequencing rule, up to $c_s$; no waiting to fill the oven.
  - Repair: a batch moves as one: within a batch nobody waits for a fellow member, the batch starts at the latest start any member needs ([05](05_rescheduling-frozen-part.md)).
  - Tests (`tests/test_batches.py`): with one print run for both carriers, greedy batching gives the joint oven run [12,15) by hand (finish B 17, A 18, C 19); every rule combination feasible and zero-disturbance; a late worker (+2 on one carrier) delays the joint start to 14; a factor 2 on the oven does not change its duration; a longer print (6 instead of 4) moves the batch to [14,17) by repair; disturbed execution with repair keeps C10 and joint starts (5 seeds).
- **Batches, step 3: CP-SAT** ([12](12_cp-sat.md)). Batch slots per family $F$ (operations with the same machines, durations and capacity $c$), one slot per operation at most:
  $$\sum_{m} g_{j,m} = u_j, \qquad \sum_{j \le i(o)} y_{o,j} = 1, \qquad y_{o,j} \Rightarrow S_o = S^{\mathrm{slot}}_j \wedge x_{o,m} = g_{j,m}\ \forall m, \qquad \sum_{o \in F} y_{o,j} \le c\, u_j, \qquad u_j \ge u_{j+1}$$
  A used slot occupies its machine once: optional interval $[S^{\mathrm{slot}}_j, S^{\mathrm{slot}}_j + p_m)$ with presence $g_{j,m}$ in `add_no_overlap`; the operations' own intervals are left out. Symmetry breaking: slots are used from the front, and the $i$-th operation of a family only uses slots $j \le i$. Frozen operations of a running batch take a slot with their constant start, so rescheduling from a snapshot with a running batch works. Tests: three carriers, three printers (5 min), one oven (10 min), one saw (1 min): optimum 36 without batching (ovens one after another, last saw at 36), 18 with capacity 3 (one oven run [5,15), three saws): both proven by CP-SAT and by hand; the batched plan replays unchanged (zero-disturbance); on the mini instance batching is optional and the optimum stays 20; CP-SAT from a snapshot with the joint oven run running finds a feasible optimum.
- **Batches, step 4**: rescheduling with the rule planner and CP-SAT (thresholds and safety net, 4 seeds) keeps C10 and all other constraints; generator parameter `batch_capacity` (step → capacity, not the run step; example file: oven 3); Gantt charts draw one bar per batch labeled with its carriers. Notebook `05_carriers`: with oven runs of up to 3 carriers the makespan of the dental example drops from about 1850 to 978 (6 oven runs instead of 16); CP-SAT groups carriers from different print runs, the greedy rule only those ready together.
- **Dental example with blanks** (generator [21](21_instance-generator.md) §4a, notebook `05_carriers`, 2026-11-03): 40 orders, 19 plates in 5 print runs, 11 blanks of up to 16 primary parts; blank and carrier milling share 3 mills, separation and polishing a bench of 2. The mills become a second bottleneck next to the oven (blank milling first, carrier milling from about 780); makespan 1138 for the best rule, not improved by CP-SAT in 60 s (293 operations). Placeholder durations and blank capacity.
- **Carrier kinds** (`Operation.carries`, schema 0.5): `carrier_kinds` (kind = part type, uniform per carrier), `carrier_chains` (one chain per kind), `chain_for` (unnamed chain = the order's only kind); `operation_graph` maps a carrier predecessor to the same carrier when the kinds agree, otherwise to all carriers of the predecessor's kind holding the order's parts. Checker, DES, rules and CP-SAT unchanged. Tests (`tests/test_carrier_kinds.py`): blank K1 with the primary parts of A and B (mill per blank: setup 1, main 2 + 2, removal 1), separation and polishing on a bench W, plates L1, L2: derived edges (blank waits for both designs; polishing of A waits only for K1; QM of L1 only for A's polishing), optimum 13 by hand and proven by CP-SAT, all rule combinations feasible and zero-disturbance, C3 for a QM before the polishing, 7 negative tests.
- **Runs per carrier** (`CarrierStep.runs`, schema 0.5): `operation_graph` creates the run of carrier $b$ for operation $o$ as $(b, o\text{/setup})$, $(b, o)$, $(b, o\text{/removal})$ (the carrier owns runs of several steps, hence the prefix), as one machine group; `_estimate` over the carrier's parts. Checker, DES, rules and CP-SAT work on machine groups and needed no change. Tests (`tests/test_carrier_runs.py`): mini instance A, B on L1, L2, mill per carrier (setup 1, main 2 and 3 from part times, removal 1): optimum 12 by hand (lower bound: mill free at 3, 9 minutes of work) and proven by CP-SAT; every rule combination feasible, runs back to back, zero-disturbance; C9 for a delayed removal; one negative test per new validation rule.
- **Run duration** (`simulation.model.instance`): `estimate_run_duration(part_times, fixed, share)` and `run_duration(instance, run)` (nesting duration, else estimate, else `None` for the constant). The only place a run's duration is set is the compilation (`operation_graph`), so the DES, the rules, CP-SAT and later the GA all use the same value. Format: `Part.times` (step → time alone), `CarrierStep.estimator` (`RunEstimator(fixed, share)`), `Run.duration` (nesting). Validation: part times only for carrier steps; with an estimator every part of a run needs its time (unless the run has a nesting duration); $0 \le \lambda \le 1$.
- **Rescheduling** ([05](05_rescheduling-frozen-part.md)): the frozen part holds started operations as before; a partly started run (e.g. setup done, print running) is continued on its machine, back to back, by dispatching (`dispatch` from a snapshot) and by CP-SAT (span interval with the frozen start). Repair keeps machines and the order per machine, so a run stays contiguous. Carrier composition and runs are given and never changed by a planner.
- **Step 5 tests**: dispatching from the snapshot at $t = 5$ continues R1 with its removal on P at 9; rescheduling with the rule planner and with CP-SAT ($\delta_C = 0$, safety net every 5 minutes, 4 seeds with durations and start offsets) keeps C1, C3–C9; due dates for carrier instances ([06](06_due-dates.md)): lead-time bound 14.5 by hand, from the hand plan 22 / 16 / 23.
- **Step 4 tests**: estimator by hand (inside the bounds, rounding half up, clamped to $\max$ and to $\sum$); mini instance with part times A/s1 2, B/s 2, A/s2 2, C/s 3 and $p^0 = 1$, $\lambda = 0.5$: R1 $1 + 2 = 3$, R2 $1 + 2.5 \to 4$ on both printers; a nesting duration overrides the estimate; rules, CP-SAT and the DES see the estimated durations; three negative tests.
- **Step 3 tests**: optimum of the mini instance 20 (proven by CP-SAT; lower bound by hand: the first run's carrier reaches the single oven at 10 at the earliest, the second carrier's oven ends at $\ge 16$, its saw at $\ge 18$, and both of its orders finish after it one after the other: $\ge 20$); zero-disturbance: the CP-SAT plan replays unchanged with makespan 20; with one printer and R1's removal pending at $t = 10$ (worker 2 minutes late), the rescheduled plan keeps R2's setup after R1's removal (without the span the solver places it in the gap, C9 violated: checked by a mutation run); a partly started run (setup done, print running at $t = 5$) is continued on its printer.
- **Step 2 tests**: SPT + ECT reproduces the hand-computed plan exactly; every rule combination (15) is feasible incl. C8, C9 and replays unchanged (zero-disturbance); the hand plan replays unchanged with and without a neutral scenario; blocking: R1's removal starts 2 minutes late ([11,12) instead of [9,10)), R2's setup waits until 12 and L1's oven starts at 12; disturbed execution with repair (5 seeds, durations and start offsets) keeps C1, C3–C9; order completions and flow times on the mini instance (A 22, B 16, C 23).
- **Mini instance** `data/instances/toy-carriers.json`, hand-computed plan with makespan 23 (comment in the test): A split over L1 and L2; R2 waits for the printer; QM of L1 waits for B's milling; A's finish waits for both saws. Tests for C8, C9 (removal one minute late, the next setup placed in the gap: only the span overlaps) and the cross-order waiting (C3).

## 6. Assumptions and open points

- Load composition (carriers) and print runs are given (nesting) and never changed by a planner. Frozen boundary: after print file generation the run's printer (and time?) is fixed. Not implemented yet: how print file generation enters the model is open (an operation in the route, an event, or a lead time before the setup); until then a run is frozen only when its first operation has started, like every other operation.
- Setup and removal: one default time per carrier step, same on all machines of the step; per machine type later. They will need a worker (04); until then nothing delays a removal except the plan itself.
- Print duration: estimator $p^0 + \lambda \sum_\pi p_\pi$ clamped to $[\max_\pi p_\pi, \sum_\pi p_\pi]$; form and parameters are assumptions to be validated with Fidentis data; same value on every printer (identical printers). To swap the form, replace `estimate_run_duration`. Schema 0.4 was regenerated in place for these fields (not committed before).
- **Mill as a shared machine (user 2026-11-03, not implemented).** Facts: (1) a blank holds primary parts of **several orders**; (2) every carrier is milled (secondary parts) **after the oven and before QM**, one carrier at a time; (3) changeovers on the mill are contained in the separate setup and removal operations; (4) the duration of milling a carrier depends on the number of telescopes on it; (5) every mill can take carriers. Rework after QM also uses the mill (see QM rework loops). Milling is serial (s-batch), not a p-batch, so the batch-step todo below is not triggered. Gaps in the model:
  - **G1 two carrier kinds (done, see §1 and §5):** a blank is structurally a carrier (parts of several orders, bound from milling to separation), but today an order has one carrier chain and primary parts are never on a carrier.
  - **G2 synchronization across kinds (done, see §3):** QM of a plate waits for the primary parts of its orders being ready, i.e. separated from their blank (user: after separation the parts are independent); today `operation_graph` maps a carrier predecessor to the same carrier, and QM waits for the per-order `mill`.
  - **G3 runs without nesting (done, see §3 and §5):** milling a carrier is a run whose load is exactly that carrier (all its parts in one go, user), and milling a blank is a run of one blank; no nesting input is needed, the run follows from the carrier. Today setup and removal exist only for given runs, and on a carrier step without given runs they are silently ignored (not validated).
  - **G4 duration per carrier (done with G3):** milling time from the telescopes on the carrier; the run estimator with $p^0 = 0$, $\lambda = 1$ gives the sum of the part times, but only for runs.
  - Answers (user 2026-11-03): separation from the blank is its own step, done by a worker; one blank per mill run; the blank composition is decided by a worker (who should decide it is open); the factory route is not complete yet. Further answers: separation happens **per blank**; before QM the primary parts are **polished** by a worker (s-batch, no machine); separation and polishing get a stand-in machine ("bench") until workers (04); the blank composition is **given** in the instance (like the print nesting), whether a planner composes it later stays open; the route is completed gradually, the model is generalized rather than fitted to the Fidentis route. Polishing is **often across orders** (user): a worker s-batch over parts of several orders, a planner decision; not modeled yet (so far out of scope, see below; to revisit with workers 04). Open: capacity of a blank.
- **From the target data model** ([32](32_target-data-model.md), 2026-11-04): plate sets as a reusable resource (a print run uses one set; all its plates are ground before reuse); interface to nesting by remaining capacities and free printer gaps instead of estimated print durations; operations per part with rework; s-batches across orders. Todos, not modeled.
- **Todo (user 2026-11-03: later): batches only within one step.** The checker groups a batch by machine and time, the greedy rule and CP-SAT by machine options, duration and capacity; operations of two different batch steps (e.g. two oven programs) on one machine at the same time are accepted as one run. Fix: step per operation in `CompiledInstance`, grouping by step in checker, rule and CP-SAT families, negative test. No effect on the current instances (one batch step per machine).
- Oven runs: planner decision (p-batch, capacity 3 carriers, fixed program duration). Steps 1–4 done (format, checker; DES, greedy dispatching, repair; CP-SAT batch slots; rescheduling, generator parameter `batch_capacity`, notebook `05_carriers`).
- Primary parts used by several carriers' QMs: "reached QM" means the primary lane is finished; several QMs may use the same primary part one after another (no exclusive resource). To confirm.
- Walking time is not included in the Fidentis durations: optional overhead per step with the workers step (04).
- Batching across orders for worker operations (e.g. polishing several orders in one go) is out of scope.
- Instance generator with carriers: [21](21_instance-generator.md) §4a (nesting emulated in due-date order, priority classes not modeled).
- Assignment rules (least load, ECT) see only the duration of the run's first operation (setup), not the whole run; on the mini instance ECT therefore puts R2 on the busy printer P (makespan 23) where least load uses P2 (makespan 20). To revisit with the print-duration estimator (step 4).
- Disturbances apply to every compiled operation with the same distribution, incl. setup, removal and the oven, although an oven program has a fixed duration. To decide with the oven step.

## 7. Sources

- Batching machine (several jobs at once, upper limit on the batch size, batch time = longest job; example: ovens) and serial batching (batch time = sum of the job times): Potts & Kovalyov (2000, `26Z9YF55`, pp. 229 and 238; checked 2026-11-03; printed pages derived from the page range **[uncertain]**). Batches with the longest processing time and compatibility groups: Fowler & Mönch (2022, `H6SPCTKI`).
- Setup times: Allahverdi et al. (2008) **[uncertain: not found in the library so far]**.
- Load as its own operation in the graph: dedicated batch nodes (Dauzère-Pérès et al., 2024, §5.3, p. 418); ganging of orders into one job (Lunardi et al., 2020, p. 1).
- Own modeling: carriers with persistent binding, scopes and the derivation rule, QM per carrier, runs with a blocked span, the acyclicity argument.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-19 | — | Draft with options, assessment and open questions. |
| 2026-11-02 | — | Decisions from the load spec and the user's answers: MES data model with parts and derived synchronization, QM per plate, print runs given, oven batching later. |
| 2026-11-02 | uncommitted | Step 1: terminology carrier / load / run; instance format 0.4; derivation rule and compilation; checker C8 (one machine per run) and C9 (blocked span); mini instance and tests. |
| 2026-11-02 | uncommitted | Step 2: order completion over served operations; scenarios over compiled operations; dispatching of runs as one unit; DES unchanged (C9 through no overtaking); tests. |
| 2026-11-02 | uncommitted | Step 3: CP-SAT with C8 (equal machine choices) and C9 (span interval per run); optimum 20 by hand; zero-disturbance; blocking and partly started runs from a snapshot. |
| 2026-11-02 | uncommitted | Step 4: run duration from nesting, else estimator $p^0 + \lambda \sum p_\pi$ clamped to $[\max, \sum]$, else constant; set once in the compilation; tests. |
| 2026-11-02 | uncommitted | Step 5: dispatching continues partly started runs; rescheduling with rules and CP-SAT on carriers; due dates for carrier instances; open: generator, print file generation. |
| 2026-11-02 | uncommitted | Generator with carriers (see 21 §4a). |
| 2026-11-03 | uncommitted | Oven batches step 1: decisions (fixed duration, loading inside, greedy rule, any carriers), C10, format and checker; sources checked. |
| 2026-11-03 | uncommitted | Oven batches step 2: DES joint start and fixed duration, greedy batching in dispatching, repair moves batches as one; tests. |
| 2026-11-03 | uncommitted | Oven batches step 3: CP-SAT batch slots (also from snapshots); hand optimum 36 vs. 18. |
| 2026-11-03 | uncommitted | Oven batches step 4: rescheduling tests, generator parameter, one Gantt bar per batch, notebook 05 (makespan 1850 → 978). |
| 2026-11-03 | uncommitted | Runs per carrier (`CarrierStep.runs`: none / given / per_carrier, schema 0.5); setup, removal, estimator validated against the run mode. |
| 2026-11-03 | uncommitted | Carrier kinds (`Operation.carries`): one chain per part type, blanks as carriers, synchronization across kinds. |
| 2026-11-03 | uncommitted | Dental example with blanks, carrier milling, separation and polishing (notebook 05 re-run). |
| 2026-11-06 | uncommitted | Renamed from `03_loads.md` to `03_carriers.md` (links in `math/`, code comments, tests, notebook 05, `CLAUDE.md` updated); intro and status cover both carrier kinds (plates, blanks) and oven batching. |
| 2026-11-09 | uncommitted | Symbols renamed (protocol 2026-11-09 (24)): batch slot start $S^B_j$ → $S^{\mathrm{slot}}_j$, slot machine choice $z_{j,m}$ → $g_{j,m}$; carrier $b$ kept (own concept; the batching literature uses $b$ or $B$ for the capacity, ours is $c_s$). |
