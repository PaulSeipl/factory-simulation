from pathlib import Path

import pytest

from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.repair import shift_repair

TOY = compile_instance(read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-dag-3x4.json", Instance))
# hand-checked feasible plan (tests/test_feasibility.py); every planned start is tight
ROWS = [
    ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
    ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
    ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
]


def arrays(rows):
    plan = [Assignment(order_id=o, op_id=j, machine=m, start=s, end=e) for o, j, m, s, e in rows]
    machine, start, end = [0] * TOY.n_ops, [0] * TOY.n_ops, [0] * TOY.n_ops
    for a in plan:
        o = TOY.op_index[a.order_id, a.op_id]
        machine[o], start[o], end[o] = TOY.machine_index[a.machine], a.start, a.end
    order_on = [sorted((o for o in range(TOY.n_ops) if machine[o] == m), key=lambda o: start[o])
                for m in range(TOY.n_machines)]
    return machine, order_on, start, end


def repaired(rows, t, actual):
    """actual: op_id -> (start, end or None); all other operations have not started."""
    machine, order_on, start, end = arrays(rows)
    s, e = [None] * TOY.n_ops, [None] * TOY.n_ops
    for op_id, (a_start, a_end) in actual.items():
        o = next(i for i, k in enumerate(TOY.op_keys) if k[1] == op_id)
        s[o], e[o] = a_start, a_end
    new_start, new_end = shift_repair(TOY, t, machine, order_on, start, end, s, e)
    return {TOY.op_keys[o][1]: (new_start[o], new_end[o]) for o in range(TOY.n_ops)}


def test_nothing_deviates_nothing_moves():
    assert repaired(ROWS, 3, {"a1": (0, 3)}) == {j: (s, e) for _, j, _, s, e in ROWS}


def test_early_finish_pulls_the_tight_chain_forward():
    # a1 finished at 2 instead of 3: everything depending on it moves 1 earlier; makespan 11 -> 10
    assert repaired(ROWS, 2, {"a1": (0, 2)}) == {
        "a1": (0, 2), "a2": (2, 5), "a3": (5, 7), "b1": (2, 4), "b2": (4, 7), "b3": (4, 8), "b4": (8, 10),
        "c1": (5, 7), "c2": (7, 9),
    }


def test_operation_with_a_gap_keeps_its_start():
    # c2 planned at 9 although 8 would be possible: the early finish of a1 does not pull it forward
    gap = [r if r[1] != "c2" else ("C", "c2", "M2", 9, 11) for r in ROWS]
    assert repaired(gap, 2, {"a1": (0, 2)})["c2"] == (9, 11)


def test_overrunning_operation_pushes_its_successors():
    # b1, planned to end at 5, is still running at 5: expected end 6, so b2 and b3 start at 6
    new = repaired(ROWS, 5, {"a1": (0, 3), "a2": (3, None), "b1": (3, None)})
    assert new["b1"] == (3, 6) and new["b2"] == (6, 9) and new["b3"] == (6, 10) and new["b4"] == (10, 12)


def test_no_operation_is_planned_before_t():
    new = repaired(ROWS, 1, {"a1": (0, None)})
    assert all(s >= 1 for j, (s, _) in new.items() if j != "a1")


@pytest.mark.parametrize("t", [0, 2, 5])
def test_running_operation_gets_its_expected_end_from_the_planned_duration(t):
    # no realized durations are passed: the expected end is start + p, at least t + 1
    assert repaired(ROWS, t, {"a1": (0, None)})["a1"] == (0, max(3, t + 1))
