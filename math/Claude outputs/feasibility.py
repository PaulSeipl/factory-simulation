"""Feasibility checker for the base FJSP model (math/01_basic-fjsp.md, C1-C5).

Independent of any solver: takes a compiled instance and a list of assignments
and reports every violated constraint. Intended as the test oracle for CP-SAT,
the DES, dispatching rules and the GA.

Interface assumptions (taken from 01_basic-fjsp.md §5, NOT from the code itself):
    ci.op_keys[o]       -> (order_id, op_id)        global index o = 0..n_ops-1
    ci.op_index[(k, j)] -> o
    ci.machine_ids[m]   -> machine id               m = machine index
    ci.machine_index[id]-> m
    ci.options[o]       -> ((m, p_om), ...)         m as machine INDEX
    ci.predecessors[o]  -> iterable of global op indices
    ci.release[o]       -> r_k(o)
    assignment.order_id, .op_id, .machine (machine ID), .start, .end
Adjust the attribute access in `_index_schedule` / the loops if the code differs.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Violation:
    constraint: str            # "C0".."C5"; C0 = schedule structure (missing/duplicate/unknown)
    ops: tuple                 # (order_id, op_id) keys involved
    message: str


@dataclass
class CheckResult:
    violations: list[Violation] = field(default_factory=list)
    makespan: int | None = None

    @property
    def feasible(self) -> bool:
        return not self.violations

    def by_constraint(self) -> dict[str, list[Violation]]:
        out: dict[str, list[Violation]] = defaultdict(list)
        for v in self.violations:
            out[v.constraint].append(v)
        return dict(out)

    def summary(self) -> str:
        if self.feasible:
            return f"feasible, Cmax = {self.makespan}"
        counts = {c: len(v) for c, v in sorted(self.by_constraint().items())}
        return f"INFEASIBLE {counts}\n" + "\n".join(f"  [{v.constraint}] {v.message}" for v in self.violations)


def _index_schedule(ci, schedule, res: CheckResult) -> dict[int, object]:
    """C0: every operation appears exactly once, refers to a known op and machine."""
    by_op: dict[int, object] = {}
    for a in schedule:
        key = (a.order_id, a.op_id)
        o = ci.op_index.get(key)
        if o is None:
            res.violations.append(Violation("C0", (key,), f"{key} is not an operation of the instance"))
            continue
        if a.machine not in ci.machine_index:
            res.violations.append(Violation("C0", (key,), f"{key} assigned to unknown machine {a.machine!r}"))
            continue
        if o in by_op:
            res.violations.append(Violation("C0", (key,), f"{key} assigned more than once"))
            continue
        by_op[o] = a
    for o, key in enumerate(ci.op_keys):
        if o not in by_op:
            res.violations.append(Violation("C0", (key,), f"{key} is not scheduled"))
    return by_op


def check_schedule(ci, schedule: Iterable) -> CheckResult:
    res = CheckResult()
    by_op = _index_schedule(ci, schedule, res)
    key = ci.op_keys

    for o, a in by_op.items():
        p_of = {ci.machine_ids[m]: p for m, p in ci.options[o]}

        # domain: integer, non-negative times
        if not (isinstance(a.start, int) and isinstance(a.end, int)) or a.start < 0:
            res.violations.append(Violation("C0", (key[o],), f"{key[o]}: start/end must be integers >= 0, got {a.start}/{a.end}"))

        # C1 assignment: machine must be eligible (exactly-one is C0's job)
        if a.machine not in p_of:
            res.violations.append(Violation(
                "C1", (key[o],), f"{key[o]} on {a.machine}, eligible: {sorted(p_of)}"))
        # C2 non-preemption: duration equals p_{o,m} of the chosen machine
        elif a.end - a.start != p_of[a.machine]:
            res.violations.append(Violation(
                "C2", (key[o],), f"{key[o]}: C-S = {a.end - a.start}, p = {p_of[a.machine]} on {a.machine}"))

        # C3 precedence
        for q in ci.predecessors[o]:
            b = by_op.get(q)
            if b is not None and a.start < b.end:
                res.violations.append(Violation(
                    "C3", (key[q], key[o]), f"{key[o]} starts at {a.start} < C{key[q]} = {b.end}"))

        # C4 release
        if a.start < ci.release[o]:
            res.violations.append(Violation(
                "C4", (key[o],), f"{key[o]} starts at {a.start} < release {ci.release[o]}"))

    # C5 machine capacity: sweep per machine, reports every overlapping pair
    per_machine: dict[object, list[tuple[int, int, int]]] = defaultdict(list)
    for o, a in by_op.items():
        per_machine[a.machine].append((a.start, a.end, o))
    for m, ivs in per_machine.items():
        ivs.sort()
        active: list[tuple[int, int, int]] = []
        for s, e, o in ivs:
            active = [iv for iv in active if iv[1] > s]       # still running at s
            for s2, e2, o2 in active:
                res.violations.append(Violation(
                    "C5", (key[o2], key[o]),
                    f"{key[o2]} [{s2},{e2}) and {key[o]} [{s},{e}) overlap on {m}"))
            active.append((s, e, o))

    if by_op:
        res.makespan = max(a.end for a in by_op.values())
    return res


def assert_feasible(ci, schedule: Iterable) -> int:
    """Raise AssertionError with all violations; return the makespan otherwise."""
    res = check_schedule(ci, list(schedule))
    if not res.feasible:
        raise AssertionError(res.summary())
    return res.makespan
