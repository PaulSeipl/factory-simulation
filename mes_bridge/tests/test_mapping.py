"""After a nesting (task 7.4): the plan's assumed carriers mapped onto the real ones, repaired, not replanned.

Recordings (scratch MES, 2026-11-24, `tests/e2e/mes_driver.py record-nesting`): three telescope orders planned in the
planned nesting flow (no plates yet), then the two most urgent nested onto one print (plates 1 and 2)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fake_mes import FakeMes
from test_proposals import _without
from test_runner import DATA, POLICY

from mes_bridge.api import ProblemOut
from mes_bridge.assumed import assume_plates
from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory
from mes_bridge.instance import epoch_of
from mes_bridge.mapping import map_plan, successors
from mes_bridge.runner import Runner

BEFORE = json.loads((DATA / "problem_before_nesting.json").read_text(encoding="utf-8"))
AFTER = json.loads((DATA / "problem_after_nesting.json").read_text(encoding="utf-8"))


@pytest.fixture
def runner():
    fake = FakeMes(BEFORE)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(AFTER["as_of"])
    factory = MesFactory(client, epoch=epoch_of(now, ZoneInfo("Europe/Berlin")), clock=lambda: now)
    r = Runner(factory, POLICY, log=[].append)
    r.tick(now, "start")
    return fake, r, now


def _assumed(raw):
    return assume_plates(ProblemOut.model_validate(raw))[0]


def test_the_real_carriers_succeed_the_assumed_ones_by_their_parts():
    old, new = _assumed(BEFORE), _assumed(AFTER)
    succ = successors(old, new)
    real = {c.am_job_id for c in ProblemOut.model_validate(AFTER).instance.carriers}
    [job] = real
    assert len(succ[f"R:{job}"]) == 1  # both nested orders were on one assumed print (due-date order)
    plates = {k: v for k, v in succ.items() if k.startswith("C:")}
    assert len(plates) == 3  # the two real plates, and the third order's plate on its new assumed print
    assert all(len(v) == 1 for v in plates.values())


def test_a_nesting_maps_and_repairs_the_plan_it_does_not_replan(runner):
    fake, r, now = runner
    r.decisions.clear()
    fake.problem = AFTER
    r.tick(now, "event")
    types = [d["type"] for d in r.decisions]
    assert "MAP" in types and "REPLAN" not in types, r.decisions
    assert r.factory.rejected == []
    job = next(c["am_job_id"] for c in AFTER["instance"]["carriers"])
    keys = {s.key for s in fake.published[-1].steps}
    assert f"job:{job}:AM_PREP" in keys  # published under the real print
    assert not any(k.endswith(":DATA_PREP_SECONDARY") for k in keys if job in k)


def test_the_mapped_print_keeps_the_assumed_prints_time_and_printer(runner):
    fake, r, now = runner
    job = next(c["am_job_id"] for c in AFTER["instance"]["carriers"])
    nested = {o for c in AFTER["instance"]["carriers"] for p in c["part_ids"] for o in [_order_of(p)]}
    before = {s.key: s for s in fake.published[-1].steps}
    print_before = [before[f"order:{o}:AM_PREP"] for o in nested]
    left_over = next(o["id"] for o in AFTER["instance"]["orders"] if o["id"] not in {str(x) for x in nested})
    fake.problem = AFTER
    r.tick(now, "event")
    steps = {s.key: s for s in fake.published[-1].steps}
    after = steps[f"job:{job}:AM_PREP"]
    assert after.equipment_id == print_before[0].equipment_id
    assert after.start == min(s.start for s in print_before)  # the urgent orders' real print keeps the slot
    # the left-over order's print (a new assumed one, published under its order key) is queued after it
    assert steps[f"order:{left_over}:AM_PREP"].start >= after.end


def test_the_mapping_keeps_every_steps_worker_and_machine_and_moves_nothing_earlier(runner):
    fake, r, now = runner
    before = {s.key: s for s in fake.published[-1].steps}
    fake.problem = AFTER
    r.tick(now, "event")
    after = {s.key: s for s in fake.published[-1].steps}
    common = before.keys() & after.keys()
    assert len(common) > 40
    changed = [k for k in common if (before[k].worker_id, before[k].equipment_id) != (after[k].worker_id,
                                                                                       after[k].equipment_id)]
    assert changed == []
    assert [k for k in common if after[k].start < before[k].start] == []


def _order_of(part_id):
    return next(p["order_id"] for p in AFTER["instance"]["parts"] if p["id"] == part_id)


def test_an_arrival_with_the_nesting_is_not_a_mapping():
    """An operation no assumed one covers (here: an order that was not in the plan) needs a complete rescheduling."""
    third = next(o["id"] for o in BEFORE["instance"]["orders"] if o["due_date"] == max(
        x["due_date"] for x in BEFORE["instance"]["orders"]))  # fmt: skip
    old_raw = _without(BEFORE, third)
    fake = FakeMes(old_raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(AFTER["as_of"])
    factory = MesFactory(client, epoch=epoch_of(now, ZoneInfo("Europe/Berlin")), clock=lambda: now)
    r = Runner(factory, POLICY, log=[].append)
    r.tick(now, "start")
    assert map_plan(factory.current_plan(), factory.problem, _assumed(AFTER), _ci(AFTER, factory)) is None
    r.decisions.clear()
    fake.problem = AFTER
    r.tick(now, "event")
    assert [d["triggers"] for d in r.decisions if d["type"] == "REPLAN"] == [["arrival"]]


def _ci(raw, factory):
    from mes_bridge.instance import build_instance
    from simulation.model.compiled import compile_instance

    return compile_instance(build_instance(_assumed(raw), epoch=factory.epoch))
