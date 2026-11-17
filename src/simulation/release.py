"""Order release: which orders of the pool nesting binds at a nesting time (math/33_order-release-interface.md).

The pool holds the accepted, not yet bound orders. A rule takes them in nesting order (due date, then release, then
index, as `carrier_generator.nest`) and binds while the budget allows; the rest wait for the next nesting time with
their due dates unchanged. The load of an order is passed in, so that the same rule works with a budget in
telescopes (open loop, step A) or in estimated mill minutes from the plan (closed loop, step B).
"""

from collections.abc import Callable, Sequence
from typing import NamedTuple


class PoolOrder(NamedTuple):
    id: str
    accepted: int
    due_date: int
    index: int  # position in the instance (last tie-breaker, as in nest)


def release(pool: Sequence[PoolOrder], budget: float | None, load: Callable[[PoolOrder], float],
            next_nesting: int | None) -> list[str]:
    """IDs of the orders bound now, in nesting order.

    Timing: an order whose due date is not after the next nesting time (`next_nesting`; None: none follows) is bound
    regardless of the budget, so an order never arrives after its due date (V10). Balancing: the others in nesting
    order while their load fits the rest of `budget` (None: no limit); an order that does not fit is skipped and a
    smaller later one may take its place (user 2026-11-17). An order larger than the whole budget is bound, and takes
    the whole budget, as soon as it alone has the earliest due date of the rest of the pool (user 2026-11-17);
    while another order shares that due date, the others go first. Starvation: if nothing is bound, the first order
    is."""
    ordered = sorted(pool, key=lambda o: (o.due_date, o.accepted, o.index))
    forced = [o for o in ordered if next_nesting is None or o.due_date <= next_nesting]
    used = sum(load(o) for o in forced)
    bound = {o.id for o in forced}
    rest = [o for o in ordered if o.id not in bound]
    if budget is not None and rest and load(rest[0]) > budget and (
            len(rest) == 1 or rest[1].due_date > rest[0].due_date):
        bound.add(rest[0].id)  # the whole budget: no balancing after it
    else:
        for o in rest:
            if budget is None or used + load(o) <= budget:
                bound.add(o.id)
                used += load(o)
    if not bound and ordered:
        bound.add(ordered[0].id)
    return [o.id for o in ordered if o.id in bound]
