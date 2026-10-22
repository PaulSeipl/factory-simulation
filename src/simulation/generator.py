"""Random instance generator (math/21_instance-generator.md).

Deterministic per seed. The parameters are stored as a separate JSON next to the instance,
so that every generated instance can be reproduced.
"""

import random
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt, model_validator

from simulation.model.instance import Instance

type RoutingMode = Literal["chain", "split", "join", "split_join"]
MIN_LENGTH: dict[str, int] = {"chain": 1, "split": 3, "join": 3, "split_join": 4}  # head/tail + 2 branches


class TemplateOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    predecessors: tuple[str, ...] = ()
    options: dict[str, PositiveInt] | None = None  # machine -> duration; generated if None


class OrderTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    operations: tuple[TemplateOperation, ...] = Field(min_length=1)


class GeneratorParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    name: str | None = None  # default: derived from the parameters
    n_machines: PositiveInt
    n_orders: PositiveInt  # including template orders
    n_operations: PositiveInt  # including template operations
    min_order_length: PositiveInt = 1
    max_machines_per_op: PositiveInt = 1  # eligible machines per operation: uniform in 1..max
    duration_range: tuple[PositiveInt, PositiveInt] = (1, 10)  # base duration of an operation
    max_duration_spread: NonNegativeInt = 0  # duration on a machine: base + uniform in 0..spread
    release_range: tuple[NonNegativeInt, NonNegativeInt] = (0, 0)
    routing_modes: tuple[RoutingMode, ...] = Field(default=("chain",), min_length=1)
    max_branches: int = Field(default=2, ge=2)
    templates: tuple[OrderTemplate, ...] = ()

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        for lo, hi, what in (*self.duration_range, "duration_range"), (*self.release_range, "release_range"):
            if lo > hi:
                raise ValueError(f"{what}: min {lo} > max {hi}")
        if self.max_machines_per_op > self.n_machines:
            raise ValueError(f"max_machines_per_op {self.max_machines_per_op} > n_machines {self.n_machines}")
        if (need := max(MIN_LENGTH[m] for m in self.routing_modes)) > self.min_order_length:
            raise ValueError(f"routing modes {list(self.routing_modes)} need min_order_length >= {need}")
        generated_orders = self.n_orders - len(self.templates)
        generated_ops = self.n_operations - sum(len(t.operations) for t in self.templates)
        if generated_orders < 0 or generated_ops < generated_orders * self.min_order_length:
            raise ValueError(
                f"{generated_ops} operations cannot fill {generated_orders} generated orders "
                f"with at least {self.min_order_length} operations each"
            )
        if generated_orders == 0 and generated_ops > 0:
            raise ValueError(f"{generated_ops} operations left but no generated order to hold them")
        return self

    def default_name(self) -> str:
        return f"gen-m{self.n_machines}-k{self.n_orders}-o{self.n_operations}-s{self.seed}"


def generate_instance(params: GeneratorParams) -> Instance:
    rng = random.Random(params.seed)
    machines = [f"M{i}" for i in range(1, params.n_machines + 1)]

    def options() -> dict[str, int]:
        base = rng.randint(*params.duration_range)
        eligible = rng.sample(machines, rng.randint(1, params.max_machines_per_op))
        return {m: base + rng.randint(0, params.max_duration_spread) for m in sorted(eligible, key=machines.index)}

    orders = []
    for i, template in enumerate(params.templates, 1):
        ops = [{"id": t.id, "step": t.id, "options": t.options or options(), "predecessors": list(t.predecessors)}
               for t in template.operations]
        orders.append({"id": f"T{i}", "release": rng.randint(*params.release_range), "operations": ops})

    n_generated = params.n_orders - len(params.templates)
    lengths = [params.min_order_length] * n_generated
    for _ in range(params.n_operations - sum(len(t.operations) for t in params.templates) - sum(lengths)):
        lengths[rng.randrange(n_generated)] += 1
    for i, length in enumerate(lengths, 1):
        mode = rng.choice(params.routing_modes)
        preds = _precedence(mode, length, params.max_branches, rng)
        ops = [{"id": str(j), "step": f"op{j}", "options": options(), "predecessors": [str(q) for q in preds[j]]}
               for j in range(1, length + 1)]
        orders.append({"id": f"O{i}", "release": rng.randint(*params.release_range), "operations": ops})

    return Instance.model_validate({
        "schema_version": "0.2",
        "name": params.name or params.default_name(),
        "machines": machines,
        "orders": orders,
    })


def _precedence(mode: str, n: int, max_branches: int, rng: random.Random) -> dict[int, list[int]]:
    """Predecessors of operations 1..n for one order."""
    preds: dict[int, list[int]] = {j: [] for j in range(1, n + 1)}
    if mode == "chain":
        for j in range(2, n + 1):
            preds[j] = [j - 1]
        return preds

    head = 1 if mode in ("split", "split_join") else None
    tail = n if mode in ("join", "split_join") else None
    middle = [j for j in range(1, n + 1) if j not in (head, tail)]
    k = rng.randint(2, min(max_branches, len(middle)))
    cuts = sorted(rng.sample(range(1, len(middle)), k - 1))  # k non-empty consecutive branches
    branches = [middle[a:b] for a, b in zip([0, *cuts], [*cuts, len(middle)], strict=True)]
    for branch in branches:
        for a, b in zip(branch, branch[1:], strict=False):
            preds[b] = [a]
        if head is not None:
            preds[branch[0]] = [head]
    if tail is not None:
        preds[tail] = [branch[-1] for branch in branches]
    return preds
