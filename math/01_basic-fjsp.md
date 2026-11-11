# 01 Basic FJSP

## 1. Prose description

A set of customer orders has to be processed on a set of machines. Each order consists of operations. Each operation can run on one of several alternative (eligible) machines, with a machine-dependent processing time. Within an order, operations are linked by precedence relations that form a directed acyclic graph (DAG). An order cannot start before its release time. Each machine processes at most one operation at a time, and operations are not interrupted.

This is the **flexible job shop scheduling problem with arbitrary precedence graphs** of Kasapidis et al. (2021, §2), extended by **release times**:

- The classical FJSP (Dauzère-Pérès et al., 2024, §2, p. 410) assumes a linear route per job. Replacing the route by an arbitrary DAG per job is the extension studied by Kasapidis et al. (2021). The review calls it *non-linear routes*, $\beta = bom$ (Dauzère-Pérès et al., 2024, §6.1, p. 421), and notes that it requires no decisions beyond those of the classical FJSP. Lunardi et al. (2020) use the same structure for the online printing shop. With a chain per order, the model reduces to the classical FJSP (Kasapidis et al., 2021, p. 4049); the Brandimarte instances are of this type.
- Release times replace the assumption that all jobs are available at time 0 (Dauzère-Pérès et al., 2024, assumption 2, p. 410; extension $\beta = r_j$, Table 1, p. 412). Lunardi et al. (2020) include release times per operation; ours are per order (see C4).

The remaining assumptions coincide with the sources: every machine is available from time 0, an operation is executed once by one machine, a machine executes at most one operation at a time, no preemption (Dauzère-Pérès et al., 2024, p. 410; Kasapidis et al., 2021, p. 4046).

**Complexity.** Garey et al. (1976, Theorem 3, p. 128) show that minimizing the schedule length (makespan) in a job shop with only two machines is NP-complete, even if the input length is measured by the sum of the task lengths, i.e. in the strong sense. That job shop is a special case of the present model: one eligible machine per operation ($|M_o| = 1$), chains as precedence graphs, and $r_k = 0$. Hence the present model is NP-hard in the strong sense as well, and no polynomial-time exact algorithm is to be expected unless P = NP. This is a worst-case statement; up to which instance size CP-SAT proves optimality in practice has to be determined experimentally (for CP models on the Brandimarte instances see Naderi & Roshanaei, 2022, p. 20).

Precedence with reconvergence at QM (JPC), loads, workers and dynamic events are added as separate components on top of this base model.

## 2. Sets, parameters, variables

All symbols are defined in [notation.md](notation.md), including correspondence tables to the notation of the sources. Introduced here:

- Sets: $\mathcal{K}$, $O$, $O_k$, $k(o)$, $M$, $M_o$, $P$
- Parameters: $p_{o,m}$, $r_k$
- Variables: $x_{o,m}$, $S_o$, $C_o$, $C_{\max}$

## 3. Constraints

Equation numbers refer to the MILP of Dauzère-Pérès et al. (2024, (1)–(8), p. 410) [DP], the MIP (9)–(17) and CP model (18)–(22) of Kasapidis et al. (2021, pp. 4048–4049) [K], and the MILP (1)–(9) and CP model (33)–(40) of Lunardi et al. (2020, pp. 5, 8) [L].

(C1) Assignment: every operation is processed on exactly one of its eligible machines. [DP] (2), [K] (10); CP form: [K] (19) `Alternative`.
$$\sum_{m \in M_o} x_{o,m} = 1 \qquad \forall o \in O$$
With workers ([04](04_workers.md)), operations without machine $O^{\emptyset}$ are exempt and have a fixed duration (C1'); the base model has $O^{\emptyset} = \emptyset$.

(C2) Non-preemption: an operation runs without interruption for the processing time of its assigned machine. [DP] use only start times and write $t_i + \sum_k p_{ki}\,\alpha_{ik}$ inside (3) and (6); [K] use only completion times $C_i$. Using both $S_o$ and $C_o$ linked by C2 is equivalent; in CP models it is implicit in the interval variable (size $= p_{o,m}$, [K] p. 4049; [L] (40)).
$$C_o = S_o + \sum_{m \in M_o} p_{o,m}\, x_{o,m} \qquad \forall o \in O$$

(C3) Precedence within an order: an operation $o'$ starts at the earliest when its predecessor $o$ has finished. [K] (11) for all job predecessors $j \in PJ_i$ of a DAG; CP form [K] (20), [L] (34) `EndBeforeStart`. [DP] (3) is the special case of a linear route.
$$S_{o'} \ge C_o \qquad \forall (o, o') \in P$$

(C4) Release: no operation of an order starts before the order's release time. [L] (8) and, in CP form, (37) state $S_i \ge r_i$ with a release time $r_i$ per operation; ours is the special case $r_i = r_{k(i)}$ for all operations of an order. Only operations without predecessors are actually restricted, since C3 propagates the bound along $P$.
$$S_o \ge r_{k(o)} \qquad \forall o \in O$$

(C5) Machine capacity: two operations assigned to the same machine do not overlap. [DP] (4)–(5) and [K] (12)–(13) linearize this disjunction with sequencing binaries and a big-M constant; CP form [K] (21), [L] (36) `NoOverlap` per machine. Here it is stated as the logical disjunction, which is what the CP model uses directly.
$$x_{o,m} = x_{o',m} = 1 \;\Rightarrow\; C_o \le S_{o'} \;\lor\; C_{o'} \le S_o \qquad \forall m \in M,\; \forall o \ne o' \in O \text{ with } m \in M_o \cap M_{o'}$$

## 4. Objective function

The constraints C1–C5 do not depend on the objective. The objective is a **parameter** of the model: solver, GA and dispatching-rule evaluation take it as an input, so further objectives can be added without changing C1–C5.

**Makespan** is used only for validation against the Brandimarte benchmarks, where it is the standard criterion ([DP] (1), (6); [K] (9), (15) and CP (18), (22); [L] (33); Dauzère-Pérès et al., 2024, p. 410, call it the most classical FJSP criterion). It is not the objective of the thesis.
$$\min C_{\max} \quad \text{s.t.} \quad C_{\max} \ge C_o \qquad \forall o \in O$$

**Objectives of the thesis:** not yet fixed. Planned are two objectives optimized together (e.g. a tardiness measure and a second criterion). Tardiness needs a due date $d_k$ per order, which is not yet part of the instance format (schema version bump). How the two objectives are combined (weighted sum, lexicographic, or Pareto front) is open; see section 6.

## 5. Implementation in code

| Formal | Code (commit `1217f7e`) |
|---|---|
| $\mathcal{K}$, $O_k$, $r_k$ | `simulation.model.instance.Order` (`id`, `operations`, `release`) |
| $O$, $o$ | global index `0..n_ops-1` in `simulation.model.compiled.CompiledInstance`; `op_keys[o] = (order_id, op_id)`, `op_index` inverse. Operations are indexed in file order, so each $O_k$ is a contiguous index range. |
| $M$, $m$ | `Instance.machines`; `CompiledInstance.machine_ids` / `machine_index` |
| $M_o$, $p_{o,m}$ | `Operation.options: dict[machine_id, duration]`; compiled: `options[o] = ((m, p_{o,m}), ...)` |
| $P$ | `Operation.predecessors` (local operation IDs of the same order); compiled: `predecessors[o]`, `successors[o]` |
| $r_{k(o)}$ | `CompiledInstance.release[o]` (copied from the order to each operation) |
| $x_{o,m}$, $S_o$, $C_o$ | `simulation.model.schedule.Assignment(order_id, op_id, machine, start, end)`: $x_{o,m} = 1$ for `machine`, $S_o$ = `start`, $C_o$ = `end` |

Guaranteed by the instance validation (`Instance.check_references`, field constraints): $M_o \ne \emptyset$; $M_o \subseteq M$; $p_{o,m} > 0$; $r_k \ge 0$; $P$ only within one order, no duplicate pairs; $(O_k, P)$ acyclic (otherwise C3 would be infeasible). `CompiledInstance.topo_order` is one topological order of $(O, P)$. Integer data (times and durations) is assumed as in Lunardi et al. (2021, §4, p. 423), who note that rational data can be made integer by a change of units.

`Schedule` only checks $S_o \ge 0$ and $C_o > S_o$ (structure, not feasibility).

**Feasibility checker** `simulation.check.feasibility.check_schedule(ci, assignments)` checks C1–C5 against a `CompiledInstance` and returns every violation, labelled with the constraint number used here:

| Label | Check |
|---|---|
| C0 | the assignment references an operation that is not in the instance (no counterpart in the model; input error) |
| C1 | every $o \in O$ assigned exactly once (missing or duplicate assignment means $\sum_m x_{o,m} \ne 1$); machine $\in M_o$ (an unknown machine is never in $M_o$) |
| C2 | $C_o - S_o = p_{o,m}$ for the assigned machine (only checked if C1 holds for the machine) |
| C3 | $S_{o'} \ge C_o$ for every $(o, o') \in P$ with both assigned |
| C4 | $S_o \ge r_{k(o)}$ |
| C6, C7 | only with a snapshot (revised plan, [05](05_rescheduling-frozen-part.md)): operations not started are not planned before $t$ (C6); frozen operations appear unchanged (C7); C2 is not checked for frozen operations |
| C5 | per machine, every pair of overlapping half-open intervals $[S_o, C_o)$; intervals that only touch ($C_o = S_{o'}$) do not overlap |

The checker is objective-agnostic (no makespan) and independent of CP-SAT, as required in `CLAUDE.md`. Dispatching rules: [11](11_dispatching-rules.md). CP-SAT: [12](12_cp-sat.md). The DES does not exist yet.

CP-SAT mapping (implemented in `simulation.planners.cpsat`, details in [12](12_cp-sat.md)). The CP models in the sources ([K] (18)–(22), [L] (33)–(40), Naderi & Roshanaei (2022) (8)–(12)) are written for IBM CP Optimizer. The transfer to OR-Tools CP-SAT is **own**:

| Source (CP Optimizer) | CP-SAT |
|---|---|
| optional interval $a_{o,m}$ of size $p_{o,m}$ ([L] (40), [K] $\phi_{i,k}$) | `new_optional_fixed_size_interval_var` on the shared start variable $S_o$ with presence literal $x_{o,m}$ |
| `Alternative`$(o, \{a_{o,m}\})$ (C1, [K] (19), [L] (35)) | `add_exactly_one`$(x_{o,m})$; all $a_{o,m}$ start at $S_o$, and $C_o = S_o + \sum_m p_{o,m} x_{o,m}$ (C2), so no `only_enforce_if` linking is needed |
| `EndBeforeStart` (C3, [K] (20), [L] (34)) | linear `add(start[o'] >= end[o])` |
| `startOf` $\ge r$ (C4, [L] (37)) | lower bound of the start variable |
| `NoOverlap` per machine (C5, [K] (21), [L] (36)) | `add_no_overlap` over the optional intervals of machine $m$ |
| $\max$ `EndOf` (objective, [K] (22), [L] (33)) | objective builder of `simulation.objectives` (makespan: `add_max_equality`), then `minimize` |

## 6. Assumptions and open points

- Time is integer in `time_unit` (default minutes). Brandimarte instances carry no unit; the loader assumes `"min"`.
- No setup times, no transport times, no time lags, no machine unavailability in this component. Dauzère-Pérès et al. (2024, §5) survey these as additional constraints; Lunardi et al. (2020) model unavailability, setup times and partial overlap for the printing shop.
- Release times are defined per order, not per operation (special case of Lunardi et al., 2020).
- Some Brandimarte instances contain machines with $\{o : m \in M_o\} = \emptyset$ (mk08: 1, mk10: 4). They are part of $M$ but can never be busy. Whether utilization metrics include them is open.
- **Order structure in practice (to be modeled later, not now):** a typical order splits into several paths: one for the secondary part and several identical paths for the primary parts (the same route repeated once per part), reconverging at QM. Other orders have simpler routes. As long as all paths are processed and the number of parts is known per order, this is a DAG per order and fits the present model ($\beta = bom$); the identical paths are copies of one subgraph. Lunardi et al. (2020, Fig. 1, p. 2) show structurally similar job DAGs (a cutting operation splitting into independent sequences; cover and pages assembled by binding).
- **Objective interface (for the first solver/GA cycle):** every objective needs two implementations, an evaluator on a finished schedule (GA, rules, DES, reporting) and an expression builder for CP-SAT; a test must check that both agree on CP-SAT solutions. With two objectives the evaluator returns a tuple; the combination (weighted sum, lexicographic, Pareto via ε-constraint, Dauzère-Pérès et al., 2024, p. 416) is a separate parameter. Non-regular objectives would invalidate decoders that build semi-active/active schedules (same, p. 415).
- **Carriers and runs extend this component** ([03_carriers.md](03_carriers.md), 2026-11-02): carrier and run operations serve several orders, so $k(o)$ becomes a set and the compiled precedence $P^*$ crosses orders, but only through carrier and run operations. C1–C5 apply unchanged to the compiled graph; C8 and C9 are added for runs.
- **To clarify with the supervisor:** the two objectives of the thesis and how they are combined.

## 7. Sources

- Problem definition and assumptions of the classical FJSP; constraints C1, C3 (linear case), C5 and the objective as MILP: Dauzère-Pérès et al. (2024), §2.1, p. 410. Non-linear routes: same, §6.1, p. 421.
- FJSP with arbitrary precedence graphs, MIP and CP models matching C1–C3, C5 and the objective: Kasapidis et al. (2021), §2.2–2.3, pp. 4048–4049.
- Release times per operation, C4 as MILP (8) and CP (37); DAG precedence: Lunardi et al. (2020), §2–3, pp. 5, 8.
- CP model for the classical FJSP: Naderi & Roshanaei (2022), §2.2, p. 5. They report that their CP model outperforms the MIP model in optimality gaps and number of optima found on existing benchmarks (p. 20).
- Integer data assumption, random-key representation for GA/DE with DAG precedence (relevant later for the GA): Lunardi et al. (2021), §4.
- Complexity: Garey et al. (1976), Theorem 3, p. 128; the reduction to the present model is own.
- Batching variants in the disjunctive graph: Dauzère-Pérès et al. (2024), §5.3, p. 418. Ganging operations: Lunardi et al. (2020), p. 1.
- Name "FJSP", instance format and benchmark instances: Brandimarte (1993).
- Own: the CP-SAT transfer table in §5; per-order release as a special case of [L].

Full references in [references.md](references.md).

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-19 | `1217f7e` | Initial documentation of the base model, as implemented in the instance format, Brandimarte loader and `compile_instance`. |
| 2026-10-19 | `1217f7e` (code unchanged) | Constraints referenced to the MILP in Dauzère-Pérès et al. (2024); C4 marked as own; DAG precedence identified as non-linear routes ($\beta = bom$). |
| 2026-10-19 | `1217f7e` (code unchanged) | Referenced Kasapidis et al. (2021), Lunardi et al. (2020, 2021), Naderi & Roshanaei (2022). Problem identified as FJSP with arbitrary precedence graphs; C4 now referenced to Lunardi et al. (2020) instead of own; CP-SAT mapping table added; order path structure noted as open point. |
| 2026-10-19 | `1217f7e` (code unchanged) | Complexity statement (Garey et al., 1976); objective declared a parameter, makespan only for benchmarks, two thesis objectives open; loads noted as breaking $k(o)$ and order-local $P$, options (a)/(b) listed. |
| 2026-10-19 | e8617db | Feasibility checker for C1–C5 implemented (`simulation.check.feasibility`); label table in §5; objective-interface notes in §6; loads moved to draft `03_carriers.md`. |
| 2026-10-20 | 75065e4 | CP-SAT mapping implemented (shared start variable instead of `only_enforce_if` linking); links to 11 and 12. |
| 2026-10-29 | 17d05a8–28ac70f | Checker extended by C6 and C7 for revised plans (math/05). |
| 2026-11-05 | e5348b0–78e228d | C1 note: operations without machine (C1' in [04](04_workers.md)); checker skips them in the machine sweep. |
