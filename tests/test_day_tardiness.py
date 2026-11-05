"""Tardiness in missed shipping days for instances with a work calendar (math/04_workers.md, section 4).

t = 0 is Monday 08:00; cutoffs (12:00 on working days) at 240, 1680, 3120, ...; Friday 12:00 is 4 * 1440 + 240.
"""

from pathlib import Path

import pytest

from simulation.calendar import cutoffs, next_cutoff
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.due_dates import assign_due_dates
from simulation.io.json_loader import read_model
from simulation.metrics import run_metrics
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN, TARDY_ORDERS, TOTAL_TARDINESS, lexicographic
from simulation.planners.cpsat import solve
from simulation.sim.scenario import Scenario

DAY = 1440
FRIDAY_CUTOFF = 4 * DAY + 240
TOY = read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-dag-3x4.json", Instance)


def chain(*durations: int, due: int = 240, calendar: bool = True):
    """One order k: a chain of operations on machine M."""
    ops = [{"id": f"o{i}", "step": "s", "options": {"M": p}, "predecessors": [f"o{i - 1}"] if i else []}
           for i, p in enumerate(durations)]
    data = {"schema_version": "0.6", "name": "chain", "machines": ["M"],
            "orders": [{"id": "k", "due_date": due, "operations": ops}]}
    return compile_instance(Instance.model_validate(data | ({"calendar": {}} if calendar else {})))


def ending_at(end: int):
    return [Assignment(order_id="k", op_id="o0", machine="M", start=0, end=end)]


@pytest.mark.parametrize("end, days", [(100, 0), (240, 0), (241, 1), (1680, 1), (1681, 2)])
def test_boundary_minutes(end, days):
    assert TOTAL_TARDINESS.evaluate(chain(end), ending_at(end)) == days


def test_weekend_counts_one_day():
    end = 7 * DAY + 120  # Monday 10:00 of the next week
    assert TOTAL_TARDINESS.evaluate(chain(end, due=FRIDAY_CUTOFF), ending_at(end)) == 1


def test_tardy_orders_unchanged_with_calendar():
    assert TARDY_ORDERS.evaluate(chain(241), ending_at(241)) == 1
    assert TARDY_ORDERS.evaluate(chain(240), ending_at(240)) == 0


def test_without_calendar_tardiness_stays_in_minutes():
    assert TOTAL_TARDINESS.evaluate(chain(1681, calendar=False), ending_at(1681)) == 1441


def test_day_tardiness_cpsat_agrees():
    ci = chain(850, 850)  # ends at 1700 at the earliest: cutoffs 240 and 1680 missed
    result = solve(ci, TOTAL_TARDINESS, time_limit=5, workers=1)
    assert result.status == "OPTIMAL"
    assert result.objective == 2 == TOTAL_TARDINESS.evaluate(ci, result.schedule)


def test_lexicographic_with_day_tardiness_agrees():
    ci = chain(850, 850)
    objective = lexicographic(TOTAL_TARDINESS, MAKESPAN)
    result = solve(ci, objective, time_limit=5, workers=1)
    assert result.objective == objective.evaluate(ci, result.schedule)
    assert TOTAL_TARDINESS.evaluate(ci, result.schedule) == 2 and MAKESPAN.evaluate(ci, result.schedule) == 1700


def test_day_spread_bounds_one_cutoff_per_day():
    ci = chain(850, 850)  # horizon 1700: at most 1700 // 1440 + 1 = 2 cutoffs per order in any window of that length
    assert TOTAL_TARDINESS.spread(ci) == 2


def test_due_dates_rounded_up_to_cutoffs():
    with_calendar = Instance.model_validate(TOY.model_dump() | {"calendar": {}})
    rounded = assign_due_dates(with_calendar, (1.0, 3000.0), seed=0)
    plain = assign_due_dates(TOY, (1.0, 3000.0), seed=0)  # same random draws
    cal = with_calendar.calendar
    for r, p in zip(rounded.orders, plain.orders, strict=True):
        assert r.due_date == next_cutoff(cal, p.due_date) and r.due_date in cutoffs(cal, r.due_date)


def test_tardy_days_column():
    ci = chain(850, 850)
    plan = solve(ci, MAKESPAN, time_limit=5, workers=1).schedule
    no_disturbance = Scenario(instance=ci.name, seed=0, sigma=0, factors=[
        {"order_id": "k", "op_id": op, "factor": 1.0} for op in ("o0", "o1")])
    m = run_metrics(ci, plan, execute(ci, plan, no_disturbance, ReschedulingPolicy()))
    assert (m["tardy_days"], m["total_tardiness"], m["tardy_orders"]) == (2, 1700 - 240, 1)
    plain = chain(850, 850, calendar=False)
    assert "tardy_days" not in run_metrics(plain, plan, execute(plain, plan, no_disturbance, ReschedulingPolicy()))
