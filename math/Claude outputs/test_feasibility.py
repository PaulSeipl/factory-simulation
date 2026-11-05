"""Tests for feasibility.py on the toy instance from the walkthrough page.

Uses a stand-in for CompiledInstance with the attributes documented in
01_basic-fjsp.md §5. Replace `toy_instance()` by a real compile_instance(...) call
once the attribute names are confirmed against the code.
"""
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from feasibility import check_schedule, assert_feasible

MACHINES = ["M1", "M2", "M3", "M4"]
ORDERS = {  # order -> (release, [(op, {machine: p}, [local preds])])
    "A": (0, [("a1", {"M1": 3, "M2": 5}, []), ("a2", {"M2": 4, "M3": 3}, ["a1"]), ("a3", {"M4": 2}, ["a2"])]),
    "B": (2, [("b1", {"M1": 2, "M3": 4}, []), ("b2", {"M2": 3, "M3": 3}, ["b1"]),
              ("b3", {"M1": 4, "M4": 3}, ["b1"]), ("b4", {"M4": 2, "M2": 3}, ["b2", "b3"])]),
    "C": (4, [("c1", {"M1": 3, "M3": 2}, []), ("c2", {"M2": 2, "M4": 4}, ["c1"])]),
}


def toy_instance():
    op_keys, options, preds, release = [], [], [], []
    midx = {m: i for i, m in enumerate(MACHINES)}
    for k, (r, ops) in ORDERS.items():
        for j, opts, _ in ops:
            op_keys.append((k, j))
    op_index = {key: i for i, key in enumerate(op_keys)}
    for k, (r, ops) in ORDERS.items():
        for j, opts, pr in ops:
            options.append(tuple((midx[m], p) for m, p in opts.items()))
            preds.append(tuple(op_index[(k, q)] for q in pr))
            release.append(r)
    return SimpleNamespace(op_keys=op_keys, op_index=op_index, machine_ids=MACHINES,
                           machine_index=midx, options=options, predecessors=preds, release=release)


@dataclass(frozen=True)
class Assignment:  # mirrors simulation.model.schedule.Assignment
    order_id: str
    op_id: str
    machine: str
    start: int
    end: int


OPTIMUM = [Assignment(j[0].upper(), j, m, s, e) for j, m, s, e in [
    ("a1", "M1", 0, 3), ("a2", "M3", 3, 6), ("a3", "M4", 6, 8), ("b1", "M1", 3, 5), ("b2", "M2", 5, 8),
    ("b3", "M1", 5, 9), ("b4", "M4", 9, 11), ("c1", "M3", 6, 8), ("c2", "M2", 8, 10)]]


def mutate(op, **kw):
    return [replace(a, **kw) if a.op_id == op else a for a in OPTIMUM]


def test_optimum_is_feasible():
    assert assert_feasible(toy_instance(), OPTIMUM) == 11


@pytest.mark.parametrize("sched, expected", [
    (mutate("c2", machine="M3"), "C1"),                 # M3 not eligible for c2
    (mutate("b3", end=7), "C2"),                        # b3 shortened
    (mutate("b4", start=8, end=10), "C3"),              # b4 before b3 finishes
    (mutate("c1", start=1, end=3), "C4"),               # c1 before release of C
    (mutate("c2", machine="M4", start=8, end=12), "C5"),  # overlaps b4 on M4
    (OPTIMUM[:-1], "C0"),                               # c2 missing
    (OPTIMUM + [OPTIMUM[0]], "C0"),                     # a1 twice
])
def test_each_break_is_detected_alone(sched, expected):
    res = check_schedule(toy_instance(), sched)
    assert not res.feasible
    assert set(res.by_constraint()) == {expected}, res.summary()


def test_c5_reports_all_overlapping_pairs():
    # three ops stacked on M1 at the same time -> 3 pairs
    sched = mutate("a1", start=10, end=13)
    sched = [replace(a, start=10, end=12) if a.op_id == "b1" else a for a in sched]
    sched = [replace(a, machine="M1", start=10, end=13) if a.op_id == "c1" else a for a in sched]
    res = check_schedule(toy_instance(), sched)
    pairs = {frozenset(v.ops) for v in res.violations if v.constraint == "C5"}
    assert {frozenset({("A", "a1"), ("B", "b1")}), frozenset({("A", "a1"), ("C", "c1")}),
            frozenset({("B", "b1"), ("C", "c1")})} <= pairs


def test_cpsat_solution_passes_checker():
    ortools = pytest.importorskip("ortools")
    from toy_cpsat import solve, orders
    status, cmax, sched = solve(orders)
    out = [Assignment(r["order"], r["op"], r["machine"], r["start"], r["end"]) for r in sched]
    assert status == "OPTIMAL" and assert_feasible(toy_instance(), out) == cmax == 11
