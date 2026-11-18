"""Order release rule (math/33_order-release-interface.md, step A) and the quota in the arrival generator."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.arrival_generator import ArrivalParams, generate_arrival_instance, nesting_times, sample_arrivals
from simulation.calendar import day_index
from simulation.carrier_generator import CarrierGeneratorParams
from simulation.experiment import ExperimentConfig
from simulation.io.json_loader import read_model
from simulation.release import PoolOrder, release

ROOT = Path(__file__).parents[1]


def pool(*orders):  # (id, due, size); accepted 0, index = position
    return [PoolOrder(k, 0, d, i) for i, (k, d, _) in enumerate(orders)], {k: n for k, _, n in orders}


def run(orders, budget, next_nesting=50):  # every due date after 50: none forced by default
    p, size = pool(*orders)
    return release(p, budget, lambda o: size[o.id], next_nesting)


# --- the rule by hand --------------------------------------------------------------------------------------------


def test_binds_in_due_date_order_within_the_budget():
    assert run([("A", 300, 4), ("B", 100, 4), ("C", 200, 4)], 8) == ["B", "C"]


def test_no_budget_binds_all():
    assert run([("A", 300, 4), ("B", 100, 4)], None) == ["B", "A"]


def test_a_smaller_later_order_takes_the_place_of_one_that_does_not_fit():
    # B (6) does not fit after A (4) into 8; C (2) does and overtakes B (user 2026-11-17)
    assert run([("A", 100, 4), ("B", 200, 6), ("C", 300, 2)], 8) == ["A", "C"]


def test_an_order_larger_than_the_budget_takes_it_when_it_alone_has_the_earliest_due_date():
    # user 2026-11-17: A (9 > 8) alone has the earliest due date -> bound, takes the whole budget (B waits)
    assert run([("A", 100, 9), ("B", 200, 2)], 8) == ["A"]
    # B shares A's due date: B goes first, A waits until it is alone at the front
    assert run([("A", 100, 9), ("B", 100, 2), ("C", 200, 2)], 8) == ["B", "C"]
    assert run([("A", 100, 9)], 8) == ["A"]
    # a large order behind a smaller earlier one waits (skipped, no budget left for it anyway)
    assert run([("A", 100, 2), ("B", 200, 9), ("C", 300, 2)], 8) == ["A", "C"]


def test_an_order_that_cannot_wait_is_bound_regardless_of_the_budget():
    # next nesting at 500: C (due 500) would arrive at its due date, so it is bound now; B waits
    assert run([("A", 100, 8), ("B", 600, 2), ("C", 500, 4)], 8, next_nesting=500) == ["A", "C"]
    # forced orders use the budget first: A (8) and C (4, forced) leave nothing for B
    assert run([("A", 100, 8), ("C", 501, 4)], 8, next_nesting=500) == ["A"]


def test_no_later_nesting_binds_all():
    assert run([("A", 100, 8), ("B", 600, 8)], 8, next_nesting=None) == ["A", "B"]


# --- quota in the arrival generator ------------------------------------------------------------------------------

# instance digests of the experiment configurations before the release rule existed (bind all = unchanged)
INSTANCE_DIGESTS = {
    "arrivals-rate4": "4e81907bf50bd2c7", "arrivals-rate6-undisturbed": "ff3fc90c868031ab",
    "arrivals-rate6": "ff3fc90c868031ab", "arrivals-rate8-double": "3a87c2d59d4e414c",
    "arrivals-rate8": "c0a843fd6b4b5365", "nesting-daily": "d3895972eba41fad", "nesting-weekly": "53384969fafc1528",
}


@pytest.mark.parametrize("name", sorted(INSTANCE_DIGESTS))
def test_without_quota_instances_are_unchanged(name):
    c = read_model(ROOT / "experiments" / f"{name}.json", ExperimentConfig)
    inst = generate_arrival_instance(c.arrivals).model_copy(update={"schema_version": "0.7"})  # digests from 0.7
    digest = hashlib.sha256(inst.model_dump_json().encode()).hexdigest()[:16]
    assert digest == INSTANCE_DIGESTS[name]


BASE = read_model(ROOT / "data" / "generator" / "dental-carriers-workers.json", CarrierGeneratorParams).model_copy(
    update={"release_range": (0, 0), "due_date_tightness": (), "count_range": (4, 4)})


def params(**changes) -> ArrivalParams:
    return ArrivalParams(**{"seed": 1, "base": BASE, "rates": dict.fromkeys(range(5), 4.0), "window_days": 10,
                            "due_working_days": 4, "backlog": 2} | changes)


@pytest.mark.parametrize("seed", range(5))
def test_quota_holds_orders_back_without_changing_due_dates(seed):
    free = generate_arrival_instance(params(seed=seed))
    held = generate_arrival_instance(params(seed=seed, quota=dict.fromkeys(range(5), 2)))  # 2 orders of 4
    before = {o.id: o for o in free.orders}
    cal = BASE.calendar
    per_batch: dict[int, list] = {}
    for o in held.orders:
        b = before[o.id]
        assert (o.accepted, o.due_date) == (b.accepted, b.due_date)  # acceptance and due date unchanged
        assert o.arrival >= b.arrival and o.release == o.arrival  # never earlier than binding all
        assert o.arrival <= o.due_date  # V10 (also validated by the instance)
        if o.arrival > 0:
            per_batch.setdefault(o.arrival, []).append(o)
    assert any(before[o.id].arrival < o.arrival for o in held.orders)  # the quota binds in this setting
    nest_at = nesting_times(params(), max(per_batch) + 7 * 1440)
    for t, batch in per_batch.items():
        after = next(n for n in nest_at if n > t)
        # two orders of 4 fit the quota of 2 default orders; every further one could not wait for the next nesting
        ranked = sorted(batch, key=lambda o: (o.due_date, o.accepted))
        assert all(o.due_date <= after for o in ranked[2:])
        assert t in nest_at and day_index(cal, t) % 7 in range(5)
    assert all(o.arrival == 0 for o in held.orders[:2])  # backlog bound at 0


def test_quota_with_a_huge_budget_equals_binding_all():
    assert generate_arrival_instance(params(quota=dict.fromkeys(range(5), 10_000.0))) == generate_arrival_instance(
        params())


def test_sample_arrivals_unchanged_by_the_quota():
    assert sample_arrivals(params(quota=dict.fromkeys(range(5), 2))) == sample_arrivals(params())


@pytest.mark.parametrize(("changes", "message"), [
    ({"quota": {**dict.fromkeys(range(5), 2), 5: 2}}, r"quota for weekdays \[5\] without nesting"),
    ({"quota": dict.fromkeys(range(4), 2)}, r"no quota for nesting weekdays \[4\]"),
    ({"quota": dict.fromkeys(range(5), 2), "due_working_days": None, "due_tightness": (1.5,)},
     r"quota needs due_working_days"),
    ({"quota": dict.fromkeys(range(5), 0)}, r"greater than 0"),
    ({"quota": dict.fromkeys(range(5), 2), "quota_size": 0}, r"greater than 0"),
])
def test_invalid_quota_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


def test_episode_with_quota_runs_through(tmp_path):
    # the dental example (not the Fidentis case, user 2026-11-18), quota 1.5 default orders (6 telescopes) at 3 orders
    # per working day: holds orders back; the episode with the rule at arrivals finishes
    from simulation.experiment import run_one

    arrivals = ArrivalParams(seed=0, base=BASE, rates=dict.fromkeys(range(5), 3.0), window_days=3, backlog=1,
                             due_working_days=4, quota=dict.fromkeys(range(5), 1.5))
    free = generate_arrival_instance(arrivals.model_copy(update={"seed": 3, "quota": None}))
    held = generate_arrival_instance(arrivals.model_copy(update={"seed": 3}))
    assert sum(o.arrival for o in held.orders) > sum(o.arrival for o in free.orders)
    config = ExperimentConfig(name="quota", arrivals=arrivals, seeds=(3,),
                              policies={"rule": {"planner": "rule"}})
    row = run_one(config, "rule", 3, tmp_path)  # finishes: every order completed (run_one checks the realized run)
    assert row["orders"] == len(held.orders) and row["mean_lead_time"] > 0
