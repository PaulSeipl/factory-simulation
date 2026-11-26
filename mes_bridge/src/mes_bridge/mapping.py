"""After a nesting (slice 7, task 7.4): the current plan's assumed carriers mapped onto the real ones.

In the planned nesting flow the plan holds assumed plates, prints and blanks (`assumed.assume_plates`, one blank per
order: `instance.blank_id`). Once a worker forms the real print (DATA_PREP_SECONDARY) or mill job (DATA_PREP_PRIMARY),
the export names the real carriers: the instance's operations are renamed, not new. A complete rescheduling would
re-optimize the plan unseen (user, 2026-11-24: nothing does that without the planner seeing it), so the plan is
*mapped*: every operation of a real carrier, run or blank takes the machine, workers and start of the assumed one
its parts were on (`map_plan`), and is then re-timed with exactly those (`retime`). The MES shows *Plan update
pending*; the planner's *Update plan* is the thorough re-solve.

Ownership follows the parts, whose ids the nesting keeps: a secondary part's carrier (`C:`, its mill run `M:` and
rework run `RW:`), the carrier's print (`R:`), a primary part's blank (`B:`, its runs `MB:` and `MF:`). One real
owner may get several assumed ones (plates of two assumed prints on one real print): it takes the one planned first.

Why re-time with the dispatcher and not the shift repair: the real grouping need not match the assumed one. An
assumed print of three plates may become a real print of two and a new assumed print for the third; both inherit
the assumed print's slot and printer, and their downstream steps interleave with other orders' on shared machines
and workers. The shift repair keeps the order per machine and worker by planned start and fails on such a plan
(found with the recordings: two runs overlapping on the printer, a run straddling another on the mill, a cycle).
The dispatcher (`dispatch_plan`, the rules' and the GA's decoder) always gives a feasible plan; with every operation
narrowed to its mapped machine and worker, released at its mapped start and ranked by it, it keeps the assignment
and the order and only moves what must move, later.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment, Plan
from simulation.planners.dispatching import dispatch_plan
from simulation.sim.snapshot import Snapshot

from mes_bridge.api import ProblemOut, ProblemPartOut
from mes_bridge.instance import blank_id, blank_run, carrier_id, flip_run, mill_run, print_run, rework_run


def _owners_of(p: ProblemPartOut) -> list[str]:
    """The instance owners a part's operations belong to (its carrier chain, or its blank); none for a secondary part
    on no plate."""
    if p.part_type == "SECONDARY":
        if p.carrier is None:
            return []
        job = p.carrier.split(":", 1)[0]
        return [carrier_id(p.carrier), mill_run(p.carrier), rework_run(p.carrier), print_run(job)]
    b = blank_id(p.order_id if p.mill_job_id is None else p.mill_job_id)  # the order's assumed blank until data prep
    return [b, blank_run(b), flip_run(b)]


def successors(old: ProblemOut, new: ProblemOut) -> dict[str, set[str]]:
    """New owner -> the old owners its parts were on (only owners that changed)."""
    before = {p.id: p for p in old.instance.parts}
    out: dict[str, set[str]] = defaultdict(set)
    for p in new.instance.parts:
        if (q := before.get(p.id)) is None or not (was_owners := _owners_of(q)) or not (now_owners := _owners_of(p)):
            continue
        for was, now in zip(was_owners, now_owners, strict=True):
            if was != now:
                out[now].add(was)
    return out


def map_plan(
    plan: Sequence[Assignment], old: ProblemOut, new: ProblemOut, ci: CompiledInstance
) -> list[Assignment] | None:
    """The plan over `ci`'s operations with the assumed owners replaced by the real ones (times, machine and workers
    of the assumed operation; not yet feasible), or None if the change is more than a renaming (an operation no
    assumed one covers: an arrival, a cancellation, a rework)."""
    succ = successors(old, new)
    if not succ:  # nothing was renamed: not a nesting
        return None
    by_key = {(a.order_id, a.op_id): a for a in plan}
    first: dict[str, int] = defaultdict(lambda: 2**62)
    for a in plan:
        first[a.order_id] = min(first[a.order_id], a.start)
    chosen = {now: min(was, key=lambda o: (first[o], o)) for now, was in succ.items()}
    out = []
    for owner, op in ci.op_keys:
        a = by_key.get((owner, op))
        if a is None and owner in chosen and (a := by_key.get((chosen[owner], op))) is not None:
            a = a.model_copy(update={"order_id": owner, "batch": None})  # the dispatcher forms the s-batches anew
        if a is None:
            return None
        out.append(a)
    return out


def retime(ci: CompiledInstance, snapshot: Snapshot, mapped: Sequence[Assignment]) -> Plan:
    """A feasible plan that keeps the mapped plan's machines, workers and order: the dispatcher over `ci` narrowed to
    them, each operation released at its mapped start (nothing moves earlier, as in a repair) and ranked by it; ties
    (the plates of one assumed print, now on two) go to the earlier due date. A machine or worker the operation can
    no longer use (the real print bound to another printer, say) is left open to the dispatcher's choice."""
    at = {ci.op_index[a.order_id, a.op_id]: a for a in mapped}
    machine_of = {m: i for i, m in enumerate(ci.machine_ids)}
    worker_of = {w: i for i, w in enumerate(ci.worker_ids)}
    options, shares, release = list(ci.options), list(ci.shares), list(ci.release)
    for o, a in at.items():
        m = machine_of.get(a.machine) if a.machine is not None else None
        group = next((g for g in ci.machine_groups if o in g), (o,))
        if m is not None and all(any(opt[0] == m for opt in options[g]) for g in group):
            for g in group:  # a run's operations share its machine
                options[g] = tuple(opt for opt in options[g] if opt[0] == m)
        if a.workers and len(a.workers) == len(shares[o]):
            narrowed = []
            for sh, w in zip(shares[o], a.workers, strict=True):
                z = worker_of.get(w)
                narrowed.append(sh._replace(workers=(z,)) if z is not None and z in sh.workers else sh)
            shares[o] = tuple(narrowed)
        release[o] = max(release[o], a.start)
    narrow = replace(ci, options=tuple(options), shares=tuple(shares), release=tuple(release))
    due = [min((d for k in ci.op_orders[o] if (d := ci.due_date[k]) is not None), default=2**62) for o in range(ci.n_ops)]

    def by_mapped_start(_ci, _state, o, _m, _p):
        return (at[o].start if o in at else 2**62, due[o], o)

    return dispatch_plan(narrow, by_mapped_start, None, snapshot)
