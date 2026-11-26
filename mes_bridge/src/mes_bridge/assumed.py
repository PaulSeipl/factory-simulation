"""Assumed plates and prints before the nesting (slice 7, task 7.1b; planned nesting flow).

In the MES's planned nesting flow an order reaches the scheduler once it is planned, before DATA_PREP_SECONDARY
nested its secondary parts on a plate of a print. The export then has no carrier for those parts, and the print's
and plate's steps are keyed per order (`order:<id>:<task>`). The thesis format needs carriers and given runs (math/03:
nesting output, never a planner decision), so the bridge assumes them, as the thesis generator's `nest` does (B2):
- one plate per order (its secondary parts),
- the plates in due-date order (then arrival, then id) next-fit into prints of up to `PLATES_PER_PRINT` plates
  (user, 2026-11-24).

`assume_plates` rewrites the problem into the shape of a nested one: placeholder AM jobs and carriers, the per-order
keys renamed to carrier and job keys (`aliases`: new key -> the MES keys it stands for). The schedule is published
under the MES's own keys (`publish_keys`), so the MES matches every step. The real nesting replaces the assumption:
the problem then has the real carriers, an instance change (task 7.4 turns that into a mapping without
re-optimization). Nothing here is shown to users (user, 2026-11-24: not well founded).
"""

from collections import defaultdict
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from mes_bridge.api import (
    ProblemAssignmentOut,
    ProblemCarrierOut,
    ProblemJobOut,
    ProblemOperationOut,
    ProblemOut,
    ProblemPartOut,
    ProblemTaskOut,
)
from mes_bridge.instance import MappingError

# Plates per print: the MES printers' build plate slots (AmSystem.max_build_plate_slots, 4 in the seed and at
# Fidentis); the export does not carry it yet.
PLATES_PER_PRINT = 4
PRINT_TASKS = frozenset({"AM_PREP", "PART_POWDER_REMOVAL"})  # one operation per print (job key)
# per plate (carrier key): the MES's CARRIER_STEPS
PLATE_TASKS = frozenset(
    {
        "PART_CLEANING",
        "HEAT_TREATMENT",
        "SAND_BLASTING",
        "MILL_PREP_SECONDARY",
        "SECONDARY_PLATE_REMOVAL",
        "REWORK",
        "REWORK_CHECKOUT",
        "SAWING",
    }
)
_NS = uuid5(NAMESPACE_URL, "mes-bridge/assumed-print")

Aliases = dict[str, list[str]]


def assumed_print_id(orders: list[UUID]) -> UUID:
    """A stable id for the print assumed for these orders (the same grouping gives the same id on every refresh)."""
    return uuid5(_NS, ",".join(str(o) for o in orders))


def assume_plates(problem: ProblemOut) -> tuple[ProblemOut, Aliases]:
    """The problem with assumed plates and prints for secondary parts on no plate, and the renamed keys."""
    inst = problem.instance
    loose = [p for p in inst.parts if p.part_type == "SECONDARY" and p.carrier is None]
    if not loose:
        return problem, {}
    by_order: dict[UUID, list[ProblemPartOut]] = defaultdict(list)
    for p in loose:
        by_order[p.order_id].append(p)
    orders = {o.id: o for o in inst.orders}

    def due_first(o: UUID) -> tuple[date, float, str]:
        arrival = orders[o].arrival
        return orders[o].due_date or date.max, arrival.timestamp() if arrival else float("inf"), str(o)

    queue = sorted(by_order, key=due_first)
    groups = [queue[i : i + PLATES_PER_PRINT] for i in range(0, len(queue), PLATES_PER_PRINT)]

    plate_of: dict[UUID, tuple[UUID, str]] = {}  # order -> (assumed print, quadrant)
    jobs, carriers = [], []
    for group in groups:
        job = assumed_print_id(group)
        jobs.append(ProblemJobOut(id=job, kind="AM", equipment_id=None, estimated_duration_minutes=None,
                                  build_plate_set_id=None))  # fmt: skip
        for i, o in enumerate(group, start=1):
            plate_of[o] = (job, str(i))
            carriers.append(
                ProblemCarrierOut(
                    key=f"{job}:{i}",
                    am_job_id=job,
                    quadrant=str(i),
                    part_ids=sorted(p.id for p in by_order[o]),
                    mill_job_id=None,
                )
            )

    rename: dict[str, str] = {}
    for op in inst.operations:
        kind, _, rest = op.key.partition(":")
        if kind != "order":
            continue
        order = UUID(rest.split(":", 1)[0])
        if order not in plate_of or op.task_type not in PRINT_TASKS | PLATE_TASKS:
            continue
        job, quadrant = plate_of[order]
        rename[op.key] = (
            f"job:{job}:{op.task_type}" if op.task_type in PRINT_TASKS else f"carrier:{job}:{quadrant}:{op.task_type}"
        )

    aliases: Aliases = defaultdict(list)
    merged: dict[str, list[ProblemOperationOut]] = defaultdict(list)
    for op in inst.operations:
        new = rename.get(op.key, op.key)
        merged[new].append(op)
        if op.key in rename:
            aliases[new].append(op.key)
    operations = [
        _merge(key, group, rename)
        if key in aliases
        else group[0].model_copy(update={"predecessors": sorted({rename.get(d, d) for d in group[0].predecessors})})
        for key, group in merged.items()
    ]

    parts = [
        p.model_copy(update={"carrier": f"{plate_of[p.order_id][0]}:{plate_of[p.order_id][1]}"})
        if p.part_type == "SECONDARY" and p.carrier is None
        else p
        for p in inst.parts
    ]
    out = problem.model_copy(
        update={
            "instance": inst.model_copy(
                update={
                    "operations": operations,
                    "parts": parts,
                    "jobs": [*inst.jobs, *jobs],
                    "carriers": [*inst.carriers, *carriers],
                    "assignments": _assignments(inst.assignments, rename),
                }
            ),
            "snapshot": problem.snapshot.model_copy(update={"tasks": _tasks(problem.snapshot.tasks, rename)}),
        }
    )
    return out, {k: sorted(v) for k, v in aliases.items()}


def _merge(key: str, group: list[ProblemOperationOut], rename: dict[str, str]) -> ProblemOperationOut:
    """One operation for the per-order operations an assumed key stands for: a print's (several orders) takes the
    longest run and every order's predecessors; a plate's is one order's, renamed. Its job is the assumed print."""
    first = group[0]
    preds = sorted({rename.get(d, d) for o in group for d in o.predecessors} - {key})
    return first.model_copy(
        update={
            "key": key,
            "order_ids": sorted({o for op in group for o in op.order_ids}),
            "job_id": UUID(key.split(":")[1]),
            "predecessors": preds,
            "attended_minutes": max(o.attended_minutes for o in group),
            "unattended_minutes": max(o.unattended_minutes for o in group),
            "machine_options": sorted({m for o in group for m in o.machine_options}),
            "delay_minutes": max(o.delay_minutes for o in group),
            "done": all(o.done for o in group),
        }
    )


def _assignments(rows: list[ProblemAssignmentOut], rename: dict[str, str]) -> list[ProblemAssignmentOut]:
    """Assignments under the new keys; for a print assumed over several orders, the first order's (key order)."""
    out: dict[str, ProblemAssignmentOut] = {}
    for a in sorted(rows, key=lambda a: a.key):
        new = rename.get(a.key, a.key)
        out.setdefault(new, a.model_copy(update={"key": new}))
    return sorted(out.values(), key=lambda a: a.key)


def _tasks(rows: list[ProblemTaskOut], rename: dict[str, str]) -> list[ProblemTaskOut]:
    """Started tasks under the new keys. A print or plate step cannot have started before its nesting; two tasks on
    one assumed key mean the MES did something the assumption does not cover."""
    out: dict[str, ProblemTaskOut] = {}
    for t in rows:
        new = rename.get(t.key, t.key)
        if new in out:
            raise MappingError(f"{new}: two started tasks on one assumed step ({out[new].key}, {t.key})")
        out[new] = t.model_copy(update={"key": new})
    return list(out.values())


def publish_keys(key: str, aliases: Aliases) -> list[str]:
    """The MES keys a schedule step is published under: the per-order keys an assumed key stands for, else itself."""
    return aliases.get(key, [key])
