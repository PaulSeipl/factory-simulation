# 08 Serial batches across orders (s-batches)

**Status:** all 8 steps of the spec (`docs/superpowers/specs/2026-11-17-s-batches-design.md` §7) done: batches only within one step (step 1, [03](03_carriers.md) §6), the instance format with validation V23, `Assignment.batch`, generator pass-through (step 2), checker C15 (step 3), DES, snapshot, repair and the frozen part of rule and CP-SAT (step 4), the rule forms batches (step 5), CP-SAT forms batches (step 6), this file and the notes (step 7), the Fidentis case with s-batch steps and a first measurement (step 8, §7a). Open: CP-SAT model size (§6).

## 7a. First measurement on the Fidentis case (step 8, 2026-11-19)

Notebook `notebooks/08_s_batches_and_forecast.ipynb` (built by `notebooks/build_08_s_batches_and_forecast.py`): 10 orders, seed 1, the case with and without `s_batch_steps`, the rule (SPT + ECT) and CP-SAT (makespan, 60 s on 12 threads, hinted with the rule plan; results stored in `notebooks/results/08/`).

| s-batches | planner | makespan | worker minutes | batches (members) | setup minutes saved | CP-SAT bound |
|---|---|---|---|---|---|---|
| without | rule | 30790 | 8830 | 0 | 0 | |
| without | CP-SAT | 23080 | 8830 | 0 | 0 | 14353 |
| with | rule | 30730 | 8155 | 38 (99) | 675 | |
| with | CP-SAT | 24700 | 8450 | 23 (59) | 420 | 13814 |
| with | CP-SAT, horizon capped and batches hinted (2026-11-19) | 24500 | 8365 | 25 (68) | 465 | 13816 |

The rule saves 675 setup minutes, 8 % of the worker time; the makespan hardly moves, since the single mill is the bottleneck (about 1268 minutes per order) and s-batches save worker time only. CP-SAT is worse with s-batches in the same budget (24700 against 23080; one thread with deterministic limit 60: 26020 against 22055; 180 s: 26160 against 22171) and forms fewer batches than the rule: the slots (106 s-batch operations, 562 slot literals) enlarge the model more than the batches help the search. Both bounds (about 14000) are close to the mill's pure processing time (13732 minutes), so the gap to the best plans is mostly the bound, which does not see that the mill's attended setups and removals wait for the shift [own assessment]. No tardiness in either variant (due dates 10 working days).

## 1. Prose description

Several manual steps of the dental factory (data preparation of the primary parts, polishing, finishing, support removal, grinding, steam cleaning, inspection, documentation, packing, cleaning and sand blasting of plates) take a time once per batch plus a time per unit. The MES counts the time once per batch (user 2026-11-17). A worker who prepares the data of three orders at once pays the setup once, not three times. The orders of one batch are chosen by the planner, across orders (or across carriers for cleaning and blasting). That is a serial batch (s-batch): the members are processed one after another by one worker, with one setup per batch (Potts & Kovalyov 2000, p. 230). It differs from the oven run, a parallel batch (p-batch, [03](03_carriers.md) C10), whose members are processed at the same time on one machine.

Within one order the model already pays the setup once: an order or part operation covers all parts of its type and carries its setup once (`base_durations`, [21](21_instance-generator.md)). What s-batches add is the saving across orders.

Decisions of the user (2026-11-17, spec §0):
- the batch moves on together (batch availability, form (b1));
- a batch is one whole worker share and does not continue across the break or the night with the same setup;
- the order and part steps have no capacity of their own (the shift limits the batch); `clean` and `blast` take at most 4 plates (user 2026-11-18).

## 2. Sets, parameters, variables

See [notation.md](notation.md). Reused: step $s(o)$ of operation $o$, setup $p^{\mathrm{su}}_s$ of step $s$ (so far the base of a run step), capacity $c_s$ (so far the p-batch capacity of a carrier step; for an s-batch step the units per batch; none: no limit). New: units $n_o$ of an operation (user 2026-11-18: count parts): a part operation covers the order's parts of its type, an order operation counts 1 (the order), a carrier operation 1 (the carrier: the 4-plate limit of `clean` and `blast`). These are the factors the generator multiplies the per-unit time with (`count` in `carrier_generator.py`), so units and durations agree. An s-batch step is a step $s$ listed in `Instance.s_batch_steps` (no set symbol: $S$ is the start-time family). A batch $j$ (in a plan: the operations with one `Assignment.batch` id) has the members $O_j \subseteq O$, the start $S^{\mathrm{slot}}_j$ and the end $C^{\mathrm{slot}}_j$ (the slot symbols of [03](03_carriers.md), whose used slot is a batch; not $B$: the carriers $\mathcal{B}$). It holds $\sum_{o \in O_j} n_o \le c_s$.

**Durations.** The duration $p_{o,m}$ of an operation of an s-batch step (on machine $m$, or $p_o$ without machine) is its singleton time and **contains** the setup. A batch $j$ of step $s$ on machine $m$ therefore lasts

$$C^{\mathrm{slot}}_j - S^{\mathrm{slot}}_j = p^{\mathrm{su}}_s + \sum_{o \in O_j} \left(p_{o,m} - p^{\mathrm{su}}_s\right)$$

and a singleton $O_j = \{o\}$ lasts $p_{o,m}$, as today. Deviation from the spec (§4 (b), which stores the time without setup per operation): with the setup inside, no existing instance, generator output or planner changes until a planner forms batches, and the migration test "every batch a singleton reproduces today's times" holds by construction.

## 3. Constraints

(C15) s-batches: the members of a batch $j$ are operations of one s-batch step $s$, on one machine $m$ (or all without), with the same workers; they all start and end with the batch (batch availability, Potts & Kovalyov 2000, §4.5):
$$S_o = S^{\mathrm{slot}}_j,\quad C_o = C^{\mathrm{slot}}_j = S^{\mathrm{slot}}_j + p^{\mathrm{su}}_s + \sum_{o' \in O_j} \left(p_{o',m} - p^{\mathrm{su}}_s\right) \qquad \forall o \in O_j$$
$$\sum_{o \in O_j} n_o \le c_s \quad \text{(if } s \text{ has a capacity)}$$
A batch id on an operation of another step is a violation. The batch is one interval: it occupies its machine once (C5) and its worker once (one share, C12–C13); an operation of an s-batch step without batch id is a singleton and lasts $p_{o,m}$ (C2). C2 is not checked for members, their length is the batch's. **Non-anticipatory setup** follows without a constraint of its own: every member starts at $S^{\mathrm{slot}}_j$ and is bound by its predecessors and release (C3, C4), so the setup starts only once all members are ready.

The instance rule:

(V23) An s-batch step $s$ is a step of the instance (an order or part step, or a carrier step without runs and without p-batch); each of its operations has one whole worker share (with or without machine) or a machine and no worker, never a prefix or suffix share (unattended time inside the batch would make it a run); with a capacity, no operation covers more units than it, $n_o \le c_s$; its setup is shorter than every duration (on every machine option), $p^{\mathrm{su}}_s < p_{o,m}$; and with a worker and a calendar every operation fits, on at least one machine, the longest share that C13 and C14 allow on one day:
$$p_o \le \max\left(h^{\mathrm{B}+} - h^{\mathrm{S}},\ h^{\mathrm{E}} + \overline{\mathrm{ot}} - \min\left(h^{\mathrm{B}+},\, h^{\mathrm{B}-} + p^{\mathrm{br}}\right)\right)$$
(before the latest break start; or from the earliest possible end of the break to the end of overtime, since a share starting at the latest break start needs no break). For the default calendar that is $\max(300, 390) = 390$ minutes. Calendar symbols from [notation.md](notation.md) ([04](04_workers.md)).

## 4. Objective function

Unchanged.

## 5. Implementation in code

- `SBatchStep(setup, capacity=None)` and `Instance.s_batch_steps` (step → `SBatchStep`, `src/simulation/model/instance.py`), left out of the dump when empty, so instance files and digests from before stay unchanged; `capacity` $\ge 2$, left out when unset. Schema 0.8 regenerated (0.8 is not released).
- V23 in `Instance._check_s_batch_steps`; `longest_share(cal)`.
- `Assignment.batch` (`src/simulation/model/schedule.py`): optional batch id, the same for all members of one batch; left out when None. Explicit rather than keyed by `(step, worker, start)`, because two batches of one step may run at the same time on two workers. No planner sets it yet.
- Generator: `CarrierGeneratorParams.s_batch_steps`, passed to the instance (and through `model_dump` to the arrival generator); unknown steps rejected; omitted at its default (config hashes unchanged). The Fidentis configuration does not use it yet (it would change its digests without any effect before step 6).
- Tests: `tests/test_s_batch_format.py` (accepted order and carrier steps; omitted defaults; longest share by hand; one negative test per V23 rule and per field constraint; generator pass-through and unknown step).
- **Compilation** (step 3): `CompiledInstance.s_setup` ($p^{\mathrm{su}}_s$ per operation, None for other steps), `s_capacity` ($c_s$), `units` ($n_o$ via `instance.units`).
- **Batch length and key** (step 4, `model/compiled.py`): `s_batch_length(ci, ops, machine)` (setup once plus each member without it; used by checker, DES, snapshot, repair); `batch_key(ci, o, x)` (a p-batch by step, machine and time, an s-batch by id; used for the frozen part of rule and CP-SAT).
- **DES and repair** (step 4): `SimState.batch_id`; `planned_batches` groups not started members by id; members get the realized batch length and one share ([13](13_des.md) §3); `_planned_duration` is the batch's (OVERDUE, shift fit); `current_plan()`, `realized()` and the snapshot (`FrozenOperation.batch`, expected end = start + batch length) carry the id; C7 compares it. The rule and CP-SAT keep a frozen batch once (worker and machine) and its id; `shift_repair` moves a batch as one with its length (`planned_durations`, also for the calendar fit). The batch length is reported as C2 (like any duration; skipped for a started batch). Tests `tests/test_s_batch_des.py` (10): zero-disturbance; realized length by hand (factor 2 on O1: $10 + 50 + 25$); a late member delays the batch; the batch waits for its members; snapshot mid-batch; replanning during the batch with repair, the rule and CP-SAT (six replans at 10…60 all accepted); a machine-bound batch; with the default calendar a batch of 55 ready at 640 waits for Tuesday 08:00 although one member (30) would fit. Mutation-checked: without the batch id in the snapshot four tests fail.
- **CP-SAT** (step 6, `planners/cpsat.py` `_s_batch_slots`): slots per step with variable length, one share set per slot, capacity in units ([12](12_cp-sat.md) §3). Tests `tests/test_s_batch_cpsat.py` (8), each optimal, feasible and zero-disturbance (realized = plan, makespan = CP-SAT value): hand optimum 81 with bound 81; capacity 3: 86 without batch; on two tools 81 on one tool; three plates (polishings ready at 6, 11, 16, setup 9) optimum 117 proven, by hand: O1 alone, then O2 + O3 $[46, 97)$; waiting for all three gives 118, all alone 126; the rule finds 117 too; with the default calendar; rescheduling every minute from the singleton plan forms the batch (3 disturbances). Mutation-checked: without the slots 6 of 8 fail.
- **Rule** (step 5, `planners/dispatching.py`): greedy join by step, units and shift fit; batch id = the first member's key ([11](11_dispatching-rules.md) §3). Tests `tests/test_s_batch_rule.py` (21): every rule combination forms the hand batch $[6, 61)$, makespan 81 against 86, feasible and zero-disturbance; capacity 3 keeps them apart (86); with $t = 0$ at Monday 16:44 the batch (55) would end after the shift and is not formed, singletons are; on two tools joint selection batches, ECT does not; rescheduling every minute from the rule's start plan (3 disturbances) keeps one batch id, feasible up to C2. Mutation-checked: without the join 19 of 21 fail.
- **Checker C15** (step 3, `check/feasibility.py`): `s_batch_violations` groups the assignments by batch id and checks step, machine, workers, starts and ends, the batch length and the units. C2 skips members; `machine_overlaps` adds one interval per batch and machine; `worker_intervals` counts a batch's share once (C12, C13). Tests `tests/test_s_batch_checker.py` on the tiny instance (two orders on one plate, 3 primary parts each, polishing 30 with setup 5): hand batch of both polishings $[6, 61) = 5 + 25 + 25$, makespan 81 against 86 with singletons, feasible; singletons without id and a singleton batch feasible; different ends, wrong length (54 against 55), a batch id on `pack`, different workers, 6 units against capacity 3 and two machines are C15; a pack inside the batch is C12; on a machine (2 polishing tools) the batch is one interval. Mutation-checked: without the single worker share or the single machine interval the tests fail.

## 6. Assumptions and open points

- **CP-SAT model size** (step 8): one slot per candidate operation and step ($n$ slots, $n(n+1)/2$ literals $y$ per family) makes CP-SAT worse on the Fidentis case than without s-batches (§7a). To try: a bound on the slots per step (spec §4 (b), **[uncertain]**: must not cut off the optimum), hinting the rule's batches (slot $y$ literals), or leaving batch forming to the GA decoder (spec §4 (b)). Huertas & Van Hentenryck (2025, `V2UY34XA`) report weak bounds for CP models of s-batching at larger sizes **[uncertain: page not rechecked]**.
- **Rule: batch at most one shift part** (2026-11-19, found on the Fidentis case): the rule plans no overtime, so a mate joins only while the batch fits the longer shift part (270 minutes in the default calendar); before, `free_from` raised for a longer batch share. Test `test_a_batch_longer_than_a_shift_part_is_not_formed`.

- **Machines allowed** (user 2026-11-18): all 12 free s-batch steps of the Fidentis route are worker-only, but a tool may later be tracked as a machine. Steps 3–6 therefore cover a batch on one machine as well: all members on the same machine, the batch interval occupies it (the oven slots' machine choice reused). The setup is per step, the durations per machine option.
- **Units in parts** (user 2026-11-18, instead of members): no step of the Fidentis case limits parts yet (only `clean` and `blast` have a capacity, in plates). An order operation counts 1, not all parts of the order, because its duration is per order ("10 + 10 per order"). An operation covers all its parts, so one order's operation is never split across batches; V23 rejects $n_o > c_s$.
- **Non-anticipatory setup** (spec §4 (b)): the setup starts only when all members are ready [own assumption]; follows from batch availability with C3 and C4 (§3). Fidentis data preparation needs the data of all members.
- **Setup factor** (DES): the setup scales with the factor of the member with the smallest index [own; spec §4 (b)], so it varies with the batch's composition. No scenario stream of its own.
- **Batch ids across replans**: a planner that forms batches (step 5, 6) must not reuse the id of a started batch for other operations, or C15 merges them.
- **Rule: no waiting, machine before batching** ([11](11_dispatching-rules.md) §3): the greedy join takes only operations ready by $t$ (a batch that pays off by waiting a few minutes is missed: CP-SAT may wait, the rule not, spec §9 Q7), and with an assignment rule the machine is fixed before batching, so operations spread over two machines cannot join.
- **Which steps** are s-batch steps in the experiments, and with which setup: spec §0 (second round). The Fidentis configuration gets them when the planners form batches.

## 7. Sources

- Potts, C. N., & Kovalyov, M. Y. (2000). Scheduling with batching: A review. *European Journal of Operational Research*, 120(2), 228–249. https://doi.org/10.1016/S0377-2217(99)00153-8 (Zotero `26Z9YF55`; s-batch and p-batch pp. 228–230, batch availability p. 238; checked in the spec pass 2026-11-17).
- Fowler, J. W., & Mönch, L. (2022). A survey of scheduling with parallel batch (p-batch) processing. *EJOR*, 298(1), 1–24. https://doi.org/10.1016/j.ejor.2021.06.012 (Zotero `H6SPCTKI`; distinguishes serial batching (s-batch: jobs of one family run consecutively after one setup) from parallel batching, PDF p. 1; checked 2026-11-18).
- Huertas, J. A., & Van Hentenryck, P. (2025). Constraint programming models for serial batch scheduling with minimum batch size. *Operations Research Perspectives*, 15, 100352. https://doi.org/10.1016/j.orp.2025.100352 (Zotero `V2UY34XA`; s-batch: jobs grouped in batches and processed sequentially within their batch, PDF p. 1; CP models with interval variables, the basis of the CP-SAT slots of step 6).
- Allahverdi, A., et al. (2008). A survey of scheduling problems with setup times or costs. *EJOR*, 187(3), 985–1032. https://doi.org/10.1016/j.ejor.2006.06.060 (Zotero `WVMP38QA`; batch sequence-independent setup times, §3.3, PDF p. 9; anticipatory vs. non-anticipatory setups, PDF p. 4).
- The form (one whole share per batch, setup inside the singleton duration, V23) is own modeling.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-18 | uncommitted | Step 1: batches only within one step ([03](03_carriers.md) §6). |
| 2026-11-18 | uncommitted | Step 2: file created; `Instance.s_batch_steps`, V23, `Assignment.batch`, generator pass-through; schema 0.8 regenerated. |
| 2026-11-18 | uncommitted | Step 2 decisions: machines allowed; capacity in units $n_o$ (parts). Step 3: C15 in the checker; batch symbols $O_j$, $S^{\mathrm{slot}}_j$, $C^{\mathrm{slot}}_j$ instead of $B$. |
| 2026-11-19 | uncommitted | Step 8: Fidentis case with s-batch steps, first measurement (§7a), notebook 08; rule batch limited to one shift part. |
| 2026-11-18 | uncommitted | Step 6: CP-SAT forms s-batches (slots with variable length). |
| 2026-11-18 | uncommitted | Step 5: the rule forms s-batches (greedy join). |
| 2026-11-18 | uncommitted | Step 4: DES, snapshot, repair, frozen part of rule and CP-SAT; batch length reported as C2; sources Fowler & Mönch, Huertas & Van Hentenryck, Allahverdi et al. added. |
