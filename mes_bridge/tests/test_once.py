"""One-shot fetch -> SPT -> check -> publish (task 1.6) against a fake MES replaying the recorded responses."""

import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from mes_bridge import once
from mes_bridge.api import ProblemOut
from mes_bridge.client import MesClient, MesError
from mes_bridge.instance import MAPPED
from fake_mes import FakeMes

DATA = Path(__file__).parent / "data"


def _raw(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _run(raw: dict, **kw):
    fake = FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(raw["as_of"])
    return fake, once.run(client, now=now, **kw)


@pytest.mark.parametrize("name", ["problem_mill_prep.json", "problem_printing.json", "problem_blank.json"])
def test_a_feasible_rule_plan_is_published_one_step_per_open_mes_step(name):
    raw = _raw(name)
    fake, outcome = _run(raw)
    assert outcome.violations == [] and fake.published == [outcome.schedule]
    p = ProblemOut.model_validate(raw)
    open_keys = {o.key for o in p.instance.operations if not o.done and o.task_type in MAPPED}
    s = outcome.schedule
    assert {st.key for st in s.steps} == open_keys
    assert s.variant == "BOUND" and s.snapshot_as_of == p.as_of
    for st in s.steps:
        assert st.start <= st.attended_end <= st.end, st.key


def test_a_print_step_is_attended_until_the_handoff_and_ends_with_the_run():
    raw = _raw("problem_printing.json")
    _, outcome = _run(raw)
    am = next(j["id"] for j in raw["instance"]["jobs"] if j["kind"] == "AM")
    st = next(s for s in outcome.schedule.steps if s.key == f"job:{am}:AM_PREP")
    task = next(t for t in raw["snapshot"]["tasks"] if t["key"] == st.key)
    assert st.start == datetime.fromisoformat(task["started_at"])
    assert st.attended_end == datetime.fromisoformat(task["handoff_at"])
    assert st.end == datetime.fromisoformat(task["expected_end"])  # the frozen run's expected end
    assert str(st.equipment_id) == task["equipment_id"] and str(st.worker_id) == task["worker_id"]


def test_the_oven_is_attended_for_its_loading_only():
    _, outcome = _run(_raw("problem_mill_prep.json"))
    oven = next(s for s in outcome.schedule.steps if s.key.endswith(":HEAT_TREATMENT"))
    assert oven.attended_end - oven.start == timedelta(minutes=35)  # 30 + 5 per plate, then the program
    assert oven.end - oven.attended_end == timedelta(minutes=180)
    assert oven.worker_id is not None and oven.equipment_id is None


def test_a_plan_with_violations_is_not_published():
    """Facts that break a model rule (one worker on two tasks at once) make every plan infeasible: not published."""
    raw = _raw("problem_printing.json")
    preps = [t for t in raw["snapshot"]["tasks"] if t["key"].endswith(":DATA_PREP_SEC_MILL")]
    preps[1]["started_at"], preps[1]["finished_at"] = preps[0]["started_at"], preps[0]["finished_at"]
    fake, outcome = _run(raw)
    assert outcome.schedule is None and fake.published == []
    assert {v.constraint for v in outcome.violations} >= {"C12"}


def test_nothing_arrived_publishes_an_empty_schedule():
    raw = _raw("problem_mill_prep.json")
    raw["instance"]["operations"], raw["snapshot"]["tasks"] = [], []
    fake, outcome = _run(raw)
    assert fake.published and fake.published[0].steps == []


def test_the_schedule_carries_the_plans_breaks_and_no_step_overlaps_them():
    """Task 4.3 (decision 21): one break per worker and day, the MES's length; the worker's steps leave it free."""
    raw = _raw("problem_blank.json")
    _, outcome = _run(raw)
    s = outcome.schedule
    assert s.breaks
    length = timedelta(minutes=raw["instance"]["calendar"]["break_minutes"])
    days = [(b.worker_id, b.start.date()) for b in s.breaks]
    assert len(days) == len(set(days))
    for b in s.breaks:
        assert b.end - b.start == length
        for st in s.steps:
            if st.worker_id == b.worker_id:
                assert st.attended_end <= b.start or st.start >= b.end, (st.key, b)


def test_a_dry_run_does_not_publish():
    fake, outcome = _run(_raw("problem_mill_prep.json"), dry_run=True)
    assert outcome.schedule is not None and fake.published == []


def test_a_wrong_password_fails_the_login():
    with pytest.raises(MesError, match="401"):
        MesClient(FakeMes(_raw("problem_mill_prep.json"))).login("scheduler", "wrong")


def test_without_a_login_the_problem_is_refused():
    with pytest.raises(MesError, match="401"):
        MesClient(FakeMes(_raw("problem_mill_prep.json"))).problem()


def test_the_command_needs_the_password_in_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("MES_SCHEDULER_PASSWORD", raising=False)
    assert once.main(["--url", "http://127.0.0.1:9"]) == 2
    assert "MES_SCHEDULER_PASSWORD" in capsys.readouterr().err
