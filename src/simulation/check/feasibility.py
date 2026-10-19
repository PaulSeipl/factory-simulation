"""Feasibility checker for the base model (math/01_basic-fjsp.md, C1-C5).

Written independently of every planner and solver: it only reads the compiled
instance and the assignments, and reports every violated constraint. Test oracle
for CP-SAT, the DES, dispatching rules and the GA. Objective-agnostic on purpose.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from simulation.model.compiled import CompiledInstance, OpKey
from simulation.model.schedule import Assignment


@dataclass(frozen=True, slots=True)
class Violation:
    constraint: str  # "C1".."C5" as in math/01; "C0" = reference to an operation not in the instance
    ops: tuple[OpKey, ...]
    message: str


def check_schedule(ci: CompiledInstance, assignments: Iterable[Assignment]) -> list[Violation]:
    """Return all violations; an empty list means the schedule is feasible."""
    violations: list[Violation] = []

    def report(constraint: str, ops: tuple[OpKey, ...], message: str) -> None:
        violations.append(Violation(constraint, ops, message))

    # C1 (sum_m x_om = 1): every operation assigned exactly once
    by_op: dict[int, Assignment] = {}
    for a in assignments:
        key = (a.order_id, a.op_id)
        o = ci.op_index.get(key)
        if o is None:
            report("C0", (key,), f"{key} is not an operation of the instance")
        elif o in by_op:
            report("C1", (key,), f"{key} assigned more than once")
        else:
            by_op[o] = a
    for o, key in enumerate(ci.op_keys):
        if o not in by_op:
            report("C1", (key,), f"{key} is not assigned")

    for o, a in by_op.items():
        key = ci.op_keys[o]
        p_of = {ci.machine_ids[m]: p for m, p in ci.options[o]}
        # C1: machine in M_o (an unknown machine is never in M_o)
        if a.machine not in p_of:
            report("C1", (key,), f"{key} on {a.machine}, eligible: {sorted(p_of)}")
        # C2: C_o - S_o = p_{o,m} of the assigned machine
        elif a.end - a.start != p_of[a.machine]:
            report("C2", (key,), f"{key}: end - start = {a.end - a.start}, p = {p_of[a.machine]} on {a.machine}")
        # C3: S_o >= C_q for every predecessor q (missing q is already reported under C1)
        for q in ci.predecessors[o]:
            if (b := by_op.get(q)) is not None and a.start < b.end:
                pred = ci.op_keys[q]
                report("C3", (pred, key), f"{key} starts at {a.start} before predecessor {pred} ends at {b.end}")
        # C4: S_o >= r_k(o)
        if a.start < ci.release[o]:
            report("C4", (key,), f"{key} starts at {a.start} before release {ci.release[o]}")

    # C5: sweep per machine over half-open intervals [S, C), reporting every overlapping pair
    per_machine: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for o, a in by_op.items():
        per_machine[a.machine].append((a.start, a.end, o))
    for machine, intervals in per_machine.items():
        running: list[tuple[int, int, int]] = []
        for s, e, o in sorted(intervals):
            running = [iv for iv in running if iv[1] > s]
            for s2, e2, o2 in running:
                report(
                    "C5",
                    (ci.op_keys[o2], ci.op_keys[o]),
                    f"{ci.op_keys[o2]} [{s2},{e2}) and {ci.op_keys[o]} [{s},{e}) overlap on {machine}",
                )
            running.append((s, e, o))

    return violations


def assert_feasible(ci: CompiledInstance, assignments: Iterable[Assignment]) -> None:
    """Raise AssertionError listing all violations (for tests and debugging)."""
    if violations := check_schedule(ci, assignments):
        raise AssertionError(
            f"{len(violations)} violation(s):\n" + "\n".join(f"  [{v.constraint}] {v.message}" for v in violations)
        )
