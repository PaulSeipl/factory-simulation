import csv
from pathlib import Path

import pytest

from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model, write_csv
from simulation.metrics import run_metrics
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.dispatching import dispatch_planner, spt
from simulation.sim.scenario import Scenario

DATA = Path(__file__).parents[1] / "data"
TOY_INSTANCE = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)  # releases A 0, B 2, C 4
TOY = compile_instance(TOY_INSTANCE)
# hand-checked feasible plan (tests/test_feasibility.py), makespan 11
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]
A3_LONG = Scenario(instance=TOY.name, seed=0, sigma=0, factors=[
    {"order_id": o.id, "op_id": op.id, "factor": 4.0 if op.id == "a3" else 1.0}
    for o in TOY_INSTANCE.orders for op in o.operations
])


def test_metrics_without_disturbance():
    # order ends A 8, B 11, C 10; flow times 8 - 0, 11 - 2, 10 - 4
    m = run_metrics(TOY, PLAN, execute(TOY, PLAN, policy=ReschedulingPolicy()))
    assert m == {"planned_makespan": 11, "makespan": 11, "mean_flow_time": pytest.approx(23 / 3),
                 "mean_start_deviation": 0, "machine_changes": 0, "repairs": 0, "reschedulings": 0,
                 "accepted_reschedulings": 0, "planner_time": 0}


def test_metrics_with_repair_only():
    # a3 takes 8 instead of 2 (ends 14); b4 moves from 9 to 14 on M4: flow times 14, 16 - 2, 10 - 4; one start
    # deviation of 5 among 9 operations; repairs at t = 8..13 (math/05, OVERDUE example)
    m = run_metrics(TOY, PLAN, execute(TOY, PLAN, A3_LONG, ReschedulingPolicy()))
    assert (m["makespan"], m["mean_flow_time"], m["mean_start_deviation"]) == (16, pytest.approx(34 / 3),
                                                                               pytest.approx(5 / 9))
    assert (m["machine_changes"], m["repairs"], m["reschedulings"]) == (0, 6, 0)


def test_metrics_with_rescheduling():
    # same overrun, rescheduling at t = 11 moves b4 to M2 [11, 14): flow times 14, 14 - 2, 6; start deviation 2 / 9
    m = run_metrics(TOY, PLAN, execute(TOY, PLAN, A3_LONG,
                                       ReschedulingPolicy(dispatch_planner(spt), max_makespan_change=2)))
    assert (m["makespan"], m["mean_flow_time"], m["mean_start_deviation"]) == (14, pytest.approx(32 / 3),
                                                                               pytest.approx(2 / 9))
    assert (m["machine_changes"], m["reschedulings"], m["accepted_reschedulings"]) == (1, 1, 1)
    assert m["planner_time"] > 0


def test_metrics_round_trip_through_csv(tmp_path):
    rows = [run_metrics(TOY, PLAN, execute(TOY, PLAN, sc, ReschedulingPolicy())) for sc in (None, A3_LONG)]
    write_csv(rows, tmp_path / "results.csv")
    with (tmp_path / "results.csv").open(encoding="utf-8", newline="") as f:
        read = list(csv.DictReader(f))
    assert [r["makespan"] for r in read] == ["11", "16"] and list(read[0]) == list(rows[0])
