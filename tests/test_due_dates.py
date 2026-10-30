import math
from pathlib import Path

import pytest

from simulation.due_dates import assign_due_dates, lead_time_bound
from simulation.generator import GeneratorParams, generate_instance
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.objectives import TOTAL_TARDINESS
from simulation.planners.dispatching import best_dispatch

DATA = Path(__file__).parents[1] / "data"
TOY = read_model(DATA / "instances" / "toy-dag-3x4.json", Instance)
MK01 = load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")


def order(inst: Instance, order_id: str):
    return next(o for o in inst.orders if o.id == order_id)


def test_lead_time_bound_of_a_chain_is_its_total_average_work():
    # A: a1 (3 + 5) / 2 = 4, a2 (4 + 3) / 2 = 3.5, a3 2
    assert lead_time_bound(order(TOY, "A")) == 9.5
    # mk01 J1: 4.5 + 3 + 3 + 4 + 1 + 5
    assert lead_time_bound(order(MK01, "J1")) == 20.5


def test_lead_time_bound_of_parallel_branches_is_the_longest_path():
    # B: b1 3, then b2 3 and b3 3.5 in parallel, then b4 2.5: 3 + 3.5 + 2.5 = 9 (the sum would be 12)
    assert lead_time_bound(order(TOY, "B")) == 9


def test_due_dates_by_hand():
    # d = r + round(theta * Lambda), half up: A 0 + 9.5 -> 10, B 2 + 9 = 11, C 4 + (2.5 + 3 = 5.5 -> 6) = 10
    inst = assign_due_dates(TOY, (1.0,), seed=0)
    assert [(o.id, o.due_date) for o in inst.orders] == [("A", 10), ("B", 11), ("C", 10)]
    assert [o.operations for o in inst.orders] == [o.operations for o in TOY.orders]  # nothing else changes


@pytest.mark.parametrize("seed", range(5))
def test_tightness_is_drawn_per_order_from_the_given_values_and_reproducible(seed):
    inst = assign_due_dates(MK01, (0.5, 1.0, 1.5), seed)
    assert inst == assign_due_dates(MK01, (0.5, 1.0, 1.5), seed)
    for o in inst.orders:
        assert o.due_date in {o.release + math.floor(theta * lead_time_bound(o) + 0.5) for theta in (0.5, 1.0, 1.5)}


def test_generator_adds_due_dates_only_when_asked():
    base = {"seed": 7, "n_machines": 5, "n_orders": 6, "n_operations": 40, "min_order_length": 4,
            "max_machines_per_op": 3, "routing_modes": ("chain", "split_join"), "release_range": (0, 10)}
    without = generate_instance(GeneratorParams(**base))
    with_due = generate_instance(GeneratorParams(**base, due_date_tightness=(1.0,)))
    assert all(o.due_date is None for o in without.orders)
    assert with_due == assign_due_dates(without, (1.0,), 7)  # own random stream: the rest is unchanged


# hand-checked feasible plan (tests/test_feasibility.py): order ends A 8, B 11, C 10; releases A 0, B 2, C 4
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "a1", "M1", 0, 3), ("A", "a2", "M3", 3, 6), ("A", "a3", "M4", 6, 8),
        ("B", "b1", "M1", 3, 5), ("B", "b2", "M2", 5, 8), ("B", "b3", "M1", 5, 9), ("B", "b4", "M4", 9, 11),
        ("C", "c1", "M3", 6, 8), ("C", "c2", "M2", 8, 10),
    ]
]


def test_due_dates_from_a_reference_plan_by_hand():
    # flow times in the plan: A 8, B 9, C 6
    assert [o.due_date for o in assign_due_dates(TOY, (1.0,), 0, reference=PLAN).orders] == [8, 11, 10]
    # theta 1.2: A 9.6 -> 10, B 2 + (10.8 -> 11) = 13, C 4 + (7.2 -> 7) = 11
    assert [o.due_date for o in assign_due_dates(TOY, (1.2,), 0, reference=PLAN).orders] == [10, 13, 11]


@pytest.mark.parametrize("path", sorted((DATA / "benchmarks" / "brandimarte").glob("*.fjs")), ids=lambda p: p.stem)
def test_reference_plan_is_on_time_for_tightness_at_least_one(path):
    inst = load_fjs(path)
    _, reference = best_dispatch(compile_instance(inst))
    ci = compile_instance(assign_due_dates(inst, (1.0, 1.2, 1.5), 3, reference=reference))
    assert TOTAL_TARDINESS.evaluate(ci, reference) == 0
