"""The scheduler's state on disk and the restart check (task 2.2c, decision 22)."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fake_mes import FakeMes

from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory
from mes_bridge.instance import epoch_of
from mes_bridge.runner import Runner
from mes_bridge.store import Store
from simulation.control.rescheduling import ReschedulingPolicy
from simulation.planners.dispatching import dispatch_planner, spt

DATA = Path(__file__).parent / "data"
POLICY = ReschedulingPolicy(planner=dispatch_planner(spt))


def _runner(tmp_path: Path, fake: FakeMes | None = None, raw: dict | None = None, epoch_shift=timedelta(0)):
    raw = raw or json.loads((DATA / "problem_printing.json").read_text(encoding="utf-8"))
    fake = fake or FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(raw["as_of"])
    epoch = epoch_of(now, ZoneInfo("Europe/Berlin")) + epoch_shift
    lines: list[str] = []
    r = Runner(
        MesFactory(client, epoch=epoch, clock=lambda: now), POLICY, log=lines.append, store=Store(tmp_path, "BOUND")
    )
    return fake, r, now, lines


def test_every_step_saves_the_anchor_and_appends_its_decisions(tmp_path):
    fake, r, now, _ = _runner(tmp_path)
    r.tick(now, "start")
    saved = r.store.load()
    assert saved is not None and saved.publication is not None
    assert saved.publication == r.factory.publication and str(saved.publication) == fake.outs[-1]["id"]
    assert saved.plan == list(r.factory.current_plan()) and saved.anchor.t == r.anchor.t
    lines = r.store.decisions_file.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["type"] for x in lines] == ["REPLAN"]
    r.tick(now, "poll")  # nothing new: no further decision line
    assert len(r.store.decisions_file.read_text(encoding="utf-8").splitlines()) == 1


def test_a_restart_resumes_when_the_mes_still_serves_the_publication(tmp_path):
    fake, first, now, _ = _runner(tmp_path)
    first.tick(now, "start")
    _, again, _, lines = _runner(tmp_path, fake=fake, raw=fake.problem)
    assert again.resume() and "resumed" in lines[-1]
    assert again.anchor == first.store.load().anchor
    again.tick(now, "start")
    # same state, same plan: no complete rescheduling; only the keep-alive republishes the restored plan unchanged
    # (the MES does not know the bridge restarted)
    assert len(fake.published) == 2 and fake.published[1].steps == fake.published[0].steps
    assert all(d["type"] != "REPLAN" for d in again.decisions)


def test_a_restart_after_someone_else_published_reschedules_completely(tmp_path):
    fake, first, now, _ = _runner(tmp_path)
    first.tick(now, "start")
    first.tick(now, "start")
    fake.outs[-1] = dict(fake.outs[-1], id="00000000-0000-0000-0000-000000000001")  # another publication is current
    _, again, _, lines = _runner(tmp_path, fake=fake, raw=fake.problem)
    assert not again.resume() and "complete rescheduling" in lines[-1]
    again.tick(now, "start")
    assert again.decisions[-1]["type"] == "REPLAN" and len(fake.published) == 2


def test_a_restart_in_another_epoch_reschedules_completely(tmp_path):
    fake, first, now, _ = _runner(tmp_path)
    first.tick(now, "start")
    _, again, _, _ = _runner(tmp_path, fake=fake, raw=fake.problem, epoch_shift=timedelta(days=7))
    assert not again.resume()


def test_an_unreadable_state_starts_fresh(tmp_path):
    fake, r, now, _ = _runner(tmp_path)
    r.tick(now, "start")
    r.store.anchor_file.write_text("{not json", encoding="utf-8")
    assert r.store.load() is None
    _, again, _, _ = _runner(tmp_path, fake=fake, raw=fake.problem)
    assert not again.resume()


def test_without_a_saved_state_there_is_nothing_to_resume(tmp_path):
    _, r, _, _ = _runner(tmp_path)
    assert not r.resume() and r.anchor is None
