# s-batches across orders (one setup per batch): design

Date: 2026-11-17. Status: **proposal; form (b1) agreed by the user 2026-11-17 (§0), details open**. Nothing is implemented. The formal model goes to `math/` once
the user has decided (§9). Requested by the session working on the Fidentis case. The user said on 2026-11-17 that
s-batches across orders are really needed (e.g. primary data preparation), that the planner must form them itself,
and that the formulation is open.

**Base of this spec.** The Fidentis case (`data/routes/fidentis.json`, `data/generator/fidentis.json`,
`base_durations`, the MES table in [21](../../../math/21_instance-generator.md) §4a, the shift limit in §6) as of
commit `c3c7387`. MES values: `SEED_STEPS` in the MES backend `services/kpi/capacity.py` (read 2026-11-17).

## 0. Decisions (user, 2026-11-17, answers to §9)

- **Q1 availability:** the batch moves on together. That means **(b1) batch availability**.
- **Q2 setup across a break or the night:** no. So one batch = one whole worker share. This settles the form.
- **Q3 maxBatch 20:** smaller in reality; 20 is a future hope of Fidentis.
- **Capacity:** s-batch steps have no capacity limit of their own. The worker share (shift part, C13) limits the
  batch. So $c_s = \infty$ for s-batch steps. The constraint $\sum y\, n_o \le c_s u_j$ and the validation
  $n_o \le c_s$ are dropped. Only the validation "setup plus the largest single member fits one shift part" stays.
- **s-batch steps** (rule of the user: attended or unattended per-unit time > 0 *and* MES maxBatch > 1): sand
  blasting, data prep primary, Gegenbetten, part removal from blank, primary polishing, finishing primary, sawing,
  support removal, grind clean, steam clean, polish. Route ids: `blast`, `data_prep_pri`, `gegenbetten`, `separate`,
  `polish_pri`, `finish_pri`, `saw`, `support_removal`, `grind`, `steam`, `polish_sec`.
- **Gain within one order** (user): the primary parts of one order are batched anyway, which saves e.g. 45 minutes
  for data prep of 4 parts ($3 \cdot 15$). **The model already has that.** An order or part operation covers all
  parts of that type of the order and pays its base once (`base_durations`: $15 + 15 n$). What s-batches add is the
  saving **across orders**: one base per batch instead of one per order. For the order and part steps on the list
  that is $15 + 10 + 10 + 15 + 10 + 10 + 10 = 80$ minutes per extra order in a batch at every step.

**Route corrections (user, 2026-11-17, second round; replace the step list above).** Two kinds of "setup + per
unit" steps:

1. **Free s-batch** (the planner chooses the members, across orders or carriers; base once per batch):
   `data_prep_pri`, `polish_pri`, `finish_pri`, `support_removal`, `grind`, `steam`, `polish_sec`;
   `inspect`, `document`, `pack` (10 + 10 per order each); `clean` (15 attended + 10 per plate, at most 4 plates);
   `blast` (5 + 5 per plate, at most 4 plates). So a capacity $c_s$ (in plates) is needed after all, for `clean`
   and `blast`; the other free steps have none.
2. **Carrier-bound** (members fixed by the persistent carrier, no choice; base once per carrier): `gegenbetten`
   (prefix $5 + 5n$ attended for $n$ parts on the blank, then 15 unattended; 2 parts: 30), `separate`
   ($10 + 10n$), `saw` (15 + 15 per secondary part on the plate), `qm` and `recheck` ($15 + 15$ per telescope on
   the plate). These are not s-batches in the planning sense: the duration is $\mathrm{base} + \mathrm{per\_unit}
   \cdot u$ per carrier, known at compile time. Today the generator folds an amortized base into the unit time
   (e.g. `qm` 16 per telescope = $15/10 + 15$ rounded); that is wrong and gets fixed in the generator.

Needed for kind 2 (no s-batch machinery): per-carrier base, i.e. the estimator fixed part $p^0$ that the format
already has (`PerCarrierStep` hard-codes `fixed=0`); a per-part base for `saw` (time per secondary part, not per
telescope); and a **prefix that grows with the parts** for `gegenbetten` (`WorkerShare.prefix` is one number per
step today: a format change). Stand-in pool `hand`: carrier steps need a machine (`CarrierStep.options` has
`min_length=1`); order and part steps may have none. Proposed: allow carrier steps without a machine, remove `hand`
(with a prefix, `gegenbetten` would otherwise block a `hand` machine during its unattended rest).

**Corrections to the text below.**
- `Operation.step` and `RouteOperation.step` **already exist** (`model/instance.py`; the route file sets them).
  What is missing is the step per operation in `CompiledInstance` (03 §6 todo).
- **Carrier steps are amortized today, not full.** Blast, sawing, Gegenbetten and separation take the MES share
  $\mathrm{base}\cdot u/B + \mathrm{per\_unit}\cdot u$ (e.g. blast $5/4 + 5 \approx 6$ per plate). That is
  optimistic: it assumes batches that nothing forms. The order and part steps pay the full base per order, which
  is pessimistic. With s-batches both get the exact per-batch base. The carrier steps therefore get **longer**
  as singletons (blast 10 instead of 6 per plate) and shorter only when batched.
- **Steps that match the user's rule but are not on the list** (MES seed values): PART_CLEANING (15 + 10 per
  plate, maxBatch 4), REWORK_CHECKOUT, i.e. QM and recheck (15 + 15 per telescope, 10), REWORK (20 + 10 attended
  per telescope, 10), INSPECTION, DOCUMENTATION, PACKAGING_SHIPPING (10 + 10 per order, 10), REMOVE_MOUNT
  (10 + 2 per part, 20), PART_POWDER_REMOVAL (15 + 5 per plate, 4). Powder removal and mount removal are the
  removals of the print and blank runs. Rework is a per-carrier run on the mill. Open: are cleaning, QM, recheck
  and the three order steps deliberately left out (§9 Q9)?

## 1. Problem

Several manual steps of the Fidentis route have a time that is paid **once per batch** plus a time per unit. Example
from the MES: DATA_PREP_PRIMARY takes 15 per batch of up to 20 primary parts, plus 15 per part. Other candidates
are polishing, sawing, grinding (Gegenbetten) and inspection. A batch may contain parts of **several orders**. The
model today has no such time. The Fidentis case charges the full setup in every order operation
(`base_durations`: $\mathrm{base} + \mathrm{per\_unit} \cdot u$). This is pessimistic: with batches the setup is
paid once for all members.

Out of scope: carriers (plates, blanks). Nesting gives them, and nothing here changes them. The oven p-batch (C10)
also stays as it is. This spec covers worker or machine steps where the planner may serve parts of several orders
one after another under a single setup.

**Proposed term** (to go into `math/terminology.md` once agreed; that file is the only place where terms change):
*s-batch*: a set of operations of one step that one resource processes one after another, with one setup at its
start. The batch is a planning decision; it exists only in the plan. It is not a carrier (persistent) and not a
load (one machine run, simultaneous processing). It is the "batch" of Allahverdi et al. (2008) and the "batch" of
the family scheduling model in Potts & Kovalyov (2000). "Family" means the given partition there (here: the step).

## 2. What the sources say (checked in Zotero, collection MA, 2026-11-17)

- **Potts & Kovalyov (2000)**, *Scheduling with batching: A review*, EJOR 120(2), 228–249,
  https://doi.org/10.1016/S0377-2217(99)00153-8, Zotero `26Z9YF55`. Printed page = 227 + PDF page (22 PDF pages).
  - Family scheduling model (p. 228). Jobs are partitioned into families. A job needs no setup if the previously
    processed job on the machine belongs to the same family. A setup is needed at the start and whenever the
    machine switches family. A **batch is a maximal set of jobs scheduled contiguously on a machine that share a
    setup**. This is option (a) below, and its batches are the slots of option (b).
  - **Batch availability** versus **job availability** ("item availability") (pp. 228–229). Under batch
    availability a job becomes available only when its whole batch is done. The example given is a pallet that
    leaves the machine only when all its jobs are processed. Under job availability a job is available as soon as
    it completes. Their default is job availability.
  - Setup notation (p. 229): $s_{ifg}$ is sequence-dependent and $s_{ig}$ sequence-independent. Setups are
    machine-independent if $s_{ifg} = s_{fg}$. The maximum batch size is $b_i$ (p. 230).
  - **Anticipatory** setups need no job to be present. **Non-anticipatory** setups cannot start before all jobs of
    the batch are released and done on the previous machine (p. 230).
  - Under batch availability, "jobs in a batch are processed sequentially, so that the processing time of a batch
    is equal to the sum of the processing times of its jobs" (§4.5, p. 238).
  - Shop problems with family setups: §4.3 (p. 236). Batch-availability and mixed-availability shops: p. 242.
  - **Worker as a setup source.** Fazle Baki and Vickson (multi-machine problems with a single operator) count the
    operator's moving between machines as a setup (p. 247; reported there, not read).
- **Allahverdi, Ng, Cheng & Kovalyov (2008)**, *A survey of scheduling problems with setup times or costs*, EJOR
  187(3), 985–1032, https://doi.org/10.1016/j.ejor.2006.06.060, Zotero `WVMP38QA`. Printed page = 984 + PDF page
  (48 PDF pages). Page mapping inferred from the page range **[uncertain]**.
  - Batch setup time (p. 987). Jobs are partitioned into families. A batch is a set of jobs of one family. Families
    are given, while "batch formation is a part of the decision making process". The group technology assumption
    (one batch per family) is a special case. Batch setups can be sequence-dependent or sequence-independent.
    Batch-availability and job-availability models are distinguished, and job availability is the default.
  - Terms (p. 988): "family" means the given partition and "batch" a part of the solution. The paper notes that
    many publications use "batch" for the partition. Setups are anticipatory unless there are release dates. No
    processing takes place during a setup. Notation: $ST_{si,b}$ / $ST_{sd,b}$ for sequence-independent and
    sequence-dependent batch (family) setup times.
  - Job shops with family setups (p. 1014), reported there and not read: Sotskov et al. (1999), $J/ST_{si,b}$,
    insertion techniques with beam search; Low et al. (2004), families of identical jobs with anticipatory,
    machine-dependent setups, disjunctive graph and integer programming.
- **Huertas & Van Hentenryck (2025)**, *Constraint programming models for serial batch scheduling with minimum
  batch size*, Operations Research Perspectives 15, 100352, https://doi.org/10.1016/j.orp.2025.100352, Zotero
  `V2UY34XA`. Pages below are PDF pages of the arXiv version (19 pages). Printed pages **[uncertain]**.
  - "In serial batch (s-batch) scheduling, jobs are grouped in batches and processed sequentially within their
    batch" (p. 1). Most of the literature considers maximum batch sizes (p. 2).
  - Their "Core" model sequences jobs with a no-overlap and a setup (transition) matrix. Consecutive jobs of a
    family form an s-batch, but the Core model "cannot guarantee" batch-size bounds (pp. 4–5). This is option (a)
    and its limit.
  - The Batching section adds batch interval variables. Each job is assigned to one batch, and a `span` constraint
    makes the batch interval cover its present jobs (p. 6). This is option (b).
  - Solver and scale: IBM CP Optimizer (sequence variables, transition matrices, `span`, `alwaysIn`) with a 1 h
    limit (p. 10). No model proves optimality on the instances with 50 and 100 jobs (p. 11). **CP-SAT has none of
    these globals**, so the CP-SAT mappings in §5 are own work.
- **OR-Tools CP-SAT** (documentation via Context7, `/google/or-tools`, 2026-11-17). Transition times in a
  no-overlap are modeled with `add_circuit`, using one arc literal per ordered pair of tasks on the resource plus
  reified precedences (sample `transitions_in_no_overlap_sample_sat.py`). There is no native transition-time
  no-overlap.

**Consequence.** (a) and (b) are not two different problems. A family-setup schedule with job availability *is* a
partition of each resource's sequence into contiguous batches (P&K p. 228). The real choices are (i) **batch or job
availability**, and (ii) **how the solvers represent the batch**: implicitly through the sequence (a) or as an
explicit object (b).

## 3. Facts from the repo that decide the design

1. **Definition of Done** (CLAUDE.md): format, checker, DES, a rule, CP-SAT and tests. The zero-disturbance test
   requires realized makespan = CP-SAT value. The user plans (2026-11-17): CP-SAT for the start plan and as the
   oracle (bound, gap), the GA for threshold and safety-net rescheduling, and GA against CP-SAT under the same
   budget. **The CP-SAT model must therefore value the same batches as the rule and the GA.** Otherwise the bound
   belongs to a different problem and the comparison is not fair.
2. **Shift limit** ([04](../../../math/04_workers.md) C13 with no share across the break; Fidentis §6 in the main
   checkout): a whole share fits one part of the shift, at most 270 minutes (13:00–17:30) without overtime. A
   full DATA_PREP_PRIMARY batch takes $15 + 15 \cdot 20 = 315 > 270$. **If a batch is one share, maxBatch 20 is
   never reached**: 17 parts ($15 + 255 = 270$) is the real limit, and in the morning part (08:00–12:00, 240) it
   is 15. With overtime the afternoon part may run to 19:30, which allows more.
3. **Workers.** Most s-batch steps are worker-only ($M_o = \emptyset$, whole share) or run on the stand-in pool
   `hand` with a whole share. CP-SAT gives each share an optional interval per qualified worker and one
   `add_no_overlap` per worker, which also holds the night, overtime and break intervals
   ([12](../../../math/12_cp-sat.md) §7a, §7b).
4. **Existing batch code** keys a batch by `(machine, planned start)` (`sim/des.py` `planned_batches`, checker C10,
   greedy join in the rules, CP-SAT slots in [03](../../../math/03_carriers.md) step 3). For worker-only steps the
   machine is `None`, so this key would merge unrelated operations. The 03 §6 todo "batches only within one step"
   **becomes blocking**: the key needs the step.
5. **Capacity unit.** The MES counts parts (20 primary parts), not operations. A member is an order or part
   operation covering $n_o$ parts (e.g. all primary parts of one order). Operations per part are not modeled
   ([32](../../../math/32_target-data-model.md) §2), so one order's operation is never split across batches. An
   order with $n_o > c_s$ needs a validation rule (§4.1).
6. **Volume.** At about one order per nesting day (Fidentis §6, print setup note), batches across orders form only
   when several orders wait for the same step at the same time. That happens mainly from a backlog or after a
   disturbance. The gain should be measured, not assumed.

## 4. Options

Common notation for all options (proposed, see §8): step $s(o)$ of operation $o$; setup $p^{\mathrm{su}}_s$ of step
$s$; per-unit time of $o$, so that $p_o = n_o \cdot p^{\mathrm{unit}}_{s(o)}$ without setup; units $n_o$ of $o$; and
capacity $c_s$ in units. $c_s$ generalizes the existing batch capacity of a carrier step, where a carrier counts as
one unit.

### (a) Family setups: the setup depends on the predecessor on the same resource

An operation of step $s$ pays $p^{\mathrm{su}}_s$ unless the share directly before it on the same worker (or
machine) is of the same step $s$. Job availability holds: each operation ends on its own.

- **Format.** The step gets `setup` and `capacity`. The operation stores only its time without setup, and the
  compiled duration depends on the plan. Schema bump.
- **Checker.** Per resource, sort its intervals. For each $o$: $C_o - S_o = p_o + p^{\mathrm{su}}_s \cdot [\text{predecessor on the resource is not of step } s]$.
  A capacity counter along each run of same-step operations, so that a run has at most $c_s$ units. Open: does a
  gap reset the setup (idle time, a break, the night, an operation of another step in between)? Without a reset
  rule a worker could keep a setup overnight.
- **DES.** The duration of $o$ is known only once its predecessor on the resource is known. That is fine for the
  planned predecessor. If repair or a delay swaps the order, the realized duration changes. The DES has to
  recompute the setup from the realized predecessor.
- **Rule.** List scheduling with the setup in the duration estimate, plus a family bonus: among ready operations,
  prefer one of the step the chosen worker did last. Simple, but myopic.
- **CP-SAT.** The no-overlap has no transition, so this needs `add_circuit` per worker. The circuit covers *all*
  optional shares that worker can take, because "the predecessor" can be of any step. That is about $n_z^2$ arc
  literals per worker plus reified precedences, and it interacts with the night and break intervals in the same
  sequence. Estimate for 40 Fidentis orders with about 20 whole shares each and 2 workers: $n_z \approx 800$ per
  worker, so about $1.3 \cdot 10^6$ arcs. **Not workable** (own estimate, not measured). A cheaper exact variant
  does not exist, because the setup depends on the immediate predecessor. Capacity needs an extra counter along
  the circuit (Huertas & Van Hentenryck: the Core model alone cannot bound batch sizes).
- **GA.** Natural. The decoder computes the setup from the previous share on the worker, and the permutation finds
  the grouping. No extra genes.
- **Shift limit.** Each member is its own share and fits a shift part by itself, so a batch may span the break. This
  is realistic only if the setup survives the break (open question).

### (b) Explicit s-batches: slots like the oven p-batch, but serial

The planner forms batches. A batch $j$ of step $s$ occupies one resource from $S^{\mathrm{slot}}_j$ to
$C^{\mathrm{slot}}_j = S^{\mathrm{slot}}_j + p^{\mathrm{su}}_s + \sum_o y_{o,j}\, p_o$, as **one whole worker
share**. Two variants:

- **(b1) batch availability.** Every member gets $S_o = S^{\mathrm{slot}}_j$ and $C_o = C^{\mathrm{slot}}_j$ (P&K
  §4.5, p. 238). This is the oven pattern with a variable duration.
- **(b2) job availability inside the slot.** Members get their own consecutive intervals inside the slot (the
  `span` of Huertas & Van Hentenryck, p. 6). This is exact for (a) restricted to contiguous batches.

Details:

- **Format.** Step-level `setup` $p^{\mathrm{su}}_s$ and `capacity` $c_s$ (units) for order or part steps (route
  operations of one id across orders) and for carrier steps without runs. `Operation.step` (new, needed by item 4
  of §3). `Assignment.batch` (new, optional id): needed because worker-only members have `machine = None`, and
  explicit beats keying by `(worker, step, start)`. Schema bump. Validation, one negative test each:
  $p^{\mathrm{su}}_s \ge 0$; $c_s \ge 1$; $n_o \le c_s$ for every member; with a calendar,
  $p^{\mathrm{su}}_s + p_o \le$ the longest shift part (otherwise not even a singleton batch fits); setup only
  on steps with a whole share or a machine; no setup on run or oven steps.
- **Checker (new C15, proposed).** Operations with the same `batch` id share step, resource and worker. Their units
  sum to at most $c_s$. The batch interval is $[S, S + p^{\mathrm{su}}_s + \sum p_o)$. (b1): every member carries
  exactly that interval. (b2): members lie consecutively inside it, with the setup at the start. C12/C13 see one
  share. An operation without a batch id is a singleton and pays the setup. That is today's `base_durations`, so
  the change is backward compatible. Anticipatory or not: proposed **non-anticipatory** (the setup starts only when
  all members are ready; P&K p. 230). Fidentis data preparation needs the data of all members, so the setup cannot
  start earlier [own assumption].
- **DES.** Reuse the oven logic: a batch starts when all members are released and ready and the worker is free, and
  the largest late start offset of its members delays it. Realized duration
  $= \operatorname{round}(\varepsilon^{\mathrm{su}}\, p^{\mathrm{su}}_s) + \sum_o \operatorname{round}(\varepsilon_o\, p_o)$, where
  the setup factor is the factor of the member with the smallest index [own; no extra scenario stream needed]. A
  started batch is frozen as a whole. A member that arrives later cannot join a running batch. (b1): all members
  end together. (b2): each member ends at its own realized time.
- **Rule.** Greedy join as for the oven: when an operation of step $s$ is chosen at $t$ for worker $z$, the
  operations of $s$ ready by $t$ join in sequencing order while units $\le c_s$ and the batch still fits the
  current shift part. No waiting to fill.
- **Repair.** A batch moves as one (as for the oven).
- **CP-SAT.** Reuse the slots of [03](../../../math/03_carriers.md) step 3, per step $s$ (not per duration family,
  which fixes the 03 todo):
  $$\sum_{j \le i(o)} y_{o,j} = 1,\quad \sum_o y_{o,j}\, n_o \le c_s\, u_j,\quad u_j \ge u_{j+1},\quad C^{\mathrm{slot}}_j - S^{\mathrm{slot}}_j = p^{\mathrm{su}}_s\, u_j + \sum_o y_{o,j}\, p_o$$
  (b1): $y_{o,j} \Rightarrow S_o = S^{\mathrm{slot}}_j \wedge C_o = C^{\mathrm{slot}}_j$. (b2): members keep their
  own intervals, add $y_{o,j} \Rightarrow S^{\mathrm{slot}}_j + p^{\mathrm{su}}_s \le S_o,\ C_o \le C^{\mathrm{slot}}_j$,
  and the members' intervals in a no-overlap (they already are, on the worker). The worker share is the slot
  interval: optional per qualified worker with presence $v_{j,z}$, $\sum_z v_{j,z} = u_j$
  ([12](../../../math/12_cp-sat.md) §7a "batch shares per slot"). C13 then caps the slot length by itself. Size
  for step $s$ with $n_s$ candidate operations: $n_s$ slots, $n_s(n_s+1)/2$ literals $y$, and $n_s |W_s|$
  optional intervals. For 40 orders and about 6 s-batch steps: $6 \cdot 820 \approx 5000$ literals $y$ and
  $6 \cdot 80 = 480$ optional intervals. That is a modest addition to today's model (own estimate, not measured).
  Bound quality: Huertas & Van Hentenryck prove no optimality at 50 or more jobs with CP Optimizer. Expect weak
  bounds, which matters for the oracle role. Tighten by capping the number of slots per step at
  $\lceil \sum n_o / \min(c_s, \text{shift cap}) \rceil$ plus slack **[uncertain: the slack must not cut off the
  optimum; needs a proof or a test]**.
- **GA.** The grouping is not in the permutation. Either the decoder forms batches greedily (same rule as above),
  or a gene per operation "join the previous batch of my step". The decoder approach is simpler and matches the
  rule. It loses batchings that require waiting.
- **Shift limit.** The slot is one share, so it must fit a shift part. With 15/15 per part that is at most 17
  primary parts in the afternoon and 15 in the morning. Splitting over the break pays a second setup (two
  batches). Whether that is right is an open question.

### (c) Grouping by the dispatching rule only

The format gets setup and capacity, the rule groups as in (b), and CP-SAT keeps the full setup per operation.

- Checker and DES as in (b). The rule is the same as in (b).
- **CP-SAT cannot value the grouping.** Its plan pays every setup (pessimistic). Its bound is a bound of the
  no-batch problem, not of the batched one. Zero-disturbance "realized = CP-SAT value" no longer covers the batch
  feature, and GA against CP-SAT is no longer fair (§3 item 1). **Fails the Definition of Done item 5.** A CP-SAT
  model with no setup at all would give a valid lower bound but infeasible plans.
- Keep (c) only as the **decoder heuristic** of (b) (rule and GA), not as a model.

## 5. Comparison

| | (a) family setups | (b1) slots, batch avail. | (b2) slots, job avail. | (c) rule only |
|---|---|---|---|---|
| Format | setup, capacity; plan-dependent duration | setup, capacity, `Operation.step`, `Assignment.batch` | same as (b1) | as (b1) |
| Checker | per-resource sequence, reset rule, capacity counter | C15: batch interval, units, one share | C15 + members inside, consecutive | as (b1) |
| DES | duration recomputed from the realized predecessor | oven logic, variable duration | oven start, members end separately | as (b1) |
| Rule | family bonus | greedy join | greedy join | greedy join |
| CP-SAT | circuit over all shares of a worker, ~$10^6$ arcs at 40 orders | slots per step, ~5000 literals | (b1) + 2 reified constraints per $y$ | full setup; wrong bound |
| GA | natural (decoder) | decoder join or join gene | same as (b1) | as (b1) |
| Shift (270) | per member; batch spans break | batch ≤ one shift part | batch ≤ one shift part | as (b1) |
| DoD | yes, but CP-SAT size | yes | yes | no |

## 6. Recommendation

**(b), explicit s-batches as CP-SAT slots per step, one whole worker share per batch, non-anticipatory setup, greedy
join in the rule and the GA decoder.** Start with **(b1) batch availability** unless the user says that members
leave the step one by one *and* a successor can use that (§9 Q1). In that case use (b2). It costs two reified
constraints per $y$ and nothing else in the format.

Reasons: (b) meets the Definition of Done with a CP-SAT model of moderate size. It reuses the oven slots, the DES
joint start and the batch repair. The shift limit falls out of C13 without a new constraint. It makes CP-SAT, the
rule and the GA value the same batches, which the planned GA against CP-SAT comparison needs. (a) is more general
(batches span breaks and other work) but is not tractable in CP-SAT at the Fidentis size. (c) fails the oracle role.

**Migration tests** (proposed): with every batch of size 1 the instance reproduces today's `base_durations` times
exactly (same CP-SAT optimum as before on the Fidentis file). A full batch reproduces the MES formula
$\mathrm{base} + \mathrm{per\_unit} \cdot u$ for $u$ units. Hand case: three orders of 4 primary parts, setup 15,
15 per part, one worker, $c_s = 20$: one batch $15 + 180 = 195$ against $3 \cdot 75 = 225$ singletons. Plus the
zero-disturbance test, the checker on all plans, and one negative test per C15 rule and per validation rule.

**Prerequisite:** step per operation in `CompiledInstance` and batch grouping by step (the 03 §6 todo), and the
batch key leaves `(machine, start)`. The existing oven tests must stay green.

## 7. Implementation order (after approval; one step at a time, tests each)

1. `Operation.step` and the compiled step; oven grouping by step (03 todo); negative test.
2. Format: step `setup` and `capacity`, `Assignment.batch`, validation, schema bump. Generator: `base_durations`
   split into setup and per unit for steps marked as s-batch.
3. Checker C15 (b1), hand case, negative tests.
4. DES and repair (oven logic, variable duration, setup factor).
5. Rule: greedy join with units and shift fit.
6. CP-SAT slots per step, worker share per slot. Hand optimum, zero-disturbance, migration tests.
7. `math/`: new component file (e.g. `08_serial-batches.md`), notation, references, terminology, protocol.
8. Measure on the Fidentis case: setups saved, makespan and tardiness, CP-SAT gap with and without s-batches.

## 8. Proposed symbols (for `math/notation.md`, not added yet)

Checked against `math/notation.md`, 03 and 12 on 2026-11-17. The main checkout's uncommitted `notation.md` must be
checked again before adding them.

| Symbol | Meaning | Why this letter |
|---|---|---|
| $s(o)$ | step of operation $o$ | extends the carrier step index $s$ to all steps; like $k(o)$, $m(o)$ |
| $c_s$ | batch capacity of step $s$, in units (carriers count 1) | existing symbol, same quantity, now also for order and part steps |
| $p^{\mathrm{su}}_s$ | setup time once per s-batch of step $s$ | a duration, family $p$ like $p^{\mathrm{br}}$; not $s$ (step) |
| $p^{\mathrm{unit}}_s$ | time per unit of step $s$ | family $p$ |
| $n_o$ | units of operation $o$ (parts it covers) | count family $n$ like $n_k$ |
| $C^{\mathrm{slot}}_j$ | end of slot $j$ | completion family, like $S^{\mathrm{slot}}_j$ |
| $v_{j,z}$ | worker $z$ serves slot $j$ | existing $v_{\eta,z}$ with the slot's share |
| $\varepsilon^{\mathrm{su}}$ | disturbance factor of a batch setup | variant of $\varepsilon_o$ |

Not used: $F$ (03 slot family, flow time $\bar F$), $f$ (objective), $s$ for setup (step index), $b$ (carrier).

## 9. Open questions for the user

1. **Availability.** In DATA_PREP_PRIMARY (and polishing, sawing, grinding, inspection), does a part go to the next
   step as soon as it is done, or does the batch move on together? Is there a successor that would start earlier
   under job availability? This decides (b1) against (b2).
2. **Setup across a break.** May a batch continue after the lunch break or the next morning without a new setup?
   If yes, the one-share-per-batch form is too strict, and the step needs a batch of several shares (no model for
   that yet).
3. **maxBatch against the shift.** 20 primary parts take 315 minutes, more than one shift part (270). Is the real
   batch smaller, the per-part time lower, or is a batch split over the break with one setup (back to Q2)?
4. **Which steps** are s-batch steps, with setup and capacity each? Candidates: DATA_PREP_PRIMARY (15, 20 parts),
   polishing, sawing, grinding, inspection. Are the MES numbers per batch or already amortized?
5. **Mixed orders and steps.** May one batch hold operations of different route steps that share a setup (e.g. two
   polishing kinds)? The proposal says no: one step per batch, sequence-independent setup.
6. **Same worker.** Must one worker do the whole batch? The proposal says yes, one share.
7. **Planner freedom.** May the planner *delay* a ready operation to fill a batch? CP-SAT may; the greedy rule and
   decoder do not. Acceptable as a difference between rule and optimizer?
8. **Nesting volume.** At about one order per nesting day, cross-order batches are rare. Is the expected volume in
   the experiments higher (backlog scenarios)? Otherwise the feature changes little in the results.
9. **Unlisted rule matches** (§0): should PART_CLEANING, QM and recheck (REWORK_CHECKOUT), and inspection,
   documentation and packaging also be s-batch steps? They match the rule (per-unit time > 0, maxBatch > 1).

Answered 2026-11-17: Q1 (batch moves together), Q2 (no), Q3 (smaller), capacity (none; the share limits it),
Q4 (the step list in §0). Still open: setup values of the carrier steps as exact per-batch values (MES seed or
corrected), Q5–Q9.

**Mill prep secondary** (asked 2026-11-17, as configured in `data/generator/fidentis.json`): MILL_PREP_SECONDARY,
MILL_JOB_SECONDARY and SECONDARY_PLATE_REMOVAL are one per-carrier run `mill_carrier` on the mill. Setup 15
(attended, whole worker share), main $30 \cdot$ telescopes (unattended), removal 5 (attended). Every plate is its
own run (user 2026-11-03: one carrier at a time on the mill), and the mill is blocked from setup to removal (C9).
The MES seeds MILL_PREP_SECONDARY with maxBatch 4 and MILL_JOB_SECONDARY with maxBatch 2. So in the MES the 15 of
the prep could be shared by up to 4 plates (and a job by 2 parts). The model does not do that: 15 per plate. It is
not an s-batch in the user's rule (per-unit time 0). Sharing it would be a mill run with several plates, i.e. a
run over several carriers like the print, not an s-batch.

## 10. Proposed protocol entry (to add with the first implementation step; not added now)

> **2026-11-17 s-batches across orders: design.** Decided: nothing yet (proposal, user to decide §9). Done: spec
> `docs/superpowers/specs/2026-11-17-s-batches-design.md` comparing family setups, serial slots and rule-only
> grouping. Sources checked in Zotero: P&K 2000 `26Z9YF55` pp. 228–230, 238; Allahverdi et al. 2008 `WVMP38QA`
> pp. 987–988, 1014; Huertas & Van Hentenryck 2025 `V2UY34XA` PDF pp. 1–6, 10–11. Found: CP-SAT has no
> transition-time no-overlap (circuit only); (a) does not scale at Fidentis size; (c) fails DoD item 5; maxBatch
> 20 of DATA_PREP_PRIMARY does not fit one shift part. Open: §9 Q1–Q8; references.md entries for `WVMP38QA` and
> `V2UY34XA`.
