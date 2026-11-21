"""Biased random-key genetic algorithm (BRKGA) with the dispatcher as decoder (math/14_genetic-algorithm.md).

A chromosome is a vector of 5|O| keys in [0, 1) (Bean 1994): per operation a priority key, a machine key, a delay key,
an overtime key and a join key. `decode` turns any vector into a feasible plan through `dispatch_plan`: the priority key is the
sequencing rule (smaller first), the machine key picks the machine from M_o, delay key ζ lets scheduling iteration ζ
look D_ζ = (D^max + 1)^key - 1 minutes past the earliest start (parameterized active schedules, Gonçalves et al. 2005;
the logarithmic map is own: most keys give a few minutes), and
the overtime key lets o's shares run up to key · max overtime past shift end (own), and a join key of at least 1/2 keeps
o out of other operations' s-batches (own; 0, as encoded, joins like the rules). So no operator needs repair:
every child is a valid vector and decodes to a feasible plan. From a snapshot the decoder keeps the frozen part.

One generation (Gonçalves et al. 2011): the N^el best are copied, N^mut new random vectors are added, the rest are
children of an elite and a non-elite parent, each key from the elite parent with probability α^in. The population
starts with the current plan (warm start, rescheduling) and the rule plans encoded as keys; the best rule plan is the
first incumbent, so the result is never worse than the best rule under the objective. With a change budget a plan
ranks first by its machine changes beyond the budget, then by the objective; the encoded current plan keeps every
machine, so a plan within the budget is always in the population.
"""

import random
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Plan
from simulation.objectives import MAKESPAN, Objective
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot

type Chromosome = list[float]
type Rank = tuple[int, int]  # (machine changes beyond the budget, objective value), smaller is better
N_KEYS = 5  # keys per operation: priority, machine, delay, overtime, join


@dataclass(frozen=True, slots=True)
class GaParams:
    population: int = 100  # N^pop (own choice)
    elite: float = 0.1  # N^el / N^pop (Gonçalves et al. 2011, p. 478: TOP 10 %)
    mutants: float = 0.2  # N^mut / N^pop (ibid.: BOT 20 %)
    inherit: float = 0.7  # α^in, probability of a key from the elite parent (ibid.: CProb 0.7)
    delay_max: int = 100  # D^max, minutes of the longest delay (user 2026-11-20; median key 0.5 gives 9 minutes)
    join: bool = True  # False: the join keys are ignored, every partner joins (greedy, as the rules; for comparisons)
    generations: int | None = None  # stop after this many generations; None: only the time limit
    time_limit: float | None = 10.0  # seconds, checked after every decode; None: only the generation limit
    seed: int = 0

    def __post_init__(self):
        if self.generations is None and self.time_limit is None:
            raise ValueError("give a generation limit, a time limit or both")
        n_el, n_mut = self.n_elite, self.n_mutants
        if n_el < 1 or n_el + n_mut >= self.population:
            raise ValueError(f"population {self.population}: needs at least one elite and one child "
                             f"(elite {n_el}, mutants {n_mut})")

    @property
    def n_elite(self) -> int:
        return round(self.elite * self.population)

    @property
    def n_mutants(self) -> int:
        return round(self.mutants * self.population)


@dataclass(frozen=True, slots=True)
class GaResult:
    plan: Plan
    value: int  # objective value of the plan
    generations: int  # completed generations
    evaluations: int  # decoded plans (rule plans and chromosomes)
    history: tuple[int, ...]  # incumbent's value after the seeding and after every generation
    over_budget: int = 0  # machine changes beyond the change budget (0 unless no plan within it was decoded)


def delay(key: float, delay_max: int) -> int:
    """D_ζ = round((D^max + 1)^key - 1): 0 at key 0, D^max at key 1, logarithmic in between."""
    return round((delay_max + 1) ** key - 1)


def decode(ci: CompiledInstance, genes: Sequence[float], delay_max: int, snapshot: Snapshot | None = None,
           join: bool = True) -> Plan:
    """The feasible plan of a chromosome (module docstring); from a snapshot with its frozen part. `join` False:
    the join keys are ignored, every partner joins."""
    n = ci.n_ops
    seq, mach = genes[:n], genes[n:2 * n]

    def sequencing(_ci, _state, o, _m, _p):
        return (seq[o],)

    def assignment(_ci, _state, o):
        opts = ci.options[o]
        return opts[int(mach[o] * len(opts))][0]

    max_ot = ci.calendar.max_overtime if ci.calendar is not None else 0
    return dispatch_plan(ci, sequencing, assignment, snapshot, delay=[delay(g, delay_max) for g in genes[2 * n:3 * n]],
                         overtime=[round(g * max_ot) for g in genes[3 * n:4 * n]],
                         join=[g < 0.5 for g in genes[4 * n:5 * n]] if join else None)


def encode(ci: CompiledInstance, plan: Sequence[Assignment]) -> Chromosome:
    """Keys that rank the plan's operations by start, pick its machines, wait nowhere, plan no overtime and join every
    s-batch (delay, overtime and join keys 0). Operations the plan lacks (arrived since) rank after all others, machine key 0.5. Decoding the
    keys need not give the plan back exactly: the decoder only reproduces what a non-delay pass reaches."""
    n = ci.n_ops
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in plan}
    order = sorted(range(n), key=lambda o: (o not in by_op, by_op[o].start if o in by_op else 0, o))
    rank = {o: i for i, o in enumerate(order)}
    mach = []
    for o in range(n):
        ms = [m for m, _ in ci.options[o]]
        a = by_op.get(o)
        m = ci.machine_index.get(a.machine) if a is not None and a.machine is not None else None
        mach.append((ms.index(m) + 0.5) / len(ms) if m in ms else 0.5)
    return [(rank[o] + 0.5) / n for o in range(n)] + mach + [0.0] * (3 * n)


def rule_plans(ci: CompiledInstance, snapshot: Snapshot | None = None) -> Iterator[Plan]:
    """All sequencing x (assignment + joint) rule plans, as in best_dispatch; lazily, so a time limit can stop them."""
    return (dispatch_plan(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None, snapshot)
            for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None])


def solve_ga(
    ci: CompiledInstance, objective: Objective, params: GaParams | None = None, snapshot: Snapshot | None = None,
    current: Sequence[Assignment] | None = None, change_budget: int | None = None,
) -> GaResult:
    """The best plan the BRKGA finds within the limits (module docstring). `current`: the plan to start from (warm
    start) and the reference of `change_budget` (machine changes of operations it plans that are not frozen)."""
    start, params = time.perf_counter(), params or GaParams()
    rng = random.Random(params.seed)
    unit, n_keys = params.delay_max, N_KEYS * ci.n_ops
    frozen = {(f.order_id, f.op_id) for f in snapshot.frozen} if snapshot else set()
    before = {(a.order_id, a.op_id): a.machine for a in current or ()}
    evaluations = 0

    def out_of_time() -> bool:
        return params.time_limit is not None and time.perf_counter() - start >= params.time_limit

    def rank(plan: Plan) -> Rank:
        nonlocal evaluations
        evaluations += 1
        over = 0
        if change_budget is not None and current is not None:
            changed = sum(a.machine != before[k] for a in plan.assignments
                          if (k := (a.order_id, a.op_id)) in before and k not in frozen)
            over = max(0, changed - change_budget)
        return over, objective.evaluate(ci, plan.assignments, plan.breaks)

    def scored(genes: Chromosome) -> tuple[Rank, Chromosome, Plan]:
        plan = decode(ci, genes, unit, snapshot, params.join)
        return rank(plan), genes, plan

    def random_vector() -> Chromosome:
        return [rng.random() for _ in range(n_keys)]

    # seeding, each decode followed by a time check: the current plan first, then the rule plans, then random vectors
    population = [scored(encode(ci, current))] if current is not None else []
    if population:
        best_rank, best_plan = population[0][0], population[0][2]
    else:
        best_rank, best_plan = (1 << 62, 0), None
    for plan in rule_plans(ci, snapshot):
        if best_plan is not None and out_of_time():
            break
        if (r := rank(plan)) < best_rank:
            best_rank, best_plan = r, plan
        if len(population) < params.population and not out_of_time():
            population.append(scored(encode(ci, plan.assignments)))
    while len(population) < params.population and not out_of_time():
        population.append(scored(random_vector()))
    population.sort(key=lambda s: s[0])  # stable: ties keep their order, so a seed gives one result
    history, generation = [], 0

    def improve() -> None:
        nonlocal best_rank, best_plan
        if population and population[0][0] < best_rank:
            best_rank, best_plan = population[0][0], population[0][2]
        history.append(best_rank[1])

    improve()
    n_el, n_mut = params.n_elite, params.n_mutants

    def stop() -> bool:
        return (len(population) <= n_el or (params.generations is not None and generation >= params.generations)
                or out_of_time())

    while not stop():
        elite, rest = population[:n_el], population[n_el:]
        children = []
        for i in range(params.population - n_el):
            if i < n_mut:
                genes = random_vector()
            else:
                a, b = rng.choice(elite)[1], rng.choice(rest)[1]
                genes = [x if rng.random() < params.inherit else y for x, y in zip(a, b, strict=True)]
            children.append(scored(genes))
            if out_of_time():  # a cut generation: its children compete with the old population
                break
        if len(children) < params.population - n_el:
            population = sorted(population + children, key=lambda s: s[0])[:params.population]
        else:
            population = sorted(elite + children, key=lambda s: s[0])
            generation += 1
        improve()
    assert best_plan is not None  # the first rule plan is always decoded
    return GaResult(best_plan, best_rank[1], generation, evaluations, tuple(history), best_rank[0])


def ga_planner(objective: Objective = MAKESPAN, params: GaParams | None = None, change_budget: int | None = None):
    """Planner for the complete rescheduling: planner(ci, snapshot, current_plan) -> new complete plan. The current
    (repaired) plan is the warm start and the reference of the change budget. Use a time limit in the DES."""

    def planner(ci: CompiledInstance, snapshot: Snapshot, current: Sequence[Assignment]) -> Plan:
        result = solve_ga(ci, objective, params, snapshot, current, change_budget)
        planner.last = {"generations": result.generations, "evaluations": result.evaluations,
                        "value": result.value, "over_budget": result.over_budget}
        return result.plan

    return planner
