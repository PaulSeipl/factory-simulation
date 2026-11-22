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
- **Deviations from the formulation:**
  - A rollout replays the committed prefix from scratch, because `dispatch_plan` keeps no copyable state. One
    iteration therefore costs one whole decode (dental example about 7 ms, dental workers about 80–130 ms).
  - The normalization uses $f^{\min}$, $f^{\max}$ of the whole search (own), not per node.

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

## 6. Assumptions and open points

- **Non-delay only, no overtime, greedy partners.**
  - The tree never waits and never plans overtime. The GA's delay and overtime keys can do both (toy-3x3: the optimum
    needs a delay).
  - Load and s-batch partners follow the rollout rule. The GA's priority and join keys steer them, so the GA has
    more control over how loads are composed.
  - M4 adds overtime to the action, if M3 shows the gap.
- **Budget.** Decision depth is 133 (dental example) and 174 (dental workers) ([11](11_dispatching-rules.md) §5). On
  dental workers, 60 s gives about 3 iterations per decision. A resumable dispatcher would make a rollout cheaper than
  a whole decode.
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
