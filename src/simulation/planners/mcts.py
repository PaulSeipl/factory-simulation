"""Monte Carlo tree search over the dispatcher's decisions (math/15_mcts.md).

A decision is an iteration of `dispatch_plan` with more than one candidate (the hook `choose`, math/11 §5): which
(operation, machine) starts next. Every candidate gives a feasible plan, so the search never checks feasibility.

Root commitment (Li et al. 2021, p. 4): from the current root, N^it iterations each walk down the tree by UCB, expand
one child, finish the plan with the rollout rule and back its value up the path; then the root's decision is fixed
(the child with the best value seen below it) and that child's subtree becomes the new root, until no decision is
left. A node's children are the ω best candidates by the rollout rule, tried in that order (fixed-width expansion,
own), so the first iteration finishes as the rollout rule does. The rollout rule is the best joint rule plan (the tree
also picks machines). The incumbent starts with the current plan (decoded as the GA does) and the 15 rule plans, so
the result is never worse than the best rule; it is the best plan of all rollouts. Values are normalized to [0, 1]
over the values seen in this search (own). With a change budget a plan ranks first by its changes beyond it, as in
the GA. No randomness: ties go to the rollout rule's order, so a run without time limit always gives one plan.

shortcut: a rollout replays the committed prefix from scratch (dispatch_plan keeps no copyable state), so it costs a
whole decode; a resumable dispatcher would make deep trees cheaper.
"""

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Plan
from simulation.objectives import MAKESPAN, Objective
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan
from simulation.planners.ga import budget_excess, decode, encode

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot

type Key = tuple[int, int | None]  # a candidate: (operation, machine)


@dataclass(frozen=True, slots=True)
class MctsParams:
    iterations: int = 20  # N^it per decision (own choice)
    width: int = 5  # ω: children per node, the best candidates by the rollout rule (own choice)
    # β of the UCB term on values normalized to [0, 1]; √2 is the UCB1 form. 0.5 and 1 never found the toy-dag-3x4
    # optimum within 200 iterations, √2 did with 100 (math/15 §5)
    exploration: float = math.sqrt(2)
    time_limit: float | None = None  # seconds, checked before every rollout (safety net); None: only N^it

    def __post_init__(self):
        if self.iterations < 1:
            raise ValueError(f"iterations must be at least 1, got {self.iterations}")
        if self.width < 1:
            raise ValueError(f"width must be at least 1, got {self.width}")
        if self.exploration < 0:
            raise ValueError(f"exploration must not be negative, got {self.exploration}")
        if self.time_limit is not None and self.time_limit <= 0:
            raise ValueError(f"time_limit must be positive, got {self.time_limit}")


@dataclass(frozen=True, slots=True)
class MctsResult:
    plan: Plan
    value: int  # objective value of the plan
    evaluations: int  # plans evaluated (warm start, rule plans, rollouts)
    decisions: int  # decisions fixed by root commitment
    rollout_rule: str  # the joint sequencing rule that finishes every rollout
    wall_limited: bool  # the time limit ended the search before every decision was fixed
    over_budget: int = 0  # machine changes beyond the change budget


@dataclass(slots=True)
class _Node:
    children: dict[Key, "_Node"] = field(default_factory=dict)  # in expansion order
    untried: list[Key] | None = None  # set on the first visit: the ω best candidates by the rollout rule
    visits: int = 0
    total: float = 0.0  # sum of the scalar values backed up through the node
    best: float = math.inf  # best scalar value of a rollout through the node


def solve_mcts(
    ci: CompiledInstance, objective: Objective, params: MctsParams | None = None, snapshot: Snapshot | None = None,
    current: Sequence[Assignment] | None = None, change_budget: int | None = None,
) -> MctsResult:
    """The best plan the search finds (module docstring). `current`: warm start and reference of `change_budget`."""
    start, params = time.perf_counter(), params or MctsParams()
    frozen = {(f.order_id, f.op_id) for f in snapshot.frozen} if snapshot else set()
    before = {(a.order_id, a.op_id): a.machine for a in current or ()}
    weight = objective.spread(ci) + 1  # one change beyond the budget outweighs any objective difference
    evaluations = 0
    best: tuple[tuple[int, int], Plan] | None = None

    def evaluate(plan: Plan) -> float:
        nonlocal evaluations, best
        evaluations += 1
        rank = budget_excess(plan.assignments, before, frozen, change_budget), objective.evaluate(
            ci, plan.assignments, plan.breaks)
        if best is None or rank < best[0]:
            best = rank, plan
        return float(rank[0] * weight + rank[1])

    if current is not None:
        evaluate(decode(ci, encode(ci, current), 0, snapshot))
    rollout, rollout_value = "", math.inf
    for s, seq in SEQUENCING_RULES.items():
        for a in [*ASSIGNMENT_RULES, None]:
            v = evaluate(dispatch_plan(ci, seq, ASSIGNMENT_RULES[a] if a else None, snapshot))
            if a is None and v < rollout_value:
                rollout, rollout_value = s, v
    seq = SEQUENCING_RULES[rollout]

    def by_rule(eligible, state) -> list[int]:
        return sorted(range(len(eligible)), key=lambda i: (
            *seq(ci, state, *eligible[i][1:]), eligible[i][1], eligible[i][2] is None, eligible[i][2] or 0))

    prefix: list[Key] = []  # the committed decisions
    root, lo, hi = _Node(), math.inf, -math.inf  # lo, hi: best and worst scalar value seen (normalization)

    def ucb(parent: _Node, child: _Node) -> float:
        mean = child.total / child.visits
        exploit = (hi - mean) / (hi - lo) if hi > lo else 0.0  # smaller values are better
        return exploit + params.exploration * math.sqrt(math.log(parent.visits) / child.visits)

    def iterate() -> bool:
        """One rollout from the root; False if the root has no decision left (the plan is complete)."""
        nonlocal lo, hi
        path, k, expanded, reached = [root], 0, False, False

        def choose(eligible, state) -> int:
            nonlocal k, expanded, reached
            if len(eligible) == 1:
                return 0
            keys: list[Key] = [(c[1], c[2]) for c in eligible]
            k += 1
            if k <= len(prefix):
                return keys.index(prefix[k - 1])
            reached = True
            node = path[-1]
            if expanded:
                return by_rule(eligible, state)[0]  # rollout below the tree
            if node.untried is None:
                node.untried = [keys[i] for i in by_rule(eligible, state)[:params.width]]
            if node.untried:
                key = node.untried.pop(0)
                node.children[key] = _Node()
                expanded = True
            else:
                key = max(node.children, key=lambda c: ucb(node, node.children[c]))
            path.append(node.children[key])
            return keys.index(key)

        x = evaluate(dispatch_plan(ci, seq, None, snapshot, choose=choose))
        lo, hi = min(lo, x), max(hi, x)
        for node in path:
            node.visits += 1
            node.total += x
            node.best = min(node.best, x)
        return reached

    def out_of_time() -> bool:
        return params.time_limit is not None and time.perf_counter() - start >= params.time_limit

    wall_limited = False
    while True:
        done = False
        for _ in range(params.iterations):
            if out_of_time():
                wall_limited = True
                break
            if not iterate():
                done = True
                break
        if done or wall_limited or not root.children:
            break
        key = min(root.children, key=lambda c: root.children[c].best)  # first in expansion order on ties
        prefix.append(key)
        root = root.children[key]
    assert best is not None  # the rule plans are always evaluated
    return MctsResult(best[1], best[0][1], evaluations, len(prefix), rollout, wall_limited, best[0][0])


def mcts_planner(objective: Objective = MAKESPAN, params: MctsParams | None = None, change_budget: int | None = None):
    """Planner for the complete rescheduling: planner(ci, snapshot, current_plan) -> new complete plan. The current
    (repaired) plan is the warm start and the reference of the change budget."""

    def planner(ci: CompiledInstance, snapshot: Snapshot, current: Sequence[Assignment]) -> Plan:
        result = solve_mcts(ci, objective, params, snapshot, current, change_budget)
        planner.last = {"evaluations": result.evaluations, "decisions": result.decisions, "value": result.value,
                        "rollout_rule": result.rollout_rule, "over_budget": result.over_budget,
                        "wall_limited": result.wall_limited}
        return result.plan

    return planner
