"""Arrival sampler and instances with arrivals (math/07_order-arrivals.md, math/21_instance-generator.md §4b).

Default calendar: t = 0 is Monday 08:00, shift 08:00-17:30, cutoff 12:00, Monday-Friday; Monday 12:00 is t = 240 and
every further working day adds 1440 (Friday 12:00 = 6000, next Monday 12:00 = 10320).
"""

from pathlib import Path
from statistics import mean

import pytest
from pydantic import ValidationError

from simulation.arrival_generator import (
    ArrivalParams,
    generate_arrival_instance,
    nesting_times,
    nth_cutoff,
    sample_arrivals,
)
from simulation.calendar import day_index, is_working_day, minute_of_day
from simulation.carrier_generator import CarrierGeneratorParams
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance, compile_visible
from simulation.model.instance import Calendar
from simulation.planners.cpsat import cpsat_planner, solve

EXAMPLE = Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-workers.json"
BASE = read_model(EXAMPLE, CarrierGeneratorParams).model_copy(update={"release_range": (0, 0),
                                                                       "due_date_tightness": ()})
CAL = Calendar()


def params(**changes) -> ArrivalParams:
    return ArrivalParams(**{"seed": 1, "base": BASE, "rates": dict.fromkeys(range(5), 2.0)} | changes)


# --- calendar helpers -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("t", "n", "expected"), [
    (120, 4, 4560),  # Monday 10:00: Monday's cutoff still counts -> Thursday 12:00
    (300, 4, 6000),  # Monday 13:00 -> Friday 12:00
    (240, 1, 1680),  # at a cutoff: strictly after -> Tuesday
    (6001, 1, 10320),  # Friday after the cutoff -> next Monday
])
def test_nth_cutoff_by_hand(t, n, expected):
    assert nth_cutoff(CAL, t, n) == expected


def test_nesting_times_weekly():
    assert nesting_times(params(nesting_days=(4,), due_working_days=6), 3 * 7 * 1440) == [6000, 16080, 26160]


# --- sampler ----------------------------------------------------------------------------------------------------


def test_same_seed_same_arrivals():
    assert sample_arrivals(params()) == sample_arrivals(params())
    assert sample_arrivals(params()) != sample_arrivals(params(seed=2))


def test_acceptance_in_the_shift_and_arrival_at_the_next_batch():
    p = params(backlog=3)
    times = sample_arrivals(p)
    batches = nesting_times(p, 30 * 1440)
    assert times[:3] == [(0, 0)] * 3
    for acc, arr in times[3:]:
        assert 0 <= acc < p.window_days * 1440 and is_working_day(CAL, day_index(CAL, acc))
        assert CAL.shift_start <= minute_of_day(CAL, acc) < CAL.shift_end
        assert arr == min(b for b in batches if b >= acc)


def test_weekly_nesting_collects_a_week():
    times = sample_arrivals(params(nesting_days=(4,), due_working_days=6))
    assert {arr for _, arr in times} <= {6000, 16080, 26160}  # accepted after week 2's batch: week 3
    assert all(arr == 6000 for acc, arr in times if acc <= 6000)


def test_rates_reproduced_in_the_mean():
    # Mondays only, 3 per Monday, two Mondays in 14 days: 6 orders on average (std of the mean over 300 seeds 0.14)
    counts = [len(sample_arrivals(params(seed=s, rates={0: 3.0}))) for s in range(300)]
    assert mean(counts) == pytest.approx(6.0, abs=0.45)


# --- instance ---------------------------------------------------------------------------------------------------


def test_instance_with_arrivals():
    p = params(backlog=2)
    inst = generate_arrival_instance(p)
    times = sample_arrivals(p)
    assert [(o.accepted, o.arrival) for o in inst.orders] == times
    assert all(o.release == o.arrival for o in inst.orders)
    for o in inst.orders[2:]:  # n-th cutoff after the acceptance
        assert o.due_date == nth_cutoff(CAL, o.accepted, 4)
    assert all(o.due_date in {nth_cutoff(CAL, 0, k) for k in (3, 4)} for o in inst.orders[:2])  # backlog: cutoff 3, 4
    # one nesting batch per arrival time, nested on its own (V21 holds by construction), IDs per batch
    arrival = {o.id: o.arrival for o in inst.orders}
    packages = {c.id.split("C")[0].split("B")[0] for c in inst.carriers}
    assert len(packages) == len(set(arrival.values()))
    assert all(len({arrival[k] for k, _ in c.parts}) == 1 for c in inst.carriers)
    assert inst.workers and inst.calendar is not None


def test_lead_time_due_dates():
    inst = generate_arrival_instance(params(due_working_days=None, due_tightness=(2.0,)))
    assert all(o.due_date >= o.arrival for o in inst.orders)


def test_small_episode_runs_with_cpsat_rescheduling():
    # three days, about one order a day plus one in the backlog: one rescheduling per later nesting batch
    p = params(rates={0: 1.0, 1: 1.0, 2: 1.0}, window_days=3, backlog=1, seed=4)
    inst = generate_arrival_instance(p)
    ci, at = compile_instance(inst), compile_visible(inst)
    start = solve(at(0), time_limit=10, workers=1)
    result = execute(ci, start.schedule, policy=ReschedulingPolicy(planner=cpsat_planner(time_limit=10)),
                     breaks=start.breaks, visible=at)
    arrivals = sorted({o.arrival for o in inst.orders} - {0})
    assert arrivals  # the episode has nesting batches after t = 0
    assert [d["t"] for d in result.decisions if "arrival" in d.get("triggers", ())] == arrivals
    assert not check_schedule(ci, result.schedule, breaks=result.breaks)


# --- invalid parameters -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("changes", "message"), [
    ({"base": BASE.model_copy(update={"calendar": None})}, r"arrivals need a calendar"),
    ({"base": BASE.model_copy(update={"release_range": (0, 30)})}, r"base needs release_range \(0, 0\)"),
    ({"base": BASE.model_copy(update={"due_date_tightness": (2.0,)})}, r"no due_date_tightness"),
    ({"rates": {7: 1.0}}, r"rates for unknown weekdays \[7\]"),
    ({"nesting_days": (5,)}, r"nesting_days \[5\] must be non-empty working days"),
    ({"nesting_days": ()}, r"must be non-empty working days"),
    ({"due_working_days": None}, r"exactly one due-date rule"),
    ({"due_tightness": (2.0,)}, r"exactly one due-date rule"),
    ({"nesting_minute": 1440}, r"less than 1440"),
    ({"due_working_days": 1}, r"due_working_days 1 too short for the nesting cycle"),  # daily: 2 needed
    ({"nesting_days": (4,), "due_working_days": 5}, r"due_working_days 5 too short"),  # weekly: 6 needed
    ({"due_working_days": 2}, r"backlog_earliest_cutoff 3 after due_working_days 2"),
])
def test_invalid_parameters_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


def test_shortest_due_offsets_accepted():
    params(due_working_days=2, backlog_earliest_cutoff=2)
    params(nesting_days=(4,), due_working_days=6)


def test_no_order_rejected():
    with pytest.raises(ValueError, match="no order sampled"):
        generate_arrival_instance(params(rates={}))
