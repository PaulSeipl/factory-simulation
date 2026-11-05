# Workers, shifts and day-based tardiness — design

Date: 2026-11-05. Status: agreed in conversation with the user, before the builder check. Formal model goes to
`math/04_workers.md` during implementation (Definition of Done, `CLAUDE.md`). Decisions are marked **(user)** or
**(mine)**; unmarked points follow from them.

## 1. Intent

Workers are the second core extension of the thesis (dual-resource constrained FJSP, DRC). In the dental factory,
machines run unattended for long stretches (print, oven, mill), while workers are needed only for parts of an
operation (loading, setup, removal) or for pure manual steps (separation, polishing, QM, Gegenbetten). Workers have
shifts; machines run through the night. The scheduler has to place attended work inside shifts, keep a common lunch
break, and trade overtime against late orders. Without workers the model overstates capacity: every setup and
removal is assumed to be served instantly, at any time of day.

Success: a plan with workers and shifts is produced by a rule and by CP-SAT, checked by the checker, executed by the
DES under disturbances with rescheduling, and the zero-disturbance test holds (realized = plan, objective = CP-SAT
value). The tardiness/overtime trade-off can be shown as a curve over the weight $w_O$.

## 2. Goals, non-goals, anti-goals

Goals:
- individual workers with qualification sets per operation;
- operations with partial worker occupation (prefix, suffix, whole) and operations without a machine;
- calendar with shifts, common lunch break, overtime;
- tardiness in missed shipping days; objective with overtime weight;
- all seven Definition-of-Done steps (format, checker, DES, rule, CP-SAT, tests, `math/`).

Non-goals:
- worker pauses a running operation to serve the oven (happens in practice; **(user)** too much for the model);
- workload balance / fatigue (protocol 2026-11-04 (2): probably beyond the thesis);
- worker proficiency (different durations per worker), skill learning;
- holidays, part-time or individual shift patterns (all workers share one shift pattern);
- real Fidentis durations: **placeholders** for now **(user)**;
- time lags on precedence edges (replaced, see §3.2).

Anti-goals (would make it a failure even if it runs):
- an infeasible CP-SAT model from a snapshot because a worker is late (oven suffix must be soft in execution, §6);
- overtime used whenever it saves a minute of tardiness (that is why it is a weighted sum, not lexicographic, §5);
- breaking existing instances: Brandimarte and toy instances without workers/calendar behave exactly as today.

## 3. Model

### 3.1 Workers (user)

- Workers are **individuals** $w \in W$, each a unary resource (one thing at a time), not a pool. Reason (user):
  qualifications will come; today every worker is qualified for every worker step.
- Each worker share of an operation has a **qualification set** $W_o \subseteq W$ (default: all workers).
- Prefix and suffix of one operation may be served by **different** workers **(user)**.
- Number of workers: generator parameter, default 3 **(mine)**.

Literature: multiple necessary resources per operation, each chosen from its own set, is the FMRJ extension
(Dauzère-Pérès et al. 2024, `ZSNHKWD6`, p. 14) studied with arbitrary precedence graphs by Kasapidis et al. 2023
(`E58NU6WE`, p. 2). There, an operation occupies **all** its resources for its whole duration
($p_i = \max_j p_{i,\alpha(i,j)}$, `E58NU6WE` p. 2). Partial occupation (prefix/suffix) is **own modeling**. DRC with
worker-dependent preparation before processing: Wang et al. 2025 (`QJHCEX6V`, abstract only read **[uncertain]**).

### 3.2 Operations with worker shares (user, revises protocol 2026-11-04 (2) block 2)

An operation $o$ has a duration $p_o$ (as today, per machine option), an optional machine, and worker shares:

| Kind | Machine | Worker | Example |
|---|---|---|---|
| manual | none | whole $[S_o, S_o+p_o)$ | polishing, separation, QM |
| attended on a machine | whole | whole | print/mill setup and removal operations of a run |
| attended start, machine continues | whole | prefix $[S_o, S_o+a_o)$ | (available; no dental step yet) |
| attended start, rest | none | prefix $[S_o, S_o+a_o)$ | Gegenbetten: work, then rest |
| attended start and end, no gap | whole | prefix and suffix $[S_o+p_o-r_o, S_o+p_o)$ | oven: load, fixed program, remove |
| machine only | whole | none | (existing operations without workers) |

- **Rest without any resource** is the unattended remainder $p_o - a_o$ of an operation without a machine. The rest
  may last longer than needed (**(user)**: minimum, not maximum); the successor simply starts at $S_{o'} \ge C_o$ as
  today. No new constraint type, no time lag on edges.
- **Runs keep their structure (mine, builder check):** setup and removal of print and mill runs stay separate
  operations (C8/C9 unchanged) and get a worker for their whole duration. Additive; `operation_graph` unchanged.
- **Oven batch (mine, builder check):** the worker shares belong to the **run** (one prefix, one suffix per oven
  run, not per carrier). Loading and removal lie **inside** the fixed program time (decision 2026-11-03), so the
  oven duration stays fixed and does not vary; C10 and the CP-SAT batch slots keep one interval per run, the worker
  intervals are tied to the slot.
- **Removal as its own operation only where waiting is allowed** (printer: plate may stay in, printer stays blocked
  until removal, run structure C9 as today). Where waiting is not allowed (oven), the removal is the suffix $r_o$
  of the same operation. **(user)**
- Operations **without a machine** are new: today C1 requires exactly one machine; the "bench" stand-in machine is
  replaced by machine-less worker operations.
- Under disturbances **(user)**: rest time and fixed machine programs (oven) do **not** vary; only attended shares
  vary. **(mine)** Operations where the machine time is attended throughout (manual) vary as a whole, as today.
  The oven does not vary at all (see oven batch above). Unattended main runs of print and mill **do vary**
  **(user)**: the run-duration estimate is inaccurate.
- **Legacy bench (mine, builder check):** existing instances (`toy-carriers`, carrier-kind tests) keep the bench
  machine and their hand-computed optima; only new generator output and the dental example (step 7) use
  machine-less operations.

### 3.3 Calendar and shifts (user)

- $t = 0$ is Monday 08:00 **(mine)**; time stays integer minutes. Working days Monday–Friday, no holidays **(mine)**.
- Shift 08:00–17:30 for all workers. Outside shifts workers are unavailable; **machines keep running** (an
  unattended print can run overnight; its removal waits until 08:00, the printer stays blocked).
- **Lunch break** of 60 min per worker and day, start $b_{w,d} \in [12{:}00, 13{:}00]$ (hard: at most one hour
  postponed). Soft: penalty on postponement $b_{w,d} - 12{:}00$ and on the spread
  $\max_w b_{w,d} - \min_w b_{w,d}$ (workers should break together).
- **Overtime**: shift end $e_{w,d} \in [17{:}30, 19{:}30]$ per worker and day (hard max 2 h), soft penalty
  $O_{w,d} = e_{w,d} - 17{:}30$.
- Attended shares cannot cross a break, the night or the shift end (no preemption). Unattended shares can (an oven
  program cannot end outside a shift because its suffix needs a worker).
- Instances **without a calendar** (Brandimarte, toy) have no shifts and minute tardiness, unchanged.

Literature: machine unavailability from shift patterns, setups that cannot be interrupted and are immediately
followed by processing: Lunardi et al. 2020 (`8Z7BQGIF`, p. 2), with resumable operations (not used here). Break and
overtime formulation: **own modeling**; no source searched beyond this.

## 4. Due dates and tardiness (user)

- `due_date` is the **shipping date**: deadline $D_k$ = 12:00 on that day.
- **Packaging and shipping operation (user):** a new last operation of every order, scope order, worker only (no
  machine, fully attended). A courier picks the packages up at each cutoff, so packaging must be **finished by** a
  cutoff; $C_k$ is the end of this operation and the order ships at the first cutoff $\ge C_k$. Packaging may be an
  **s-batch across orders** (one worker packs several orders in one go). **(mine)** Step 1–6 build it per order;
  the s-batch across orders comes as a later step together with polishing across orders (protocol 2026-11-03 (8)),
  since both need the same new mechanism (a worker s-batch over operations of different orders, decided by the
  planner). **Shipping cutoffs** $\Gamma$ = 12:00 on every working day.
- **Tardiness in missed shipping days:**
  $$T_k = \left|\{\, c \in \Gamma : D_k \le c < C_k \,\}\right|$$
  shipped by 12:00 on the due date → 0; by 12:00 on the next working day → 1; Friday 12:01 to Monday 12:00 → 1.
- The generator places due dates on cutoffs **(mine)**: the existing calibration (`06_due-dates.md`) computes a
  minute value, which is rounded **up** to the next cutoff.
- Minute tardiness stays as a **metric** (gradient for analysis), not in the objective **(mine)**.

## 5. Objective (user, structure mine)

Lexicographic (existing `lexicographic(...)`):
0. oven overstay (minutes), only non-zero from snapshots where a late worker forces it **(mine, builder check)**;
   first, because overstay damages parts. The oven stays blocked while its removal waits.
   **[CHECK WITH FIDENTIS]** (user): is overstay really worse than a late order, and is the oven blocked while the
   parts wait?
1. $f_1 = \sum_k T_k + w_O \sum_{w,d} O_{w,d}$ — one level, weighted. $w_O$ = days of tardiness per minute of
   overtime; **varied in experiments** to show the trade-off curve instead of fixing a "right" value. Weighted sum
   as a standard technique: source not searched **[uncertain]**.
2. break penalties: postponement + spread (weights equal **(mine)**).
3. makespan. **Metric (exact):** an activity clock that runs while any worker is on shift **or** any machine is
   processing (user: a print until 22:00 counts, 22:00–08:00 does not). **In CP-SAT:** plain end time as a proxy
   **(mine)**, since the exact clock needs a per-minute indicator and this level only breaks ties.

Priority (user): late order worse than overtime "to a certain degree" (hence the weight); overtime worse than a
postponed break.

## 6. Execution (DES)

- Workers start no attended share outside their shift or during their break.
- **Planned order per worker (mine, builder check):** as for machines, a worker follows their planned sequence
  (no overtaking); the swap rule is the only exception. Repair keeps worker sequences.
- **Swap rule (user):** when an operation has reached its planned start and is ready, but its planned worker is
  still busy, a qualified worker who is free now and whose next planned task starts no earlier than now plus the
  **expected** attended share takes it. Tie-break: most room before the next task **(mine)**. Without disturbances
  the rule never fires (zero-disturbance test holds).
- The DES writes the actual worker into its current plan after a swap **(mine)**, so repair sees the real state.
- **Oven suffix (user):** hard in the plan, soft in execution. If no worker is free at the end of the program, the
  removal waits; the minutes are recorded as **oven overstay**.
- Breaks: a worker busy at break time takes the break after finishing, individually **(mine)**; recorded as
  postponement/spread.
- Work past the shift end is overtime; past 19:30 an **overrun** (metric).
- Snapshot: `FrozenOperation` gets the actual prefix/suffix workers; a running oven shows its **planned** suffix
  worker, which rescheduling may still change. The planning tool sees a swap at the next DES time point (snapshot
  is taken after events, before starts); started operations are frozen anyway.

## 7. Planning tool

- **Dispatching rule (mine):** list scheduling places an operation at the earliest time where the machine and a
  qualified worker for prefix and suffix are free, inside shift and outside break. Worker: earliest free, ties by
  least load. Breaks at 12:00, no overtime: a simple baseline.
- **Repair (mine):** keeps machines, workers, order (definition unchanged, `terminology.md`). An attended share
  pushed into a break or the night moves to the next feasible slot. Repair creates no overtime.
- **Complete rescheduling:** may reassign workers and machines; only rescheduling decides overtime.
- **CP-SAT (mine, mapping):**
  - per worker share and eligible worker an optional interval; exactly one present per share; per worker
    `AddNoOverlap` over its intervals, its nights/weekends (fixed intervals), its break interval (start variable
    $b_{w,d}$) and its off-shift interval $[e_{w,d}, \text{next } 08{:}00)$;
  - prefix interval start = operation start; suffix interval end = operation end (fixed offsets);
  - tardiness: one Boolean per order and cutoff in the horizon, $[C_k > c]$, summed for $c \ge D_k$;
  - spread: `AddMaxEquality` / `AddMinEquality` per day;
  - from snapshots: oven suffix soft (removal may end later, penalized), so the model is never infeasible because
    of a late worker;
  - symmetry among identical workers: expected slowdown; symmetry breaking is left to the builder.
- Frozen part: running operation fixed incl. prefix worker; planned suffix worker of a running oven still free.

## 8. Metrics (new)

Overtime per worker and day; break postponement and spread; oven overstay; overruns past 19:30; number of swaps;
tardiness in days and in minutes; tardy orders; makespan on the activity clock.

## 8a. Visualization (user asked, design mine)

A new calendar Gantt in `simulation.viz` for notebook examples, next to `plot_gantt`:
- **x-axis in clock time** (weekday and hour) over a chosen window (e.g. 3 days); **nights and weekends
  compressed** to a narrow hatched gap, so the shifts take the width.
- **Background bands:** off-shift (grey), overtime window 17:30–19:30 (amber), shipping cutoffs as dashed vertical
  lines.
- **Rows:** machines first, then one row per worker, then a "resting" row for unattended shares without a machine
  (Gegenbetten).
- **Bars:** attended share solid, unattended share light; a machine blocked while waiting for removal hatched; the
  same operation has the same label on its machine and worker rows. Breaks per worker as grey blocks (a postponed
  break visibly offset); overtime work in amber.
- Same colors per operation as `plot_gantt`; a running-time cursor optional for snapshots.

## 9. Order of implementation

Each step with tests, `math/` and a protocol entry; user approval between steps (working style, `CLAUDE.md`):
1. calendar and day tardiness (no workers yet); existing instances unchanged;
2. machine-less operations and worker shares in the format (schema bump) and the checker;
3. DES: shifts, breaks, overtime, swap rule, oven overstay;
4. dispatching rule;
5. CP-SAT;
6. snapshot and rescheduling (frozen workers, soft oven suffix);
7. generator (workers, calendar, placeholder attended shares, packaging operation), dental example, calendar
   Gantt (§8a), notebook, `math/04_workers.md`;
8. later: worker s-batch across orders (packaging, polishing).

## 10. Left to the builder

Field names and format shape; data structures in `CompiledInstance`; symmetry breaking; exact horizon for
calendar intervals; test instances (one mini instance with a hand-computed result per step, negative test per
validation rule, zero-disturbance never skipped).

## 11. Open (not blocking)

Real attended shares and durations from Fidentis; polishing across orders as a worker s-batch (protocol 2026-11-03
(8)); worker qualifications once known; reproducible CP-SAT under a time limit (protocol 2026-11-04 (4)).
