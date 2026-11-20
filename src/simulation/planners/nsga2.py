"""NSGA-II over the GA's random keys (math/14_genetic-algorithm.md §3a): an offline trade-off analysis, not a planner.

The chromosome and the decoder are those of the BRKGA (`ga.decode`), so every chromosome is a feasible plan. Instead
of one objective, a vector of objectives (e.g. tardiness, overtime, makespan) is minimized, and the result is the set
of non-dominated plans: no plan in it is at least as good in every objective and better in one.

One generation (Deb et al. 2002, pp. 185-186): binary tournaments by the crowded-comparison operator (lower front
first, then larger crowding distance) pick parents; children by uniform crossover and key mutation (own choice for
random keys; the source runs real- and binary-coded variants on continuous test functions, math/14); parents and
children together (2N) are sorted into fronts, and the next N are filled front by front, the last front cut by
crowding distance.
"""

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Plan
from simulation.objectives import Objective
from simulation.planners.ga import N_KEYS, Chromosome, decode, encode, rule_plans

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot

type Values = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NsgaParams:
    population: int = 100  # N (own choice)
    crossover: float = 0.9  # probability that a child is a crossover of its parents, else a copy of the first (own)
    mutation: float | None = None  # probability per key of a new random key; None: 1 / number of keys (own)
    delay_max: int = 100  # D^max, as in the BRKGA
    generations: int | None = None
    time_limit: float | None = 60.0  # seconds, checked after every decode
    seed: int = 0

    def __post_init__(self):
        if self.generations is None and self.time_limit is None:
            raise ValueError("give a generation limit, a time limit or both")
        if self.population < 2:
            raise ValueError(f"population {self.population}: needs at least two for a tournament")


@dataclass(frozen=True, slots=True)
class NsgaResult:
    front: list[tuple[Values, Plan]]  # non-dominated plans, one per distinct objective vector, sorted by values
    generations: int
    evaluations: int


def dominates(a: Values, b: Values) -> bool:
    """a is at least as good in every objective and better in one (minimization)."""
    return all(x <= y for x, y in zip(a, b, strict=True)) and a != b


def non_dominated_fronts(values: Sequence[Values]) -> list[list[int]]:
    """Indices sorted into fronts: front 0 is non-dominated, front 1 is non-dominated once front 0 is removed, ...
    (Deb et al. 2002, pp. 183-184: fast non-dominated sorting)."""
    dominated_by = [[] for _ in values]  # i -> the solutions i dominates
    count = [0] * len(values)  # i -> how many solutions dominate i
    for i, a in enumerate(values):
        for j, b in enumerate(values):
            if dominates(a, b):
                dominated_by[i].append(j)
            elif dominates(b, a):
                count[i] += 1
    fronts, current = [], [i for i, c in enumerate(count) if c == 0]
    while current:
        fronts.append(current)
        following = []
        for i in current:
            for j in dominated_by[i]:
                count[j] -= 1
                if count[j] == 0:
                    following.append(j)
        current = sorted(following)
    return fronts


def crowding_distances(front: Sequence[int], values: Sequence[Values]) -> dict[int, float]:
    """Per member: the sum over objectives of the normalized gap between its two neighbours; the extremes of every
    objective get infinity, so they are always kept (Deb et al. 2002, p. 185, Fig. 1; the infinite boundary value is
    not legible in the extracted text of the procedure: uncertain, math/14)."""
    distance = dict.fromkeys(front, 0.0)
    for k in range(len(values[front[0]])):
        ordered = sorted(front, key=lambda i: (values[i][k], i))
        low, high = values[ordered[0]][k], values[ordered[-1]][k]
        distance[ordered[0]] = distance[ordered[-1]] = float("inf")
        if high == low:
            continue
        for prev, mid, nxt in zip(ordered, ordered[1:], ordered[2:], strict=False):  # consecutive triples
            distance[mid] += (values[nxt][k] - values[prev][k]) / (high - low)
    return distance


def nsga2(
    ci: CompiledInstance, objectives: Sequence[Objective], params: NsgaParams | None = None,
    snapshot: "Snapshot | None" = None,
) -> NsgaResult:
    """The non-dominated plans NSGA-II finds within the limits (module docstring). The population starts with the
    rule plans encoded as keys; the rest is random."""
    start, params = time.perf_counter(), params or NsgaParams()
    rng = random.Random(params.seed)
    unit, n_keys = params.delay_max, N_KEYS * ci.n_ops
    p_mut = params.mutation if params.mutation is not None else 1 / n_keys
    evaluations = 0

    def out_of_time() -> bool:
        return params.time_limit is not None and time.perf_counter() - start >= params.time_limit

    def scored(genes: Chromosome) -> tuple[Values, Chromosome, Plan]:
        nonlocal evaluations
        evaluations += 1
        plan = decode(ci, genes, unit, snapshot)
        return tuple(f.evaluate(ci, plan.assignments, plan.breaks) for f in objectives), genes, plan

    def random_vector() -> Chromosome:
        return [rng.random() for _ in range(n_keys)]

    population = []
    for plan in rule_plans(ci, snapshot):  # each rule plan is decoded once to encode it, then decoded as keys
        if population and out_of_time() or len(population) >= params.population:
            break
        evaluations += 1
        population.append(scored(encode(ci, plan.assignments)))
    while len(population) < params.population and not out_of_time():
        population.append(scored(random_vector()))

    def ranked(pop):
        """front index and crowding distance per member."""
        values = [v for v, _, _ in pop]
        rank, crowd = {}, {}
        for r, front in enumerate(non_dominated_fronts(values)):
            rank.update(dict.fromkeys(front, r))
            crowd.update(crowding_distances(front, values))
        return rank, crowd

    def select(pop, rank, crowd) -> Chromosome:
        """Binary tournament by the crowded-comparison operator."""
        i, j = rng.randrange(len(pop)), rng.randrange(len(pop))
        return pop[min(i, j, key=lambda x: (rank[x], -crowd[x], x))][1]

    generation = 0
    while len(population) >= 2 and not (params.generations is not None and generation >= params.generations) \
            and not out_of_time():
        rank, crowd = ranked(population)
        children = []
        while len(children) < params.population:
            a, b = select(population, rank, crowd), select(population, rank, crowd)
            genes = ([x if rng.random() < 0.5 else y for x, y in zip(a, b, strict=True)]
                     if rng.random() < params.crossover else list(a))
            children.append(scored([rng.random() if rng.random() < p_mut else g for g in genes]))
            if out_of_time():
                break
        combined = population + children
        values = [v for v, _, _ in combined]
        survivors = []
        for front in non_dominated_fronts(values):
            if len(survivors) + len(front) <= params.population:
                survivors += front
                continue
            crowd = crowding_distances(front, values)
            survivors += sorted(front, key=lambda i: (-crowd[i], i))[:params.population - len(survivors)]
            break
        population = [combined[i] for i in survivors]
        if len(children) == params.population:
            generation += 1

    values = [v for v, _, _ in population]
    best = {}
    for i in non_dominated_fronts(values)[0]:
        best.setdefault(values[i], population[i][2])
    return NsgaResult(sorted(best.items(), key=lambda vp: vp[0]), generation, evaluations)
