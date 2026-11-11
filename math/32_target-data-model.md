# 32 Target data model: comparison and decisions

Scope note (2026-11-04). Compares the model in code with the target data model of the Adaptive Scheduler in `diagrams/data_modell_adaptive_scheduler.mmd` (MES-facing problem instance) and `diagrams/solver_modell_adaptive_scheduler.mmd` (solver instance), and records the decisions and todos that came out of it. Proposing batches to nesting (`architecture-diagram.mmd`, sequence diagrams) is **deprecated** (user). MES integration stays out of scope; the comparison only concerns the model.

## 1. Correspondence

| Target model | Code | Note |
|---|---|---|
| `ProblemInstance` / `SolverInstance` | `Instance` / `CompiledInstance` | same two layers |
| `RoutingOperation.lane`, `unitKind` | `Operation.scope`, `carries` | |
| `formsBatch`, `couplingUntilOperationId` | `role` form / separate | |
| `carrierType` PLATE / BLANK | carrier kind = part type of its parts (`carrier_kinds`) | an explicit kind only if two kinds hold the same part type |
| `Batch` | `Carrier` | forming and coupling ops follow from the route roles; machine and status are plan / snapshot state; `plateId` comes with plate sets (§3) |
| `batchId` / `loadId` | carrier / run | |
| `maxBatch` | `batch_capacity` (p-batch, carrier steps only) | target: s-batches on many steps (§2) |
| `extraPartDiscount` | estimator share $\lambda$ | |
| `MACHINE_RUN`, `continuityGroupId` | run (C8, C9) | |
| `ExistingBatch`, fixed `Assignment` | given carriers / runs, `FrozenOperation` | |
| `durationDistribution` | scenario $\sigma$ (global) | per step: open |
| `SolverStatus.FALLBACK` | planner keeps the plan | |
| `Routing` shared by `routingId` | route copied into every order | equivalent |

## 2. Decisions and todos (user 2026-11-04)

- **Attended / unattended** (with workers, 04): attended time occupies worker **and** machine, unattended time only the machine (`hasHandoff`: the worker starts, the machine continues alone; often the worker is needed again at the end). Splitting every operation into setup → main → removal is too fine (removals are often very short, some steps have no machine, and the MES would have to report every segment). **Decided (user 2026-11-04, my proposal): three building blocks, used only where they matter.**
  1. an operation with a resource set (machine and/or worker), attended for its whole duration (bench work, QM);
  2. **rest time without any resource** as a minimum time lag on a precedence edge, $S_{o'} \ge C_o + l_{o,o'}$, not as an operation;
  3. the run structure (setup, main, removal) only for handoff steps whose end needs a scarce worker (print today; oven, mills if needed).
  Granularity follows what the MES reports: a segment the MES does not report cannot be fed back to the DES. A short removal is added to the main operation, assuming a worker is free for a moment.
- **Plate sets** (eventually; plates may become scarce at higher volume): plates come in sets (mostly 4); a print run uses exactly **one set** (confirmed); after the run every plate of the set, used or not, is ground before the set is available again. Model: the set is a reusable resource occupied from the print setup to the end of the grinding; grinding waits for the saws of all used plates of the set and is an operation without customer order (`OrderKind.MAINTENANCE`); CP-SAT: assignment of print runs to sets, one occupancy interval per run and set, no overlap per set.
- **Interface to nesting by capacities** (instead of estimating print durations): nesting estimates print durations better than the scheduler (the estimator is a rough approximation and stays a fallback; a duration reported by nesting already overrides it, `Run.duration`). The scheduler gives nesting the remaining capacities given frozen and planned operations: printer time, mill time, worker time, free plate sets, plus order data (telescopes, later priority classes). Caveat (mine): a total per resource hides timing; a printer with 600 free minutes in ten gaps cannot host a 300-minute print. Hence printers as **free gaps** (start, length minus setup and removal: the `PrintSlot`), mill and worker time per time bucket (e.g. shift). The gaps come from the current plan without the new runs, which breaks the circle plan → durations → nesting. A due-date bound per part (`PrintDeadline`) can be added later.
- **s-batches with `maxBatch`**: many steps may process several parts serially (maxBatch = 1: no batch), e.g. polishing, often **across orders**. Gain only through a time incurred once per batch (base + per-unit time); without it an s-batch is a sequence. Planner decision, not modeled.
- **Operations per part** (note, with rework): today an operation with scope of a part type covers all parts of that type of the order, a carrier operation the parts on the carrier; which part was processed follows from that. Not expressible: parts of one order at different times or machines, rework or scrap of a single part (`replacesPartId`). Planned: scope "per part" (one operation per part, expanded from the route); `maxBatch` then groups per-part operations again, which generalizes today's $n \cdot p$ operation. To be done together with QM rework loops.
- **Workload balance** (objective; user 2026-11-04: with the goal of reducing worker fatigue probably **beyond the scope of the thesis**): spread operations over the time window instead of packing them, against worker fatigue and as a buffer for breakdowns and new orders. Conflicts with makespan and tardiness by design. Formulations: peak load per time bucket and resource, or deviation from the mean load: resource leveling, one of three classes of resource problems in project scheduling, used when resources are sufficient (Herroelen 1972, `ZPNJK6M2`, pp. 4–5); common objectives are the maximum or the sum of squares of daily usage, deviations from a target level and the peak (Aristotelous & Nearchou 2024, `EUS4ZZVJ`, p. 2), mostly with a fixed schedule length; exact methods do not scale (ibid.), heuristics shift activities within their slack (Li et al. 2023, `5BX85M6T`, p. 2). The buffer goal is robustness, a separate criterion and a separate strategy: robust pro-active scheduling, next to completely reactive and predictive-reactive scheduling (Ouelhadj & Petrovic 2009, `DG38JM6L`, pp. 2–3; Aytug et al. 2005, `DPAZ3QNT`, §4.2); techniques insert temporal slack so that disruptions are absorbed without rescheduling (Davenport et al., `T67B96FW`, p. 1) or explicit idle time against resource breakdowns (Lambrechts et al. 2011, `LQFDQ743`, p. 1). The thesis follows the predictive-reactive strategy ([05](05_rescheduling-frozen-part.md)); robustness by slack is related work. Worker load in dynamic FJSP: Zhou et al. 2026 (`EA8QC55F`, p. 1) treat workload balance and fatigue as explicit constraints (constrained RL) and note that DRL methods seldom do; their event trigger chooses between right shift and full rescheduling, as ours does. The DES does not start an operation before its planned start, so a planned spread survives execution, but shift repair may move operations earlier.
- **Arrival forecast, order kinds FORECAST / MAINTENANCE, tentative operations**: later.
- **Not yet modeled**, from the target model: calendars and availability, priority, per-step duration distributions, `batchDurationTable` (batch size → duration), objective SCHEDULE_STABILITY (todo in 05).

## 3. Sources

Checked in Zotero (collection MA, `text --grep`, 2026-11-04); full entries in [references.md](references.md):
- Herroelen 1972 (`ZPNJK6M2`): resource leveling as one of three classes of resource problems (p. 4), when resources are sufficient (p. 5).
- Aristotelous & Nearchou 2024 (`EUS4ZZVJ`), p. 2: leveling objectives; priority rules in commercial software; exact methods do not solve large instances.
- Li, Zheng & Zhu 2023 (`5BX85M6T`), pp. 1–2: leveling minimizes fluctuations of resource usage; heuristics shift activities within their slacks.
- Davenport, Gefflot & Beck (`T67B96FW`, year not in Zotero), p. 1: robust schedules absorb unexpected events without rescheduling; temporal slack.
- Lambrechts, Demeulemeester & Herroelen 2011 (`LQFDQ743`), p. 1: explicit idle time against resource breakdowns.
- Klimek & Łebkowski 2009 (`8SPWPQ6M`), p. 2: predictive-reactive scheduling in two phases; robust buffer allocation.
- Zhou, Tan & Li 2026 (`EA8QC55F`), p. 1: workload balance and fatigue as constraints in dynamic FJSP.
- Already in the library: Ouelhadj & Petrovic 2009 (`DG38JM6L`), pp. 2–3, three categories of dynamic scheduling incl. robust pro-active; Aytug et al. 2005 (`DPAZ3QNT`), §4.2 robust scheduling approaches; Berti et al. 2021 (`8F7AYGYK`), ageing workforce, rest allowance and ergonomics in DRC job shops (p. 1); Usman et al. 2026 (`XUBLNB8X`), review of resource-flexible JSP incl. ergonomics as a trend (p. 2); Xu et al. 2011 (`K82ZAAIS`), DRC review: load smoothing by job release (p. 2) **[uncertain: only the grep line read]**.
- Not in the library: Hartmann & Briskorn RCPSP surveys (cited in `EUS4ZZVJ`), Aribi et al., Sun et al.; Guo et al. 2023 dropped (Chinese only).

Own modeling: the three building blocks for attended time, plate sets as reusable resource, capacity interface with free printer gaps.

## 4. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-04 | 31b7574–91ebc7c | Created: correspondence with the target data model, decisions and todos. |
| 2026-11-04 | 31b7574–91ebc7c | Attended time decided (three building blocks); workload balance likely out of scope; sources checked in Zotero. |
