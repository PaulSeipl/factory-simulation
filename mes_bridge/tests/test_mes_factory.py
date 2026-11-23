"""The MES as a `Factory` of the thesis planning tool and the controller step (task 2.2a), against a fake MES."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fake_mes import FakeMes

from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory, step
from mes_bridge.instance import epoch_of
from simulation.control.rescheduling import Factory, ReschedulingPolicy
from simulation.planners.dispatching import dispatch_planner, spt

DATA = Path(__file__).parent / "data"
POLICY = ReschedulingPolicy(planner=dispatch_planner(spt))


def _setup(name: str = "problem_printing.json"):
    raw = json.loads((DATA / name).read_text(encoding="utf-8"))
    fake = FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    as_of = datetime.fromisoformat(raw["as_of"])
    factory = MesFactory(client, epoch=epoch_of(as_of, ZoneInfo("Europe/Berlin")), clock=lambda: as_of)
    return raw, fake, factory


def _print_key(raw) -> str:
    return next(t["key"] for t in raw["snapshot"]["tasks"] if t["key"].endswith(":AM_PREP"))


def test_the_mes_factory_is_a_factory():
    _, _, factory = _setup()
    assert isinstance(factory, Factory)


def test_the_first_step_plans_completely_and_publishes():
    _, fake, factory = _setup()
    decisions: list[dict] = []
    anchor = step(factory, POLICY, None, decisions)
    assert len(fake.published) == 1 and factory.rejected == []
    assert decisions[-1]["type"] == "REPLAN" and decisions[-1]["triggers"] == ["arrival"]
    key = lambda a: (a.order_id, a.op_id)  # noqa: E731
    assert sorted(anchor.plan, key=key) == sorted(factory.current_plan(), key=key)
    assert anchor.t == factory.snapshot().t


def test_nothing_changed_nothing_is_published():
    _, fake, factory = _setup()
    decisions: list[dict] = []
    anchor = step(factory, POLICY, None, decisions)
    again = step(factory, POLICY, anchor, decisions)
    assert len(fake.published) == 1 and again == anchor


def test_a_longer_print_is_repaired_and_the_shifted_plan_published():
    raw, fake, factory = _setup()
    decisions: list[dict] = []
    anchor = step(factory, POLICY, None, decisions)
    before = {s.key: s for s in fake.published[-1].steps}
    task = next(t for t in raw["snapshot"]["tasks"] if t["key"] == _print_key(raw))
    task["expected_end"] = (datetime.fromisoformat(task["expected_end"]) + timedelta(minutes=60)).isoformat()
    step(factory, POLICY, anchor, decisions)
    assert len(fake.published) == 2 and decisions[-1]["type"] == "REPAIR"
    after = {s.key: s for s in fake.published[-1].steps}
    key = _print_key(raw)
    assert after[key].end - before[key].end == timedelta(minutes=60)  # the frozen run ends at the new expectation
    removal = next(k for k in after if k.endswith(":PART_POWDER_REMOVAL"))
    assert after[removal].start >= after[key].end


def test_a_changed_set_of_operations_is_a_complete_rescheduling():
    raw, fake, factory = _setup()
    decisions: list[dict] = []
    anchor = step(factory, POLICY, None, decisions)
    # one plate's blasting is gone (e.g. a cancelled part): the instance changed
    gone = next(o for o in raw["instance"]["operations"] if o["key"].endswith(":2:SAND_BLASTING"))
    for o in raw["instance"]["operations"]:
        o["predecessors"] = [p for p in o["predecessors"] if p != gone["key"]]
        if o["key"].endswith(":2:MILL_PREP_SECONDARY"):
            o["predecessors"].append(gone["predecessors"][0])
    raw["instance"]["operations"].remove(gone)
    step(factory, POLICY, anchor, decisions)
    assert decisions[-1]["type"] == "REPLAN" and decisions[-1]["triggers"] == ["arrival"]
    assert len(fake.published) == 2 and gone["key"] not in {s.key for s in fake.published[-1].steps}


def test_a_plan_breaking_the_facts_is_not_published():
    raw, fake, factory = _setup()
    preps = [t for t in raw["snapshot"]["tasks"] if t["key"].endswith(":DATA_PREP_SEC_MILL")]
    preps[1]["started_at"], preps[1]["finished_at"] = preps[0]["started_at"], preps[0]["finished_at"]
    anchor = step(factory, POLICY, None, [])
    assert fake.published == [] and factory.rejected and factory.current_plan() == []
    assert anchor is not None


def test_nothing_arrived_is_nothing_to_plan():
    raw, fake, factory = _setup()
    raw["instance"]["operations"], raw["snapshot"]["tasks"] = [], []
    assert step(factory, POLICY, None, []) is None and fake.published == []
