# 15 — Monte Carlo tree search over the dispatcher's decisions

## 1. Prose description

A third search-based planner next to CP-SAT ([12](12_cp-sat.md)) and the GA ([14](14_genetic-algorithm.md)). It
builds the plan the way the dispatcher does ([11](11_dispatching-rules.md)): iteration by iteration, from the
snapshot with its frozen part. At each iteration with more than one candidate, it decides which
(operation, machine) starts next.

Building a plan step by step is a sequential decision problem. Lv et al. (2025, p. 1, p. 3) describe JSP and FJSP as a
Markov decision process. Monte Carlo tree search (MCTS) searches this decision tree:
- it tries choices;
- it finishes each partial plan with a rule (rollout);
- it keeps statistics per node.

It learns nothing between instances. The tree is the decision space of the GA's decoder, without the delay, overtime
and join keys. So MCTS and the GA can be compared at the same number of decodes. The step interface is also the one
a learned policy (RL) will use later.

Root commitment follows Li et al. (2021, p. 4):
- after a number of iterations, the root's decision is fixed;
- the chosen child becomes the new root;
- its subtree is kept, so its statistics are reused.

## 2. Sets, parameters, variables

New symbols (central definitions in [notation.md](notation.md)):

| Symbol | Meaning |
|---|---|
| $\mathcal{U}$, $\vartheta$ | search tree; a node, i.e. the state after a prefix of decisions |
| $N^{\mathrm{it}}$ | iterations per decision (rollouts before each root commitment) |
| $N^{\mathrm{wid}}$ | children per node: the best candidates by the rollout rule |
| $N^{\mathrm{vis}}_\vartheta$ | visits of node $\vartheta$ |
| $\bar f_\vartheta$ | mean value of the rollouts through $\vartheta$ |
| $f^{\min}$, $f^{\max}$ | best and worst rollout value seen in this search |
| $\beta$ | exploration weight of the UCB term |

A **decision** is an iteration $\zeta$ of the dispatcher with more than one eligible candidate $(t, o, m, p)$ (all
that can start by the earliest start; non-delay). Iterations with one candidate are not part of the tree.

## 3. Algorithm

Value of a plan $\pi$: $f(\pi)$, the objective's value. With a change budget $\kappa$ it becomes
$(\chi(\pi) - \kappa)^+ (\mathrm{spr}(f) + 1) + f(\pi)$. So one change beyond the budget outweighs any objective
difference, the same order as the GA's rank ([14](14_genetic-algorithm.md) §3b).

1. **Incumbent and rollout rule.** Evaluate the current plan (decoded as the GA does) and the 15 rule plans. The
   best of them is the first incumbent. The best **joint** rule plan names the rollout rule, so the tree chooses
   machines too.
2. **Iteration** (from the root $\vartheta_0$):
   - The committed decisions are replayed.
   - **Selection:** at a node whose children have all been expanded, take the child with the largest
     $$\frac{f^{\max} - \bar f_{\vartheta'}}{f^{\max} - f^{\min}} + \beta \sqrt{\frac{\ln N^{\mathrm{vis}}_\vartheta}{N^{\mathrm{vis}}_{\vartheta'}}}$$
     The first term is 0 while $f^{\max} = f^{\min}$; smaller values are better.
   - **Expansion:** at the first node that still has untried children, add the next one. A node's children are its
     $N^{\mathrm{wid}}$ best candidates by the rollout rule, tried in that order.
   - **Rollout:** the rollout rule decides all later decisions.
   - **Backup:** the plan's value is added to every node on the path (visits, sum, best value). The incumbent is
     updated.
3. **Commitment:** after $N^{\mathrm{it}}$ iterations, fix the root's child with the best value seen below it (ties:
   expansion order) and make it the root. Stop when an iteration reaches no decision beyond the committed ones.
4. The result is the incumbent: the best plan over the warm start, the rule plans and all rollouts.

Properties:
- Every plan is feasible: the candidates are checked by the dispatcher (hook `choose`, [11](11_dispatching-rules.md) §5).
- The result is never worse than the best rule plan.
- The search uses no randomness, so the same parameters give the same plan (without a time limit).
- The first iteration below every node expands the rollout rule's own choice. With $N^{\mathrm{it}} = 1$ the result
  is the rollout rule's plan.

## 4. Objective function

Any `Objective` ([14](14_genetic-algorithm.md) §4); in the experiments, the worker objective with cutoff slack
([04](04_workers.md) (O7)). No new objective.

## 5. Implementation in code

- **Module:** `simulation.planners.mcts`.
  - `solve_mcts(ci, objective, params, snapshot, current, change_budget) -> MctsResult` (plan, value, evaluations,
    decisions, rollout rule, `wall_limited`, `over_budget`).
  - `mcts_planner(objective, params, change_budget)`: the planner interface of [05](05_rescheduling-frozen-part.md)
    §3, `planner.last` as for the GA.
- **Parameters:** `MctsParams(iterations` $= N^{\mathrm{it}} = 20$, `width` $= N^{\mathrm{wid}} = 5$,
  `exploration` $= \beta = \sqrt 2$, `time_limit = None)`. All are own choices, to be tuned in M3. The time limit is a
  safety net checked before every rollout; when it stops the search, the incumbent is returned.
- **Shared with the GA:** `budget_excess` (change budget), `decode(encode(current))` (warm start).
- **Experiments:** planner `"mcts"` in `PolicyConfig` with the required `iterations`; the configuration's
  `time_limit` is the safety net ([07](07_order-arrivals.md) §6).
- **Resuming at the root** (2026-11-22): the root keeps a checkpoint of the dispatcher before its decision
  (`dispatch_until`, [11](11_dispatching-rules.md) §5). Every rollout resumes from a copy of it, and a commitment
  advances it by one decision. Before that, every rollout replayed the committed decisions from scratch.
  - Same plans as before on dental example, Fidentis and dental workers (worker objective); one evaluation fewer,
    namely the old last rollout, which only found that no decision was left.
  - 1.9× (dental example), 2.0× (Fidentis) and 2.1× (dental workers) faster, as estimated from the mean share of a
    decode spent before a decision (70 %, 54 %, 51 %).
- **Deviation from the formulation:** the normalization uses $f^{\min}$, $f^{\max}$ of the whole search (own), not
  per node.

Tests (`tests/test_mcts.py`):
- feasibility on four toy instances and dental example;
- never worse than any rule;
- **hand case** `toy-dag-3x4`:
  - all 15 rule plans end at 12;
  - enumerating all 108 non-delay plans gives 11, and CP-SAT proves 11 optimal;
  - the search with $N^{\mathrm{it}} = 100$ finds 11; with $\beta = 0.5$ it stays at 12 (too greedy).
- beats the rules on dental example;
- same parameters, same plan;
- time limit;
- from a snapshot, warm start;
- zero disturbance (DES realizes the plan);
- rescheduling in the DES and change budget 0, as for the GA;
- one negative test per parameter rule.

**Exploration** (`toy-dag-3x4`, $N^{\mathrm{wid}} = 5$):
- $\beta \in \{0.5, 1\}$ never left the rule's first decision within 200 iterations. The second root child had a
  normalized mean of 0 after two visits, against about 1 for the first. Its UCB term needs
  $\beta \sqrt{\ln N / 2} > 1$; at $\beta = 0.5$ that means $N > e^8 \approx 3000$.
- $\beta = \sqrt 2$ found the optimum with 100 iterations.

**First numbers** (2026-11-22, one core, makespan, $N^{\mathrm{it}} = 10$, $N^{\mathrm{wid}} = 5$, $\beta = \sqrt 2$):

| Instance | Best rule | MCTS | CP-SAT 10 s | Evaluations | Decisions | Time |
|---|---|---|---|---|---|---|
| toy-3x3 | 11 | 11 | 10 (optimal, needs a delay) | 56 | 4 | < 0.1 s |
| toy-dag-3x4 | 12 | 12 (11 with $N^{\mathrm{it}} = 100$) | 11 (optimal) | 46 | 3 | < 0.1 s |
| mk01 | 42 | 42 | 40 (optimal) | 406 | 39 | 0.4 s |
| dental-carriers-example | 1138 | **1122** | 1251 (feasible) | 1336 | 132 | 10.3 s |

With $\beta = 0.5$ the table gave the same MCTS values (CP-SAT reached 1280 in 10 s then; machine load varies). On toy-3x3 the
optimum 10 is not a non-delay plan: the enumeration of all 174 non-delay plans gives 11 at best, so the tree cannot
reach it.

## 5a. M3: comparison at equal wall time (2026-11-22)

**Script:** `notebooks/mcts_compare.py`, results in `notebooks/results/mcts_compare.json`.

**Setup:**
- 60 s per run on one core each, 11 runs in parallel.
- GA: 3 seeds each, in three variants:
  - all keys;
  - overtime keys forced to 0;
  - additionally $D^{\max} = 0$ (non-delay).

  The last variant has the same action class as MCTS, except that the join keys and priority keys still steer the
  load and s-batch partners.
- CP-SAT: one thread, hinted with the best rule plan.
- MCTS: $N^{\mathrm{it}}$ = budget / (decisions × rollout time), measured before the run.
- Objectives: makespan; on dental workers (due dates and calendar) also the worker objective with cutoff slack.

| Case, objective | Rule | CP-SAT | MCTS ($N^{\mathrm{it}}$) | GA | GA no overtime | GA no overtime, no delay |
|---|---|---|---|---|---|---|
| dental example, makespan | 1138 | 1138 | **1122** (19) | 1126–1130 | 1126–1130 | 1126–1129 |
| dental workers, makespan | 2963 | 2963 | 2936 (2, cut) | **2915**–2942 (OT 345–531) | 2946–2952 | 2952 |
| dental workers, worker obj. ($10^{17}$) | 1.736 | 1.734 | 1.736 (1) | **1.27**–1.33 (OT 301–463) | 1.56–1.61 | 1.61 |
| Fidentis, makespan | 24850 | none in 60 s | 24640 (32, cut) | **23130**–24520 (OT 630–872) | 23200–24570 | 24570 |
| balanced, makespan | 24640 | none in 60 s | 24640 (13) | **22180**–22260 (OT 459–699) | 23160–23200 | 23170–23610 |

"cut": the time limit stopped the search before every decision was committed. OT: planned overtime in minutes. An
earlier round on a more loaded machine gave the same ranking.

**Findings:**
- **Overtime explains most of the GA's lead on the worker instances.**
  - On dental workers (makespan) the GA without overtime is behind MCTS: 2946–2952 against 2936.
  - On Fidentis and balanced, removing overtime costs the GA 70–1440 minutes.
  - Makespan does not penalize overtime. The worker objective weighs it below tardiness, so trading tardiness
    for overtime pays there.
- **In the same action class** (no overtime, non-delay):
  - MCTS is better on dental example and on dental workers (makespan);
  - slightly worse on Fidentis (24640 against 24570);
  - clearly worse on balanced (24640 against 23170–23610).

  What remains of the GA's advantage on balanced comes from its join keys and from its priority keys over load
  and s-batch partners, or from the search itself. This run does not separate the two.
- **Budget.** On dental workers a rollout costs about 0.2 s, so 60 s allow 1–2 iterations per decision. With the
  worker objective MCTS stays at its rollout rule.
- **CP-SAT on one thread** finds no plan for Fidentis in 60 s. On dental workers it does not improve the hinted rule
  plan, or only barely (worker objective 1.734 against 1.736).
  - In the first round it returned 1.906, worse than the hint, after 304 s (five levels one after another).
  - In a loaded run it failed with "level active_makespan: no solution within the time limit".
  - Whether the hint is kept across the levels is open ([12](12_cp-sat.md)).

## 6. Assumptions and open points

- **Non-delay only, no overtime, greedy partners.**
  - The tree never waits and never plans overtime. The GA's delay and overtime keys can do both (toy-3x3: the optimum
    needs a delay).
  - Load and s-batch partners follow the rollout rule. The GA's priority and join keys steer them, so the GA has
    more control over how loads are composed.
  - M4 adds overtime to the action, if M3 shows the gap.
- **Budget.** Decision depth is 133 (dental example) and 174 (dental workers) ([11](11_dispatching-rules.md) §5). On
  dental workers, 60 s gave 1–2 iterations per decision in M3 (§5a). Resuming at the root doubles that; the rest of
  every rollout still runs to the end of the plan.
- **Values.** The rollout value of the lexicographic worker objective is one large integer. Its normalization over
  $[f^{\min}, f^{\max}]$ is dominated by the highest level that varies. Whether that suits UCB is open (M3).
- **Parameters** $N^{\mathrm{it}}$, $N^{\mathrm{wid}}$, $\beta$ are own choices, tuned in M3 at equal wall time against
  the GA.

## 7. Sources

- Root commitment and reuse of the subtree: Li et al. (2021), p. 4 (PDF page index; article number 107211),
  Zotero `7VCTD9GM`. They use MCTS for rescheduling a dynamic FJSP, and moves are (order, operation, machine).
- Scheduling as a Markov decision process: Lv et al. (2025), p. 1, p. 3, Zotero `QACURDAW`.
- UCB1 as the selection rule and UCT as MCTS with UCB1: **[uncertain]**, not found in the library (Auer et al. 2002;
  Kocsis & Szepesvári 2006, from memory).
- Own: tree over the dispatcher's decisions through the `choose` hook; fixed-width expansion in rule order; rule plans
  as incumbent; commitment to the child with the best value seen; normalization over the whole search;
  change-budget rank as the GA's.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-22 | uncommitted | M2: `planners/mcts.py`, `tests/test_mcts.py`, planner `"mcts"` in the experiments; first numbers. |
| 2026-11-22 | uncommitted | §5a M3: comparison at 60 s against rule, CP-SAT and three GA variants (`notebooks/mcts_compare.py`). |
| 2026-11-22 | uncommitted | §5: rollouts resume from the root's checkpoint (`dispatch_until`); same plans, about 2× faster. |
