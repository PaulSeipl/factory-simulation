# Mathematical documentation

Formal model of the scheduling problem; basis for the modeling chapter of the thesis. Not under version control.

| File | Content |
|---|---|
| [notation.md](notation.md) | Central notation: all sets, indices, parameters and variables, with correspondence to the notation of the sources. |
| [terminology.md](terminology.md) | Binding terminology (order, operation, part, carrier, run, load, …); imported by `simulation/CLAUDE.md` and `seipl27/CLAUDE.md`. |
| [01_basic-fjsp.md](01_basic-fjsp.md) | Base model: FJSP with arbitrary precedence graphs (Kasapidis et al. 2021) plus release times; constraints, makespan, CP-SAT mapping. |
| [02_instance-validation.md](02_instance-validation.md) | Validation of the instance (input, not plan constraints): V0 well-formed, V1–V23 semantic rules per component, `[Vn]` tags in the error messages, negative tests per rule. |
| [03_carriers.md](03_carriers.md) | Carriers (build plates and blanks, persistent binding from forming to separation), loads and runs: format with parts, scopes and carrier kinds, derivation rule for the synchronization, QM per carrier, C8 (one machine per run), C9 (blocked span), C10 (oven p-batches); implemented in all parts. |
| [04_workers.md](04_workers.md) | Workers and work calendar: shifts, common break, overtime, shipping cutoffs, worker shares (whole, prefix, suffix), operations without machine, constraints C1', C11–C14 and checker, tardiness in missed shipping days (phase 1 implemented); DES, rules, CP-SAT planned. |
| [05_rescheduling-frozen-part.md](05_rescheduling-frozen-part.md) | Rescheduling: predictive-reactive strategy, frozen part, C6/C7, shift repair (left and right shift, gaps kept), thresholds triggering a complete rescheduling (rules or CP-SAT), acceptance by change budget; roles of DES and planning tool; open points drift, stability, QM rework. |
| [06_due-dates.md](06_due-dates.md) | Due dates per order (soft): instance format, generation from the longest path or from a reference plan with a tightness factor, objectives total tardiness and number of tardy orders (CP-SAT mapping), EDD. |
| [07_order-arrivals.md](07_order-arrivals.md) | Order arrivals: acceptance, arrival and release per order, packages (a carrier and a run never span arrivals), visible sub-instance of the planning tool; DES event, trigger and sampler follow. |
| [08_serial-batches.md](08_serial-batches.md) | s-batches across orders: one worker share and one setup per batch, chosen by the planner; format, V23, duration with the setup inside the singleton time; checker, DES, rule, CP-SAT to follow. |
| [11_dispatching-rules.md](11_dispatching-rules.md) | Dispatching: sequencing rules (SPT, FIFO, MWKR, LRP) with assignment rules (least load, ECT) or joint; hand-computed examples; Brandimarte results. |
| [12_cp-sat.md](12_cp-sat.md) | CP-SAT model of C1–C5 (static and from a snapshot with change budget), makespan objective, warm start, brute-force verification, Brandimarte results. |
| [14_genetic-algorithm.md](14_genetic-algorithm.md) | GA (BRKGA): random keys for priority, machine, delay and overtime per operation, decoded by the dispatcher into parameterized active schedules (waiting for batch partners, overtime allowance); generation scheme, seeding with the rule plans, hand examples; rescheduling planner (snapshot, warm start, change budget, time limit); NSGA-II over the same keys as offline trade-off analysis. |
| [15_mcts.md](15_mcts.md) | Monte Carlo tree search over the dispatcher's decisions (hook `choose`): root commitment, UCB selection, fixed-width expansion in rule order, rule plans as incumbent; rescheduling planner; hand case against CP-SAT. |
| [13_des.md](13_des.md) | Discrete-event simulation, version 3: the factory: execution of a plan under disturbances (start offsets, late ones counted from actual readiness, OVERDUE events for overruns, planned machine and order kept), event heap, event log; snapshot with frozen part (no information leakage); plan updates from the planning tool. |
| [21_instance-generator.md](21_instance-generator.md) | Random instance generator: parameters, routing modes (chain, split, join, split_join), templates, parameter file. |
| [22_scenarios.md](22_scenarios.md) | Disturbance scenarios: log-normal processing-time factor per operation (mean 1), start offsets (q, a, b), realized durations. |
| [23_metrics.md](23_metrics.md) | Metrics of an execution run: realized makespan, mean flow time, start deviation and machine changes against the start plan, number of repairs and reschedulings, planner time; CSV output. |
| [31_llm-in-scheduling.md](31_llm-in-scheduling.md) | Literature note: LLMs in scheduling (assessment of the field, Shiau et al. 2026), own assessment, options A/B/C; decision A (no LLM for now). |
| [32_target-data-model.md](32_target-data-model.md) | Comparison with the target data model of the Adaptive Scheduler (diagrams): correspondence, decisions and todos (attended time, plate sets, capacity interface to nesting, s-batches, operations per part, workload balance). |
| [33_order-release-interface.md](33_order-release-interface.md) | Scope note: arrival forecast and capacity reserve as parameters of order release (nesting), capacity signal from the plan, toy model of the daily cycle, workload-control sources; not implemented. |
| [references.md](references.md) | All cited sources. |
| [protocol.md](protocol.md) | Working protocol: per pass the decisions, work, findings and open points, with references; newest first. |

Numbering: `0x` model components, `1x` solution methods and simulation, `2x` data generation and experiments, `3x` literature notes and scope decisions.
