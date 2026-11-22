# 14 Genetic algorithm (BRKGA)

Status: steps 1–4 of the GA plan done (protocol (77), (78), (80)): random keys for priority, machine, delay and
overtime, the BRKGA loop (step 1, 2), the rescheduling planner with snapshot, warm start, change budget and time
limit (step 3, §3b), NSGA-II as an offline trade-off analysis over the same keys (step 4, §3a). Not yet run on the
Fidentis case (experiments).

## 1. Prose description

The GA is the primary solver of the thesis. It searches over **instructions for a schedule builder**, not over
schedules. A chromosome is a vector of numbers in $[0, 1)$, called random keys (Bean, 1994). A **decoder** turns
every such vector into a feasible plan. The decoder is the dispatcher of [11](11_dispatching-rules.md), which
already respects every constraint of the model: precedence, runs, p- and s-batches, workers, shifts and breaks.
So the genetic operators only mix numbers and never produce an infeasible plan. Bean (1994, p. 154) introduces
random keys for this reason: they guarantee "feasibility of all offspring without creating additional overhead".

Per operation $o$ the chromosome holds four keys:

- a **priority key**: when the decoder chooses among candidates, the smaller key wins;
- a **machine key**: which machine of $M_o$ the operation uses (no effect if $|M_o| = 1$, as on the Fidentis case;
  kept for flexible instances and for future machine set-ups, user 2026-11-19);
- a **delay key**: how far scheduling iteration $\zeta$ may look past the earliest possible start;
- an **overtime key**: how many minutes past shift end the operation's worker shares may run (up to the maximum
  overtime of the calendar).

The keys are independent. The delay key belongs to an iteration of the decoder, not to an operation: key $\zeta$
says how far iteration $\zeta$ looks ahead, whichever operation it then picks. Which operation it picks is decided by
the priority keys alone. A small priority key therefore means "early in the order", not "little delay".

The delay key is the reason the decoder can wait. Without it the dispatcher is **non-delay**: it starts an
operation as soon as a machine is free and a candidate is ready. For the job shop, "the optimal schedule is in the
set of all active schedules" (Gonçalves et al., 2005, p. 79), and their figure on that page draws the non-delay
schedules as a subset of the active ones; that the optimum can lie outside the non-delay subset is not stated in
the text we read **[uncertain]**. Our model (batches, workers, shifts) is not a classical job shop, so the
dominance result does not carry over as a theorem; that waiting can be necessary here is shown by the hand example
in §5 (own). In our process waiting matters for batches: an s-batch or oven run that waits a few minutes can take
a part that becomes ready just after, and save a setup.

The search itself follows the biased random-key GA (BRKGA) of Gonçalves et al. (2011, pp. 472–473): the best
chromosomes (elite) survive unchanged, new random chromosomes (mutants) keep diversity, and children inherit each
key from their elite parent with a higher probability. The objective is any `Objective` of the project; a
lexicographic objective is one exact integer ([06](06_due-dates.md)), so the GA compares integers.

## 2. Sets, parameters, variables

New symbols (registered in [notation.md](notation.md)):

| Symbol | Meaning |
|---|---|
| $\upsilon = (\upsilon^{\mathrm{seq}}, \upsilon^{\mathrm{mach}}, \upsilon^{\mathrm{del}}, \upsilon^{\mathrm{ot}}, \upsilon^{\mathrm{join}}) \in [0,1)^{5\lvert O \rvert}$ | chromosome: priority, machine, delay, overtime and join key per operation |
| $\mathrm{ot}^{\mathrm{al}}_o$ | overtime allowance of $o$: minutes past shift end its new shares may use |
| $\zeta$ | scheduling iteration of the decoder (one lead operation, with its run or batch, per iteration) |
| $D_\zeta$ | delay of iteration $\zeta$ in minutes |
| $D^{\max}$ | longest delay in minutes (default 100, user 2026-11-20) |
| $N^{\mathrm{pop}}$, $N^{\mathrm{el}}$, $N^{\mathrm{mut}}$ | population size, number of elite chromosomes, number of mutants per generation |
| $\alpha^{\mathrm{in}}$ | probability that a child takes a key from its elite parent |

## 3. Decoding and the GA

**Decoding.** The dispatcher of [11](11_dispatching-rules.md) with:

- sequencing rule: priority of $o$ is $\upsilon^{\mathrm{seq}}_o$ (smaller first);
- assignment rule: $m(o)$ is option number $\lfloor \upsilon^{\mathrm{mach}}_o \cdot \lvert M_o \rvert \rfloor$ of
  $M_o$ (Lunardi et al., 2021, p. 420, use one real array for the assignment and one for the sequencing);
- delay of iteration $\zeta$:

$$D_\zeta = \operatorname{round}\left((D^{\max} + 1)^{\upsilon^{\mathrm{del}}_\zeta} - 1\right)$$

The delay per scheduling iteration and its key follow Gonçalves et al. (2005, p. 81), who scale linearly:
$\mathrm{Delay}_g = \mathrm{gene}_g \cdot 1.5 \cdot \mathrm{MaxDur}$. On our durations that window reached 2853
minutes (MaxDur is a 1902-minute print run) and made the GA worse (§5a). The logarithmic map is own (user
2026-11-20): key 0 gives 0, the median key 0.5 gives 9 minutes, key 0.9 gives 63, key 1 gives $D^{\max} = 100$; most
iterations wait a few minutes, few wait long. $D^{\max} = 0$ is the non-delay decoder. In iteration $\zeta$ let $t$ be the earliest possible start over all candidates. Every
candidate that can start by $t + D_\zeta$ competes, the smallest priority key wins, and the winner starts at its
own earliest start. Batch partners join if they are ready by that start ([11](11_dispatching-rules.md) §3), so a
later lead can collect more partners. With $D_\zeta = 0$ for all $\zeta$ the decoder is the non-delay dispatcher.
There are at most $\lvert O \rvert$ iterations (each places at least one operation), so $\lvert O \rvert$ delay keys
suffice.
- overtime allowance of $o$ (own):

$$\mathrm{ot}^{\mathrm{al}}_o = \operatorname{round}\left(\upsilon^{\mathrm{ot}}_o \cdot \overline{\mathrm{ot}}\right)$$

A new share of $o$ must lie in one part of a working day, the second part ending at $h^{\mathrm{E}} +
\mathrm{ot}^{\mathrm{al}}_o$ instead of $h^{\mathrm{E}}$; the break stays as for the rules. An s-batch is booked with
the allowance of the operation the decoder chose (the one whose join check passed), not of its first member. With
$\mathrm{ot}^{\mathrm{al}}_o = 0$ for all $o$ the decoder plans no overtime, as the rules. The allowance only
permits overtime: an operation uses it only where its earliest start falls there.
- join key of $o$ (own): $o$ joins another operation's s-batch only if $\upsilon^{\mathrm{join}}_o < 1/2$. A
  declining $o$ stays ready and may lead a batch of its own later, which others may join; the lead's own key is not
  asked. Key 0 joins, as the rules do, so encoded rule plans keep their batches. The key exists because a partner
  costs: every member of an s-batch ends at the batch end, so a partner lengthens the batch and delays the lead's
  successors (hand example 3, §5). p-batches (oven) are not affected: a p-batch partner adds no length (same
  duration, [03](03_carriers.md) C10), only a slot.

**Feasibility.** Every vector in $[0,1)^{5|O|}$ decodes to a feasible plan: the decoder chooses only among
candidates it can place, at times where machine and workers are free (C1–C15 as for the rules). Overtime stays
within C13: a share ends by $h^{\mathrm{E}} + \mathrm{ot}^{\mathrm{al}}_o \le h^{\mathrm{E}} + \overline{\mathrm{ot}}$.
No repair.

**Generation** $g \to g+1$ (Gonçalves et al., 2011, pp. 472–473, 478):

1. sort the population by objective value;
2. copy the $N^{\mathrm{el}}$ best (elite) unchanged;
3. add $N^{\mathrm{mut}}$ random vectors (mutants);
4. fill up to $N^{\mathrm{pop}}$ with children: an elite parent $a$ and a non-elite parent $b$; key $i$ of the
   child is $a_i$ with probability $\alpha^{\mathrm{in}}$, else $b_i$ (parametrized uniform crossover). The
   parents are drawn uniformly from their sets (own choice; how the source draws them was not checked in the
   text **[uncertain]**).

Defaults: $N^{\mathrm{el}} = 0.1\,N^{\mathrm{pop}}$, $N^{\mathrm{mut}} = 0.2\,N^{\mathrm{pop}}$,
$\alpha^{\mathrm{in}} = 0.7$: the configuration Gonçalves et al. (2011, p. 478) chose for their RCPSP after a pilot
over TOP 0.10–0.20, BOT 0.15–0.30, CProb 0.70–0.80; not tuned here. $N^{\mathrm{pop}} = 100$ (own choice; the
source uses 10 times the number of activities, p. 478, which would be 1890 on the Fidentis case with 10 orders).

**Initial population and incumbent.** All rule plans of [11](11_dispatching-rules.md) (5 sequencing × 3
assignment variants) are encoded as chromosomes: priority keys rank the operations by start, machine keys point at
the plan's machine, delay, overtime and join keys are 0. The rest is random. The best rule plan is the first incumbent, so the GA
result is never worse than the best rule under the objective. An encoded rule plan need not decode to itself
(ties and the non-delay pass); it is a starting point, not a copy.

**Stop.** After a number of generations or a wall-clock limit, whichever comes first. The time limit is checked
after every decode, also during the seeding; a generation cut by it lets its children compete with the old
population and does not count. At least one plan is always decoded (the current plan, else the first rule plan), so
under a very short limit the guarantee "never worse than the best rule" holds only for the rule plans decoded in
time. With a time limit the number of generations depends on the machine, so only a generation limit gives
reproducible results.

### 3a. NSGA-II (offline trade-off analysis)

The same chromosome and decoder, but a vector of objectives $(f_1, \dots, f_q)$ instead of one, e.g. tardiness,
overtime and makespan. The result is the **non-dominated front**: the plans for which no other found plan is at
least as good in every objective and better in one. It answers "how much overtime buys how much tardiness" on one
instance or snapshot; it is not used as a planner in the DES, which needs one plan per rescheduling (user
2026-11-19).

One generation (Deb et al., 2002, pp. 183–186):

1. sort the population into fronts by fast non-dominated sorting (front 0 non-dominated, front 1 non-dominated
   without front 0, ...);
2. per front the **crowding distance**: per objective, the normalized gap between a member's two neighbours,
   summed; the extremes of each objective get $\infty$ (Fig. 1, p. 185; the boundary value is not legible in the
   extracted text **[uncertain]**);
3. $N^{\mathrm{pop}}$ children: two binary tournaments by the crowded-comparison operator (lower front first, then
   larger crowding distance) pick the parents; with probability 0.9 uniform crossover (each key from either parent
   with probability 0.5), else a copy of the first parent; then each key is replaced by a random key with
   probability $1 / (5\lvert O \rvert)$ (own choice for random keys: the source runs a real-coded and a
   binary-coded variant, 30 bits per variable, on continuous test functions SCH, FON, POL, KUR and ZDT, pp. 187–189;
   its crossover and mutation operators are not legible in the extracted text **[uncertain]**);
4. parents and children together ($2N^{\mathrm{pop}}$) are sorted into fronts, and the next population is filled
   front by front; the front that does not fit completely is cut by crowding distance (elitism).

The initial population holds the rule plans encoded as keys, the rest is random. The front returned holds one plan
per distinct objective vector.

**Stability as an objective.** `start_deviation(reference)` evaluates a plan by its total absolute start deviation
from a reference plan, $\sum_{o} \lvert S_o - S^{\mathrm{ref}}_o \rvert$ over the reference's operations
($\lvert O \rvert \cdot D_S$ of [23](23_metrics.md) when the reference is the start plan). Wu et al. (1993, pp. 4–5)
define this deviation and the "efficient frontier" of makespan against it for one-machine rescheduling, and report
that stability "can be increased significantly with little or no sacrifice in makespan" (abstract). With
(makespan, start deviation) NSGA-II gives that frontier for our case. The objective has no CP-SAT model (analysis
only).

### 3b. Rescheduling planner

`ga_planner(objective, params, change_budget)` has the planner interface of the DES ([05](05_rescheduling-frozen-part.md)
§3): `planner(ci, snapshot, current) -> Plan`.

- **Frozen part:** the decoder starts from the snapshot as the rules do ([11](11_dispatching-rules.md)): frozen
  operations unchanged, machines busy until their (expected) end, nothing new before $t$.
- **Warm start:** the current (repaired) plan is encoded (priority keys by start, its machines, delay, overtime and
  join keys 0) and decoded first. A partner the current plan kept out of a batch may join again in that decode (the
  encoding does not record declines; own simplification, see §6). Operations it lacks (arrived since) rank after all others. The last population is not
  kept between reschedulings (own choice; the instance and the frozen part change between them).
- **Change budget $\kappa$:** a plan ranks first by its machine changes beyond $\kappa$ against the current plan
  (operations planned there and not frozen; arrived operations do not count, as in [05](05_rescheduling-frozen-part.md)),
  then by the objective. The encoded current plan keeps every machine (its machine keys point at them), so a plan
  within the budget is always in the population and the result stays within it. This is the constraint-domination
  idea of Deb et al. (2002, p. 192: a feasible solution beats an infeasible one, two infeasible ones compare by
  violation) applied to one objective (own transfer).

## 4. Objective function

Any `Objective` (`objective.evaluate(ci, assignments, breaks)`), minimized. Not affected by this file. With the
overtime key the GA can trade overtime against the other levels: under makespan alone it takes overtime where that
ends the plan earlier, under an objective with an overtime level it avoids overtime that buys nothing on a higher
level (second hand example in §5).

## 5. Implementation in code

- `planners/dispatching.py`, `dispatch_plan(..., delay=None, overtime=None, join=None)`: the delay window, the
  overtime allowance per operation (`free_from` with the extended shift end, `part_fits`, the s-batch join check) and
  the join flags (a declining partner is left out of the s-batch candidates); `None` keeps the rule plans unchanged (tests `test_zero_delay_is_the_non_delay_plan`, `overtime=[0]` in
  `test_overtime_allowance_by_hand`); an allowance above $\overline{\mathrm{ot}}$ is rejected.
- `planners/ga.py`:
  - `solve_ga(ci, objective, params, snapshot, current, change_budget)`, `ga_planner` (§3b; `planner.last`: generations,
    evaluations, value, machine changes over the budget);
  - `GaParams`: $N^{\mathrm{pop}}$, elite and mutant shares, $\alpha^{\mathrm{in}}$, $D^{\max}$ (`delay_max`),
    generation and time limits, seed (validated: at least one elite and one child), `join` (False ignores the join
    keys: the greedy join of the rules, for comparisons);
  - `N_KEYS = 5`, `delay` (the map above), `decode`, `encode`, `rule_plans`;
  - `solve_ga(ci, objective, params) -> GaResult` (plan, value, generations, evaluations, best value per
    generation).
- `objectives.py`, `start_deviation(reference)` (§3a; test `test_start_deviation_by_hand`).
- `planners/nsga2.py` (§3a): `NsgaParams`, `dominates`, `non_dominated_fronts`, `crowding_distances`,
  `nsga2(ci, objectives, params, snapshot) -> NsgaResult` (`NsgaParams.join` as `GaParams.join`) (front as (values, plan) pairs, generations,
  evaluations). Tests `tests/test_nsga2.py`: fronts and crowding by hand; on the late pack (hand example 2) the front
  is exactly $\{(600, 30), (1530, 0)\}$ in (makespan, overtime); front plans feasible and mutually non-dominated on the
  s-batch instance.
- Plain Python lists and `random.Random(seed)`: the decoder dominates the run time (about 20 ms per decode on the
  Fidentis case with 10 orders, 150 ms on the dental workers example), so vectorizing the keys would not help.

**Hand example** (`tests/test_ga.py::wait_for_batch`): two orders, each prep on M1 (1 min), then polish on M2 (5
min, setup 2 inside), polish an s-batch step ([08](08_serial-batches.md)). Every rule gives makespan 11: the first
polish starts alone at 1, the second at 6. Waiting until 2 gives one batch $[2, 2 + 2 + 3 + 3) = [2, 10)$, makespan
10, optimal (second prep ends at 2 at the earliest; a batch of both lasts 8; apart, the second polish ends at 11).
CP-SAT proves 10; the GA finds 10; a hand chromosome reproduces the batch at $[2, 10)$, and the same chromosome with
delay keys 0 gives 11.

**Hand example 2** (`tests/test_ga.py::late_pack`, default calendar: shift end 17:30, $\overline{\mathrm{ot}} = 120$):
one 90-minute pack, released Monday 16:30. Without overtime it does not fit before 17:30 and runs Tuesday 08:00 to
09:30. With an allowance of 30 minutes it runs 16:30 to 18:00 (overtime 30); with 29 it still waits for Tuesday.
The GA under makespan finds the Monday plan (makespan 600 minutes from Monday 08:00), under the overtime objective
the Tuesday plan (overtime 0).

The overtime keys are also tested together with s-batches: random chromosomes on a small instance with polish and
pack as s-batch steps, one worker and the default calendar plan overtime next to batches, and the checker accepts
every plan. Booking a batch with its first member's allowance instead of the chosen operation's fails these tests
(mutation check).

**Hand example 3** (`tests/test_ga.py::join_hurts`): two orders, polish on M2 (5 min, setup 2 inside, an s-batch
step), J1 then ships on M3 (10 min). Both polishes are ready at 0, so every rule batches them:
$[0, 2 + 3 + 3) = [0, 8)$, J1 ships $[8, 18)$, makespan 18. If J2 declines, J1 polishes alone $[0, 5)$ and ships
$[5, 15)$ while J2 polishes $[5, 10)$: makespan 15, optimal (J1 ships after a polish of at least 5). CP-SAT proves
15; the GA finds 15, with the join keys ignored 18; a hand chromosome with J2 declining gives exactly the plan
above, and a declining lead changes nothing. Further tests: all partners joining is the greedy plan; all declining
gives no batch of two, and the DES realizes such a plan unchanged; random join keys change the plan, pass the
checker and replay unchanged (zero disturbance). Without the filter in the join loop four of these five tests fail
(mutation check).

**Rescheduling** (`tests/test_ga.py`, toy-dag-3x4 with its hand plan): with b1 twice as long, every complete
rescheduling by the GA from the snapshot is feasible (the DES checks it) and accepted. With b1 three times as long,
the GA without a budget moves two machines in its third rescheduling; with $\kappa = 0$ it keeps every machine and
every plan is accepted, while the rule plans are rejected in the same setting ([05](05_rescheduling-frozen-part.md)
tests). Ignoring the budget in the ranking fails that test (mutation check). Zero disturbance: the DES realizes GA
plans exactly (toy, toy-workers, s-batch instance; Definition of Done).

## 5a. First comparison on the Fidentis case (2026-11-19)

`notebooks/ga_compare.py`, results in `notebooks/results/ga_compare.json`. Fidentis case with 10 orders (189
operations), static, makespan, 60 s per GA run, 6 seeds, default parameters with the linear delay of that day
($1.5 \cdot$ the longest duration, since replaced by the logarithmic map of §3); "no-delay" is the same GA without
delay. Rule (SPT/ECT) and CP-SAT (60 s, 12 threads, with the rule plan as hint) from notebook
08's stored run. Every GA plan passes the checker.

| s-batches | planner | makespan best / mean / worst | overtime | batches | setups saved |
|---|---|---|---|---|---|
| without | rule SPT/ECT | 30790 | 0 | – | – |
| without | best rule (LRP) | 25980 | 0 | – | – |
| without | CP-SAT | 23080 | 762 | – | – |
| without | GA | 24570 / 24580 / 24590 | 743 | – | – |
| without | GA no-delay | 23100 / 23527 / 24540 | 707 | – | – |
| with | rule SPT/ECT | 30730 | 0 | 38 | 675 |
| with | best rule (MWKR) | 24850 | 0 | – | – |
| with | CP-SAT | 24500 | 916 | 25 | 465 |
| with | GA | 23190 / 23952 / 24570 | 435 | 31 | 610 |
| with | GA no-delay | 23100 / 23210 / 23460 | 881 | 33 | 515 |

Findings:

- **With s-batches the GA beats CP-SAT** at equal wall time: 23100 to 23460 (no-delay, all 6 seeds) against 24500,
  on one core against 12 threads. Without s-batches the best GA run (23100) is about level with CP-SAT (23080), the
  mean is worse. The s-batch slots make the CP-SAT model larger ([08](08_serial-batches.md) §7a); for the GA the
  decoder forms the batches and the chromosome does not grow.
- **The delay window as scaled hurts.** With a window of up to 2853 minutes the GA is worse than
  without delay in both variants (means 24580 against 23527, 23952 against 23210). A random delay key looks up to
  two days ahead, so most decodes wait far too long. This confirms the open point on the delay scale (§6); waiting
  helps in the hand example, but needs a range that fits our durations.
- **The makespan moves in steps of about a working day** (24540 → 23100 = 1440 minutes): the plan ends when the last
  attended operation fits into a shift, so many plans share a value and improvements come in jumps. The histories
  show long plateaus and one or two jumps per run.
- **The GA was still improving at the end** (jumps in the last generations of several runs), after only 3 to 5
  generations (without s-batches) and 9 to 11 (with). The 12 runs in parallel slowed each decode about threefold (40 ms
  and 20 ms per decode alone; about 125 ms and 60 ms in the pool), so each run had roughly 20 s of single-core time.
- **The starting population is already strong:** the best of 15 rules and 85 random chromosomes is 23500 to 24930.
  SPT/ECT, the rule of notebook 08, is the worst of the 15 rules (best: LRP 25980, MWKR 24850); random chromosomes
  can use overtime, the rules cannot.

Limits: 6 seeds, wall-clock limits (not reproducible), CPU contention between the GA runs, CP-SAT values from one
earlier run; with one thread CP-SAT gave 22055 without and 26020 with s-batches in that run (protocol (75)), so
"one core against one thread" without s-batches favours CP-SAT. Makespan is not the thesis objective; the
comparison under the lexicographic objective and in the DES is part of the experiments.

## 5b. Notebook 09: two instances, the join key, fronts (2026-11-20)

`notebooks/09_ga.ipynb` (built by `notebooks/build_09_ga.py`, runs in `notebooks/ga_runs.py`, results in
`notebooks/results/09/`). Instances: **fidentis** (two workers: workers 12.2 calendar days of work, mill 9.5) and
**balanced** (a third worker: workers 8.1, mill 9.5, no clear bottleneck), each with and without s-batches.
Makespan, 60 s per run; the best of the 15 rule plans; CP-SAT on 12 threads hinted with that plan; the GA in three
settings, 6 seeds each, 6 runs in parallel, 15 to 28 generations: all five keys ("GA"), delay keys ignored
($D^{\max} = 0$), join keys ignored (`GaParams(join=False)`, greedy join as in the rules).

| instance | s-batches | best rule | CP-SAT | GA best / mean | GA no-delay best / mean | GA greedy join best / mean |
|---|---|---|---|---|---|---|
| fidentis | without | 25980 | 23060 | 23190 / 23205 | 23080 / 23229 | 23190 / 23208 |
| fidentis | with | 24850 | 23120 | 23060 / 23443 | 23110 / 23272 | 23100 / 23362 |
| balanced | without | 24540 | 22170 | 22180 / 22920 | 22180 / 22492 | 22180 / 22920 |
| balanced | with | 24640 | 23680 | 22170 / 22193 | 22175 / 22209 | 23080 / 23098 |

Findings (details in the notebook):

- **The join key removes the cost of s-batches on balanced.** With s-batches every seed of the GA reaches 22170 to
  22230, a working day below the greedy join (23080 to 23130) and level with the GA without s-batches (22180). The
  GA forms fewer batches there (20 against 34) and saves fewer setup minutes (335 against 545). Without s-batches
  the join keys decide nothing (same values as the greedy join). On fidentis no clear effect (one seed of each
  setting stays a day behind).
- **s-batches do not shorten the makespan** on either instance (balanced 22170 against 22180, fidentis 23060
  against 23080); their saving shows in worker minutes (300 to 400 in the GA's best plans), while the makespan moves
  in working-day steps. The earlier statement "s-batches lengthen the balanced makespan" held for the greedy join.
- **GA against CP-SAT:** level on fidentis, better on balanced with s-batches (every seed); CP-SAT reaches 22170 on
  balanced without s-batches, where the GA seeds split one day apart. CP-SAT on 12 threads is not deterministic:
  balanced with s-batches gave 23270 in the run before and 23680 now.
- **CP-SAT depends on its hint:** with the best rule plan it reaches 23120 on fidentis with s-batches, with SPT/ECT
  (§5a, notebook 08) 24500. The §5a statement "the GA beats CP-SAT with s-batches" came mostly from that weak hint.
- **Delay:** no gain under makespan.
- **Fronts (NSGA-II, 120 s, with s-batches, five keys):** balanced, makespan against overtime: 22250 at 447 minutes,
  23100 at 20, 23130 at 0. Fidentis stayed on the slow day (24540 at 50, 24570 at 0), while the run with four keys
  reached 23200 at 10; checked in §5c: the seed, not the join key.
  Against start deviation from the best rule plan, deviation falls to almost nothing within one day step (fidentis
  24720 at 5500 summed minutes, 24840 at 0), a day step moves most operations (balanced 22205 at 452225).

Limits: 6 seeds, wall-clock limits, makespan only, static instances, one NSGA-II run per front.

## 5c. Does the join key hurt NSGA-II? (2026-11-20)

`notebooks/nsga_join_check.py`, results in `notebooks/results/nsga_join_check.json`. Fidentis with s-batches,
(makespan, overtime), 120 s per run, seeds 1 to 4, join keys used or ignored (`NsgaParams(join=False)`); every front
plan passes the checker.

| join keys | seed 1 | seed 2 | seed 3 | seed 4 |
|---|---|---|---|---|
| used | 24540 at 50 … 24570 at 0 | 24520 at 210 … 24570 at 0 | 24540 at 55 … 24600 at 0 | 24560 at 40 … 24600 at 0 |
| ignored | 23180 at 70 … 23240 at 0 | 24540 at 150 … 24620 at 0 | 24540 at 190 … 24620 at 0 | 24540 at 175 … 24640 at 0 |

(fastest and overtime-free point of each front, makespan at overtime minutes). Without join keys one of four seeds
reaches the faster working day (the 23200 of the earlier run was seed 1); with them none does. On the slower day the
fronts with join keys need less overtime (24570 at 0 against 24620 at 0 for the same seed). One of four against none
is no evidence that the join key hurts; it shows that NSGA-II at 120 s mostly misses the day the BRKGA reaches in
60 s (23060 to 23110, §5b). Plausible reason (own reading, not tested): NSGA-II keeps no elite bias and mutates one
key in $5\lvert O \rvert$, so it explores less than the BRKGA's 20 % random mutants. Seeding NSGA-II with the
BRKGA's best plan would be a cheap fix if the fronts are used in the thesis.

## 5d. Rescheduling with arrivals in the DES (2026-11-22)

Notebook 09 §6 (`resched_run` in `notebooks/ga_runs.py`, results in `notebooks/results/09/rescheduling.json`).
Fidentis case with arrivals: orders accepted over 10 working days (0.6 or 1.0 a working day; the mill manages about
0.77), 2 known at 0, due 10 working days after acceptance; nesting binds all at the next nesting time or under the
norm with a 3-day window and the arrival rate as forecast ([33](33_order-release-interface.md)); keyed disturbances
(sigma 0.2). Start plan by CP-SAT for every planner of a seed; repair between nesting times, complete rescheduling
at every nesting time with new orders. CP-SAT and the GA minimize the worker objective with a 60-minute buffer;
CP-SAT one thread, 5 deterministic seconds per level (as in the experiments); the GA 30 generations per
rescheduling (reproducible); the rule SPT/ECT. 4 seeds.


| rate | release | SPT/ECT | CP-SAT | GA |
|---|---|---|---|---|
| 0.6 | bind all | 12.8 | 5.5 | 1.8 |
| 0.6 | norm 3 d | 9.0 | 8.8 | 4.0 |
| 1.0 | bind all | 41.5 | 50.0 | 17.8 |
| 1.0 | norm 3 d | 36.2 | 38.2 | 28.8 |

- **The GA has the fewest tardy days in every setting** and on 13 of 16 seed and setting pairs at most as many as
  CP-SAT; above capacity with bind all it cuts them to less than half of both others (17.8 against 41.5 and 50.0).
  Its makespan is also shortest in every setting (16.1 to 26.5 days against 18.9 to 28.9).
- **CP-SAT is not better than the rule above capacity.** With 5 deterministic seconds per level (as in the
  experiments) it never hit the 120 s wall clock, so the budget, not a failure, stopped it; per call it used 27 to 176
  s of wall time, the GA 35 to 57 s (30 generations). At 0.6 bind all it beats the rule (5.5 against 12.8).
- **The norm helps the rule, not the optimizers.** It lowers the rule's tardy days (12.8 to 9.0, 41.5 to 36.2) but
  raises the GA's (1.8 to 4.0, 17.8 to 28.8): a planner that sequences well gains more from seeing the orders early
  than from a short queue.
- **Overtime** stays small for all (means 20 to 90 minutes over a run); no planner is consistently higher (the GA
  more with bind all, less under the norm).

Limits: 4 seeds, 4 to 11 orders per episode (seed 3 at rate 1.0 only 4), one CP-SAT budget, the rule optimizes no
objective; disturbances are only repaired. Own reading of the numbers.

To make the GA usable here, `horizon_bound` (the spread of the lexicographic weights, [06](06_due-dates.md) §4) is
computed once per instance object: a lexicographic `evaluate` asked it about 25 times per plan and took 98 % of the
time (69 ms per plan on 216 operations, now about 6 ms). `ga_planner.last` reports `wall_limited` like CP-SAT.
Test `test_ga_reschedules_arrivals_with_nesting` (dental example, three arrivals, every rescheduling accepted).

## 5e. The plan over time (2026-11-22)

Notebook 09 §7: the plan history of the DES (`execute(..., keep_history=True)`, plan metrics (M10) of
[23](23_metrics.md)) for rate 1.0, seeds 1 and 4, both releases and all three planners (results in
`notebooks/results/09/history.json`). An animation shows the plan in force once a day (GA and CP-SAT, seed 1, bind
all; `viz.plan_at` rebuilds the plan at t from the change sets, `viz.plot_plan_state` draws it per order with finished
operations as realized), and step plots show the planned tardy days and makespan over the run.

**What the plan history shows** (rate 1.0, seeds 1 and 4):

- **Seed 1, bind all:** the GA's plan reaches 1 planned tardy day at day 2 and keeps it to the end. The rule's
  climbs with every binding to 22 by day 10.4. CP-SAT's reschedulings lower it (to 3 at days 9.2 and 10.2), but the
  repairs right after push it up again (9 at day 10.2, 14 at day 15.4, 18 at day 17.4): disturbances trigger no
  rescheduling here (§6), so a tight plan drifts and nothing re-sequences it. The GA's plan absorbs the same
  disturbances.
- **Under the norm the planners stay close until the late bindings** (planned tardy days at most 3 up to day 14 to
  15), when the held-back orders arrive together; from then on the GA's plan has the fewest (seed 1 day 16.2: rule 15,
  CP-SAT 11, GA 9; seed 4 at the end: 58, 55, 36).
- **Animation (seed 1, bind all):** at the end only O2 finished late with the GA (realized tardy days 1); with
  CP-SAT seven of eight orders did.

Own reading of 4 episodes per planner; the history is the plan in force, not the realized schedule (M10).

## 6. Assumptions and open points

- **Delay scale.** Now logarithmic up to $D^{\max} = 100$ minutes (§3), chosen by judgement (user: median about
  10, maximum about 100), not tuned. A scale per step or per machine remains an alternative.
- **Waiting reaches only ready operations.** A lead can wait for partners that are already ready (all predecessors
  placed) but become available later; an operation whose predecessor is not placed yet cannot join. A look-ahead
  would be needed for that (later, if the experiments show it).
- **Random vectors decline half the partners.** With the threshold 1/2 a random key vector (every mutant) keeps
  about half of all partners out of s-batches. The BRKGA copes (§5b); for NSGA-II four seeds show no harm (§5c), so
  the threshold stays.
- **Join key: one flag per partner, not per pair.** An operation declines every batch or none; which lead it joins
  follows from the order of the decoder. The threshold 1/2 is own. The warm start encodes no declines, so a
  current plan with a partner kept out of a batch does not decode back to itself (it remains a starting point).
- **Not a model change.** The join key only widens which plans the decoder can reach; instance format, checker, DES
  and CP-SAT are unchanged (CP-SAT may already leave a batch slot empty), so the Definition of Done for a model
  feature does not apply.
- **Overtime per operation, not per worker and day.** The key allows overtime for an operation's shares; a
  worker's overtime on a day follows from the shares placed there. A key per worker and day would be closer to
  CP-SAT's $\mathrm{ot}_{z,\nu}$ ([12](12_cp-sat.md)) but needs the planning horizon in days before decoding (own
  choice, revisit if the experiments show the GA buys overtime inefficiently).
- **Parameters** ($N^{\mathrm{pop}}$, elite, mutants, $\alpha^{\mathrm{in}}$) are taken from the source, not tuned.
- **Run time** (note for the experiments, user 2026-11-19): about 2 s per generation of 100 on one core for the
  Fidentis case. The time limit is checked between generations only: the 15 rule plans and the initial population
  are decoded first (about 2.5 s on the Fidentis case, 17 s on the dental workers example), so a budget of 1 s per
  rescheduling cannot even finish the seeding. Step 3 needs a time check inside the seeding, and a profile of
  `dispatch_plan` (the dental example decodes 7 times slower than the Fidentis case for 1.5 times the
  operations). Inside the DES the GA needs a time limit, not a generation count; parallel evaluation needs a
  process pool that lives for the whole DES run (starting one per rescheduling costs seconds on Windows).
- **Single objective.** The DES needs one plan per rescheduling, so the GA minimizes the lexicographic objective.
  NSGA-II (Deb et al., 2002) with the same chromosome and decoder is the offline trade-off analysis (§3a).
  Stability is not yet one of its objectives: it needs a reference plan as an `Objective` (machine changes or start
  deviation against it); to add for the analysis when needed.
- **NSGA-II operators and parameters** (crossover 0.9, key mutation $1/(5|O|)$, $N^{\mathrm{pop}}$ 100) are own
  choices, not tuned; no change budget (an offline analysis).
- **No population carried across reschedulings.** Each rescheduling starts from the current plan, the rule plans and
  random keys.

## 7. Sources

- Bean (1994): random keys, feasibility of all offspring (p. 154).
- Gonçalves et al. (2005): parameterized active schedules, priorities and delays as genes, delay formula (pp. 79,
  81).
- Gonçalves et al. (2011): BRKGA generation scheme, parametrized uniform crossover, parameter values (pp. 472–473,
  478).
- Deb et al. (2002): NSGA-II (fast non-dominated sorting, crowding distance, crowded comparison, elitist
  selection from parents and children, pp. 183–186); constraint domination (p. 192), transferred to the change
  budget.
- Lunardi et al. (2021): two real arrays (assignment, sequencing) with a decoder (p. 420).
- Defersha & Rooyani (2020): an alternative without machine keys, the machine that finishes soonest (p. 2);
  seeding with the ECT rule plans covers that choice.
- Own modeling: the decoder is the project's dispatcher; the delay window applied to runs, p- and s-batches and
  workers; the overtime key; the join key; the initial population from the rule plans.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-19 | uncommitted | Step 1: delay window in `dispatch_plan`, `planners/ga.py` (BRKGA with priority, machine and delay keys), `tests/test_ga.py`. |
| 2026-11-19 | uncommitted | Step 2: overtime key (allowance per operation) in `dispatch_plan` and the chromosome ($4\lvert O \rvert$ keys); hand example 2; s-batches with overtime tested. |
| 2026-11-19 | uncommitted | Step 3: `solve_ga` from a snapshot with warm start, change budget (rank by excess) and a time check after every decode; `ga_planner`; tests in the DES, budget mutation-checked, zero disturbance. |
| 2026-11-19 | uncommitted | Step 4: `planners/nsga2.py` over the same keys and decoder; `tests/test_nsga2.py`. |
| 2026-11-19 | uncommitted | §5a: first comparison with rule and CP-SAT on the Fidentis case (`notebooks/ga_compare.py`). |
| 2026-11-20 | uncommitted | Logarithmic delay map ($D^{\max} = 100$) instead of the linear one; `start_deviation` objective for NSGA-II; §5b notebook 09. |
| 2026-11-20 | uncommitted | Join key ($5\lvert O \rvert$ keys): a partner may decline an s-batch; `dispatch_plan(..., join)`, `GaParams.join`; hand example 3. |
| 2026-11-20 | uncommitted | `NsgaParams.join`; §5c: the join key does not hurt NSGA-II (4 seeds). |
| 2026-11-22 | uncommitted | §5d: GA, CP-SAT and rule rescheduling with arrivals in the DES; `horizon_bound` cached per instance; `ga_planner.last["wall_limited"]`. |
| 2026-11-22 | uncommitted | §5e: plan history of the rescheduling runs, animation and metrics over time (`viz.plan_at`, `viz.plot_plan_state`). |
