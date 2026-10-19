from collections import Counter
from graphlib import CycleError, TopologicalSorter
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)


def _duplicates(ids) -> list[str]:
    return sorted(k for k, n in Counter(ids).items() if n > 1)


class Operation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str  # unique inside an order; globally (order.id, op.id)
    step: str  # process step like "print"; may repeat within and across orders
    # Machine ID -> duration.
    # shortcut: dict stays mutable despite frozen=True,
    # switch to frozendict once on Python >= 3.15 (pydantic >= 2.14 supports it)
    options: dict[str, PositiveInt] = Field(min_length=1)
    predecessors: tuple[str, ...] = ()  # op IDs of the same order


class Order(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    release: NonNegativeInt = 0  # earliest start time
    operations: tuple[Operation, ...]


class Instance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["0.2"]
    name: str
    time_unit: Literal["s", "min", "h"] = "min"
    machines: tuple[str, ...]
    orders: tuple[Order, ...]

    @model_validator(mode="after")
    def check_references(self):
        if dups := _duplicates(self.machines):
            raise ValueError(f"duplicate machine IDs: {dups}")
        if dups := _duplicates(o.id for o in self.orders):
            raise ValueError(f"duplicate order IDs: {dups}")
        machines = set(self.machines)
        for order in self.orders:
            local = [op.id for op in order.operations]
            if dups := _duplicates(local):
                raise ValueError(f"order {order.id}: duplicate operation IDs: {dups}")
            for op in order.operations:
                if unknown := sorted(set(op.options) - machines):
                    raise ValueError(
                        f"order {order.id}, op {op.id}: unknown machines {unknown}"
                    )
                if dups := _duplicates(op.predecessors):
                    raise ValueError(
                        f"order {order.id}, op {op.id}: duplicate predecessors {dups}"
                    )
                if unknown := sorted(set(op.predecessors) - set(local)):
                    raise ValueError(
                        f"order {order.id}, op {op.id}: unknown predecessors {unknown}"
                        " (must be operation IDs of the same order)"
                    )
            # after the reference check: prepare() would silently add unknown nodes
            graph = {op.id: op.predecessors for op in order.operations}
            try:
                TopologicalSorter(graph).prepare()
            except CycleError as e:
                raise ValueError(
                    f"order {order.id}: cycle in predecessors: {' -> '.join(e.args[1])}"
                ) from e
        return self
