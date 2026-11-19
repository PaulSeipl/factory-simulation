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
| $\upsilon = (\upsilon^{\mathrm{seq}}, \upsilon^{\mathrm{mach}}, \upsilon^{\mathrm{del}}, \upsilon^{\mathrm{ot}}) \in [0,1)^{4\lvert O \rvert}$ | chromosome: priority, machine, delay and overtime key per operation |
| $\mathrm{ot}^{\mathrm{al}}_o$ | overtime allowance of $o$: minutes past shift end its new shares may use |
| $\zeta$ | scheduling iteration of the decoder (one lead operation, with its run or batch, per iteration) |
| $D_\zeta$ | delay of iteration $\zeta$ in minutes |
| $p^{\max}$ | longest processing time of any operation on any machine |
| $\alpha^{\mathrm{del}}$ | delay factor (default 1.5, Gonçalves et al., 2005, p. 81) |
| $N^{\mathrm{pop}}$, $N^{\mathrm{el}}$, $N^{\mathrm{mut}}$ | population size, number of elite chromosomes, number of mutants per generation |
| $\alpha^{\mathrm{in}}$ | probability that a child takes a key from its elite parent |

## 3. Decoding and the GA

**Decoding.** The dispatcher of [11](11_dispatching-rules.md) with:

- sequencing rule: priority of $o$ is $\upsilon^{\mathrm{seq}}_o$ (smaller first);
- assignment rule: $m(o)$ is option number $\lfloor \upsilon^{\mathrm{mach}}_o \cdot \lvert M_o \rvert \rfloor$ of
  $M_o$ (Lunardi et al., 2021, p. 420, use one real array for the assignment and one for the sequencing);
- delay of iteration $\zeta$:

$$D_\zeta = \operatorname{round}\left(\upsilon^{\mathrm{del}}_\zeta \cdot \alpha^{\mathrm{del}} \cdot p^{\max}\right)$$

(Gonçalves et al., 2005, p. 81: $\mathrm{Delay}_g = \mathrm{gene}_g \cdot 1.5 \cdot \mathrm{MaxDur}$, one delay per
scheduling iteration $g$.) In iteration $\zeta$ let $t$ be the earliest possible start over all candidates. Every
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

**Feasibility.** Every vector in $[0,1)^{4|O|}$ decodes to a feasible plan: the decoder chooses only among
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
the plan's machine, delay and overtime keys are 0. The rest is random. The best rule plan is the first incumbent, so the GA
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
   probability $1 / (4\lvert O \rvert)$ (own choice for random keys; the source uses real-coded and binary
   operators);
4. parents and children together ($2N^{\mathrm{pop}}$) are sorted into fronts, and the next population is filled
   front by front; the front that does not fit completely is cut by crowding distance (elitism).

The initial population holds the rule plans encoded as keys, the rest is random. The front returned holds one plan
per distinct objective vector.

### 3b. Rescheduling planner

`ga_planner(objective, params, change_budget)` has the planner interface of the DES ([05](05_rescheduling-frozen-part.md)
§3): `planner(ci, snapshot, current) -> Plan`.

- **Frozen part:** the decoder starts from the snapshot as the rules do ([11](11_dispatching-rules.md)): frozen
  operations unchanged, machines busy until their (expected) end, nothing new before $t$.
- **Warm start:** the current (repaired) plan is encoded (priority keys by start, its machines, delay and overtime
  keys 0) and decoded first. Operations it lacks (arrived since) rank after all others. The last population is not
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

- `planners/dispatching.py`, `dispatch_plan(..., delay=None, overtime=None)`: the delay window and the overtime
  allowance per operation (`free_from` with the extended shift end, `part_fits`, the s-batch join check); `None`
  keeps the rule plans unchanged (tests `test_zero_delay_is_the_non_delay_plan`, `overtime=[0]` in
  `test_overtime_allowance_by_hand`); an allowance above $\overline{\mathrm{ot}}$ is rejected.
- `planners/ga.py`:
  - `solve_ga(ci, objective, params, snapshot, current, change_budget)`, `ga_planner` (§3b; `planner.last`: generations,
    evaluations, value, machine changes over the budget);
  - `GaParams`: $N^{\mathrm{pop}}$, elite and mutant shares, $\alpha^{\mathrm{in}}$, $\alpha^{\mathrm{del}}$,
    generation and time limits, seed (validated: at least one elite and one child);
  - `N_KEYS = 4`, `delay_unit` ($\alpha^{\mathrm{del}} p^{\max}$), `decode`, `encode`, `rule_plans`;
  - `solve_ga(ci, objective, params) -> GaResult` (plan, value, generations, evaluations, best value per
    generation).
- `planners/nsga2.py` (§3a): `NsgaParams`, `dominates`, `non_dominated_fronts`, `crowding_distances`,
  `nsga2(ci, objectives, params, snapshot) -> NsgaResult` (front as (values, plan) pairs, generations,
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

**Rescheduling** (`tests/test_ga.py`, toy-dag-3x4 with its hand plan): with b1 twice as long, every complete
rescheduling by the GA from the snapshot is feasible (the DES checks it) and accepted. With b1 three times as long,
the GA without a budget moves two machines in its third rescheduling; with $\kappa = 0$ it keeps every machine and
every plan is accepted, while the rule plans are rejected in the same setting ([05](05_rescheduling-frozen-part.md)
tests). Ignoring the budget in the ranking fails that test (mutation check). Zero disturbance: the DES realizes GA
plans exactly (toy, toy-workers, s-batch instance; Definition of Done).

## 6. Assumptions and open points

- **Delay scale.** $\alpha^{\mathrm{del}} p^{\max}$ is 2853 minutes on the Fidentis case ($p^{\max} = 1902$, a
  print run), so a random delay key lets an iteration look up to two days ahead, while most operations take 10 to
  60 minutes. Gonçalves et al. tuned 1.5 on job-shop instances with similar durations. Alternatives: a scale per
  step or per machine, or a logarithmic map of the key (user 2026-11-19) so that most keys give short delays; to
  be measured in the experiments.
- **Waiting reaches only ready operations.** A lead can wait for partners that are already ready (all predecessors
  placed) but become available later; an operation whose predecessor is not placed yet cannot join. A join key or a
  look-ahead would be needed for that (later, if the experiments show it).
- **s-batch membership stays greedy.** Every ready partner that fits joins; the GA cannot say "do not join". Same as
  above.
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
- **NSGA-II operators and parameters** (crossover 0.9, key mutation $1/(4|O|)$, $N^{\mathrm{pop}}$ 100) are own
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
  workers; the overtime key; the initial population from the rule plans.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-19 | uncommitted | Step 1: delay window in `dispatch_plan`, `planners/ga.py` (BRKGA with priority, machine and delay keys), `tests/test_ga.py`. |
| 2026-11-19 | uncommitted | Step 2: overtime key (allowance per operation) in `dispatch_plan` and the chromosome ($4\lvert O \rvert$ keys); hand example 2; s-batches with overtime tested. |
| 2026-11-19 | uncommitted | Step 3: `solve_ga` from a snapshot with warm start, change budget (rank by excess) and a time check after every decode; `ga_planner`; tests in the DES, budget mutation-checked, zero disturbance. |
| 2026-11-19 | uncommitted | Step 4: `planners/nsga2.py` over the same keys and decoder; `tests/test_nsga2.py`. |
