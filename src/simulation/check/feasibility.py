"""Feasibility checker for the base model (math/01_basic-fjsp.md, C1-C5) and revised plans (math/05, C6-C7).

Written independently of every planner and solver: it only reads the compiled
instance and the assignments, and reports every violated constraint. Test oracle
for CP-SAT, the DES, dispatching rules and the GA. Objective-agnostic on purpose.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simulation.model.compiled import CompiledInstance, OpKey
from simulation.model.schedule import Assignment

if TYPE_CHECKING:
    from simulation.sim.snapshot import FrozenOperation, Snapshot


@dataclass(frozen=True, slots=True)
class Violation:
    constraint: str  # "C1".."C5" (math/01), "C6", "C7" (math/05); "C0" = operation not in the instance
    ops: tuple[OpKey, ...]
    message: str


def check_schedule(
    ci: CompiledInstance, assignments: Iterable[Assignment], snapshot: Snapshot | None = None
) -> list[Violation]:
    """Return all violations; an empty list means the schedule is feasible.

    With a snapshot (a plan revised at time snapshot.t), the frozen operations must appear exactly as in
    the snapshot (C7, realized or expected times, so C2 is not checked for them) and no other operation
    may start before snapshot.t (C6).
    """
    by_op, violations = assigned_exactly_once(ci, assignments)
    frozen = {ci.op_index[f.order_id, f.op_id]: f for f in snapshot.frozen} if snapshot else {}
    for o, a in by_op.items():
        key = ci.op_keys[o]
        p_of = {ci.machine_ids[m]: p for m, p in ci.options[o]}
        found = [
            not_eligible(key, a.machine, p_of)
            or (None if o in frozen else wrong_duration(key, a, p_of[a.machine])),
            *starts_before_predecessors(ci, o, a, by_op),
            starts_before_release(key, a.start, ci.release[o]),
            frozen_changed(key, a, frozen[o]) if o in frozen else None,
            starts_before_t(key, a.start, snapshot.t) if snapshot and o not in frozen else None,
        ]
        violations += [v for v in found if v]
    return violations + machine_overlaps(ci, by_op)


def assigned_exactly_once(
    ci: CompiledInstance, assignments: Iterable[Assignment]
) -> tuple[dict[int, Assignment], list[Violation]]:
    """C1 (sum_m x_om = 1): every operation exactly once; C0: no unknown operations."""
    by_op: dict[int, Assignment] = {}
    violations = []
    for a in assignments:
        key = (a.order_id, a.op_id)
        o = ci.op_index.get(key)
        if o is None:
            violations.append(Violation("C0", (key,), f"{key} is not an operation of the instance"))
        elif o in by_op:
            violations.append(Violation("C1", (key,), f"{key} assigned more than once"))
        else:
            by_op[o] = a
    violations += [Violation("C1", (key,), f"{key} is not assigned")
                   for o, key in enumerate(ci.op_keys) if o not in by_op]
    return by_op, violations


def not_eligible(key: OpKey, machine: str, p_of: Mapping[str, int]) -> Violation | None:
    """C1: the machine is in M_o (an unknown machine is never in M_o)."""
    if machine not in p_of:
        return Violation("C1", (key,), f"{key} on {machine}, eligible: {sorted(p_of)}")
    return None


def wrong_duration(key: OpKey, a: Assignment, p: int) -> Violation | None:
    """C2: C_o - S_o = p_{o,m} of the assigned machine."""
    if a.end - a.start != p:
        return Violation("C2", (key,), f"{key}: end - start = {a.end - a.start}, p = {p} on {a.machine}")
    return None


def starts_before_predecessors(
    ci: CompiledInstance, o: int, a: Assignment, by_op: Mapping[int, Assignment]
) -> list[Violation]:
    """C3: S_o >= C_q for every predecessor q (a missing q is already reported under C1)."""
    violations = []
    for q in ci.predecessors[o]:
        if (b := by_op.get(q)) is not None and a.start < b.end:
            pred, key = ci.op_keys[q], ci.op_keys[o]
            violations.append(Violation("C3", (pred, key),
                                        f"{key} starts at {a.start} before predecessor {pred} ends at {b.end}"))
    return violations


def starts_before_release(key: OpKey, start: int, release: int) -> Violation | None:
    """C4: S_o >= r_k(o)."""
    if start < release:
        return Violation("C4", (key,), f"{key} starts at {start} before release {release}")
    return None


def frozen_changed(key: OpKey, a: Assignment, f: FrozenOperation) -> Violation | None:
    """C7: a frozen operation appears with the machine and times of the snapshot."""
    if (a.machine, a.start, a.end) != (f.machine, f.start, f.end):
        return Violation("C7", (key,), f"{key} is frozen as {f.machine} [{f.start},{f.end}), planned "
                                       f"{a.machine} [{a.start},{a.end})")
    return None


def starts_before_t(key: OpKey, start: int, t: int) -> Violation | None:
    """C6: an operation not started is not planned before the rescheduling point t."""
    if start < t:
        return Violation("C6", (key,), f"{key} starts at {start} before the rescheduling point {t}")
    return None


def machine_overlaps(ci: CompiledInstance, by_op: Mapping[int, Assignment]) -> list[Violation]:
    """C5: sweep per machine over half-open intervals [S, C), reporting every overlapping pair."""
    per_machine: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for o, a in by_op.items():
        per_machine[a.machine].append((a.start, a.end, o))
    violations = []
    for machine, intervals in per_machine.items():
        running: list[tuple[int, int, int]] = []
        for s, e, o in sorted(intervals):
            running = [iv for iv in running if iv[1] > s]
            violations += [
                Violation("C5", (ci.op_keys[o2], ci.op_keys[o]),
                          f"{ci.op_keys[o2]} [{s2},{e2}) and {ci.op_keys[o]} [{s},{e}) overlap on {machine}")
                for s2, e2, o2 in running
            ]
            running.append((s, e, o))
    return violations


def assert_feasible(ci: CompiledInstance, assignments: Iterable[Assignment]) -> None:
    """Raise AssertionError listing all violations (for tests and debugging)."""
    if violations := check_schedule(ci, assignments):
        raise AssertionError(
            f"{len(violations)} violation(s):\n" + "\n".join(f"  [{v.constraint}] {v.message}" for v in violations)
        )
