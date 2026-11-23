"""Bound and free (task 6.1, spec decision 4): assignments as pins in BOUND, ignored in FREE."""

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from mes_bridge.api import ProblemOut
from mes_bridge.config import SchedulerConfig
from mes_bridge.instance import build_instance, epoch_of
from mes_bridge.once import BOUND, FREE, solve
from mes_bridge.state import build_snapshot, id_map, pin
from simulation.model.compiled import compile_instance

DATA = Path(__file__).parent / "data"
BERLIN = ZoneInfo("Europe/Berlin")
W2, M2 = str(uuid4()), str(uuid4())


def _raw(name: str = "problem_mill_prep.json") -> dict:
    """A recording with a second worker and a second printer the print may use."""
    raw = json.loads((DATA / name).read_text(encoding="utf-8"))
    inst = raw["instance"]
    inst["workers"].append({**inst["workers"][0], "id": W2})
    am = next(m for m in inst["machines"] if m["equipment_type"] == "AM_SYSTEM")
    inst["machines"].append({**am, "id": M2, "name": "AM 2"})
    for o in inst["operations"]:
        if o["task_type"] == "AM_PREP":
            o["machine_options"].append(M2)
    for j in inst["jobs"]:
        if j["kind"] == "AM":
            j["equipment_id"] = None  # no machine chosen yet: both printers are options
    return raw


def _key(raw: dict, task_type: str) -> str:
    return next(o["key"] for o in raw["instance"]["operations"] if o["task_type"] == task_type and not o["done"])


def _assign(raw: dict, key: str, worker: str | None = None, machine: str | None = None) -> None:
    raw["instance"]["assignments"].append(
        {"key": key, "worker_id": worker or W2, "equipment_id": machine, "tie_break": None}
    )


def _pins(raw: dict):
    p = ProblemOut.model_validate(raw)
    epoch = epoch_of(p.as_of, BERLIN)
    ci = compile_instance(build_instance(p, epoch=epoch))
    ids = id_map(p, ci)
    snap = build_snapshot(p, ci, ids, epoch=epoch)
    return ci, ids, pin(ci, p, ids, {(f.order_id, f.op_id) for f in snap.frozen})


def test_an_assignment_pins_its_operations_to_the_machine_and_the_worker():
    raw = _raw()
    _assign(raw, _key(raw, "AM_PREP"), machine=M2)
    ci, ids, pins = _pins(raw)
    m2, w2 = ci.machine_ids.index(M2), ci.worker_ids.index(W2)
    for key in ids.ops[_key(raw, "AM_PREP")]:
        o = ci.op_index[key]
        assert len(ci.options[o]) == 2  # unpinned: both printers
        assert [m for m, _ in pins.ci.options[o]] == [m2], key
        assert all(sh.workers == (w2,) for sh in pins.ci.shares[o]), key
    assert pins.skipped == ()


def test_a_machine_pin_holds_for_the_whole_run():
    """AM_PREP (setup + print) and PART_POWDER_REMOVAL (removal) are one run on one machine."""
    raw = _raw()
    _assign(raw, _key(raw, "AM_PREP"), machine=M2)
    ci, ids, pins = _pins(raw)
    removal = ci.op_index[ids.ops[_key(raw, "PART_POWDER_REMOVAL")][0]]
    assert [m for m, _ in pins.ci.options[removal]] == [ci.machine_ids.index(M2)]
    assert pins.ci.shares[removal] == ci.shares[removal]  # its worker is not pinned


def test_a_machine_the_step_cannot_use_is_skipped_not_an_error():
    raw = _raw()
    _assign(raw, _key(raw, "AM_PREP"), machine=str(uuid4()))
    ci, _, pins = _pins(raw)
    assert pins.ci.options == ci.options and len(pins.skipped) == 2  # setup and print


def test_a_started_step_keeps_its_facts():
    raw = _raw()
    started = next(t["key"] for t in raw["snapshot"]["tasks"])
    _assign(raw, started)
    ci, ids, pins = _pins(raw)
    assert not set(ids.ops[started]) & set(pins.pinned)
    assert pins.ci.shares == ci.shares


def test_bound_follows_the_pin_and_free_is_published_as_free():
    raw = _raw()
    key = _key(raw, "POLISH")
    _assign(raw, key)
    p = ProblemOut.model_validate(raw)
    kw = {"epoch": epoch_of(p.as_of, BERLIN), "solved_at": datetime.fromisoformat(p.as_of.isoformat())}
    bound, free = solve(p, **kw, variant=BOUND), solve(p, **kw, variant=FREE)
    assert bound.violations == [] and free.violations == []
    assert bound.schedule.variant == BOUND and free.schedule.variant == FREE
    assert next(s for s in bound.schedule.steps if s.key == key).worker_id.hex == W2.replace("-", "")


@pytest.mark.parametrize("variants", [[], ["BOUND", "BOUND"], ["SOMETIMES"]])
def test_the_variants_setting_is_checked(variants):
    with pytest.raises(ValidationError):
        SchedulerConfig.model_validate({"variants": variants})


def test_both_variants_by_default():
    assert SchedulerConfig().variants == ("BOUND", "FREE")


def _factories(raw: dict):
    from fake_mes import FakeMes

    from mes_bridge.client import MesClient
    from mes_bridge.factory import MesFactory

    fake = FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    as_of = datetime.fromisoformat(raw["as_of"])
    epoch = epoch_of(as_of, BERLIN)
    make = lambda v: MesFactory(client, epoch=epoch, clock=lambda: as_of, variant=v)  # noqa: E731
    return fake, make(BOUND), make(FREE)


def test_each_variant_publishes_its_own_schedule():
    from simulation.control.rescheduling import ReschedulingPolicy
    from simulation.planners.dispatching import dispatch_planner, spt

    from mes_bridge.factory import step

    raw = _raw()
    _assign(raw, _key(raw, "POLISH"))
    fake, bound, free = _factories(raw)
    policy = ReschedulingPolicy(planner=dispatch_planner(spt))
    step(bound, policy, None, [])
    step(free, policy, None, [])
    assert [s.variant for s in fake.published] == [BOUND, FREE]
    assert bound.pins is not None and bound.pins.pinned and free.pins is None


def test_in_bound_a_changed_pin_is_an_instance_change_and_in_free_it_is_not():
    raw = _raw()
    key = _key(raw, "POLISH")
    _, bound, free = _factories(raw)
    assert bound.refresh() and free.refresh()  # the first refresh
    assert not bound.refresh() and not free.refresh()  # nothing changed
    _assign(raw, key)
    assert bound.refresh() and not free.refresh()  # a new pin
    assert not bound.refresh()
    raw["instance"]["assignments"][0]["worker_id"] = raw["instance"]["workers"][0]["id"]
    assert bound.refresh()  # the pin changed its worker
    raw["instance"]["assignments"].clear()
    assert bound.refresh()  # the pin was removed


def test_an_unknown_variant_is_rejected():
    from mes_bridge.factory import MesFactory

    with pytest.raises(ValueError, match="variant"):
        MesFactory(None, epoch=datetime(2026, 11, 23, tzinfo=BERLIN), variant="MAYBE")


def test_runners_step_every_variant_once_per_wake_and_wake_at_the_earliest_timer():
    from datetime import timedelta

    from simulation.control.rescheduling import ReschedulingPolicy
    from simulation.planners.dispatching import dispatch_planner, spt

    from mes_bridge.runner import Runner, Runners

    raw = _raw()
    fake, bound, free = _factories(raw)
    policy = ReschedulingPolicy(planner=dispatch_planner(spt))
    logs: list[str] = []
    rs = Runners(
        [Runner(bound, policy, log=logs.append), Runner(free, policy, poll=timedelta(minutes=1), log=logs.append)],
        log=logs.append,
    )
    rs.events.put({"type": "START"})
    now = datetime.fromisoformat(raw["as_of"])
    rs.tick(now, "event")
    assert [s.variant for s in fake.published] == [BOUND, FREE]
    assert rs.events.empty() and "BOUND event (1 events)" in logs[0] and "FREE event (1 events)" in logs[1]
    wake, _ = rs.next_wake(now)
    assert wake == min(r.next_wake(now)[0] for r in rs.runners) <= now + timedelta(minutes=1)


def test_one_variant_failing_does_not_stop_the_other():
    from simulation.control.rescheduling import ReschedulingPolicy
    from simulation.planners.dispatching import dispatch_planner, spt

    from mes_bridge.runner import RETRY, Runner, Runners

    raw = _raw()
    fake, bound, free = _factories(raw)
    policy = ReschedulingPolicy(planner=dispatch_planner(spt))

    def broken(*_a, **_k):
        raise RuntimeError("boom")

    bound.refresh = broken
    logs: list[str] = []
    rs = Runners([Runner(bound, policy, log=logs.append), Runner(free, policy, log=logs.append)], log=logs.append)
    rs.tick(datetime.fromisoformat(raw["as_of"]), "poll")
    assert [s.variant for s in fake.published] == [FREE]
    assert any("BOUND" in line and "step failed: boom" in line and "Traceback" in line for line in logs)
    # a failed step is retried soon, not at the safety poll (the MES restarting must not stall the plan 5 min)
    now = datetime.fromisoformat(raw["as_of"])
    wake, why = rs.next_wake(now)
    assert (wake - now, why) == (RETRY, "retry")
    del bound.refresh  # the MES is back
    rs.tick(now, "retry")
    assert not rs.failed and rs.next_wake(now)[1] != "retry"
