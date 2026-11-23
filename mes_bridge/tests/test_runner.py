"""The long-running scheduler (task 2.2b): the event endpoint, merging, timers, the loop, the re-login."""

import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fake_mes import FakeMes

from mes_bridge import runner as runner_mod
from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory
from mes_bridge.instance import epoch_of
from mes_bridge.runner import Runner, event_server
from simulation.control.rescheduling import ReschedulingPolicy
from simulation.planners.dispatching import dispatch_planner, spt

DATA = Path(__file__).parent / "data"
POLICY = ReschedulingPolicy(planner=dispatch_planner(spt))


def _runner(policy=POLICY, **kw):
    raw = json.loads((DATA / "problem_printing.json").read_text(encoding="utf-8"))
    fake = FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(raw["as_of"])
    factory = MesFactory(client, epoch=epoch_of(now, ZoneInfo("Europe/Berlin")), clock=lambda: now)
    lines: list[str] = []
    return fake, Runner(factory, policy, log=lines.append, **kw), now, lines


@pytest.fixture
def server():
    events: queue.Queue = queue.Queue()
    srv = event_server("secret", events, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", events
    srv.shutdown()


def _post(url: str, body: bytes, token: str | None = "secret") -> int:
    headers = {"Content-Type": "application/json"} | ({"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method="POST")) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_an_event_with_the_shared_token_is_queued(server):
    url, events = server
    assert _post(url + "/events", b'{"type": "START", "ids": ["x"], "at": "2026-11-23T10:00:00Z"}') == 202
    assert events.get_nowait()["type"] == "START"


@pytest.mark.parametrize(
    ("path", "body", "token", "status"),
    [
        ("/events", b"{}", None, 401),
        ("/events", b"{}", "wrong", 401),
        ("/events", b"not json", "secret", 400),
        ("/events", b"[1, 2]", "secret", 400),
        ("/other", b"{}", "secret", 404),
    ],
)
def test_a_bad_event_request_is_refused_and_not_queued(server, path, body, token, status):
    url, events = server
    assert _post(url + path, body, token) == status
    assert events.empty()


def test_events_since_the_last_step_are_merged_into_one():
    fake, r, now, lines = _runner()
    for i in range(3):
        r.events.put({"type": "START", "ids": [str(i)]})
    r.tick(now, "event")
    assert r.events.empty() and len(fake.published) == 1
    assert "3 events, 1 published" in lines[-1]


def test_the_next_wake_is_the_earliest_timer_or_the_poll():
    _, r, now, _ = _runner(poll=timedelta(seconds=30))
    r.tick(now, "start")
    assert r.next_wake(now) == (now + timedelta(seconds=30), "poll")
    r.poll = timedelta(days=30)
    at, why = r.next_wake(now)
    assert why in ("planned_start", "overdue") and now < at < now + timedelta(days=30)
    starts = [r.factory.epoch + timedelta(minutes=a.start) for a in r.factory.current_plan()]
    assert at <= min(s for s in starts if s > now) or why == "overdue"


def test_the_periodic_deadline_is_a_timer():
    _, r, now, _ = _runner(policy=ReschedulingPolicy(planner=dispatch_planner(spt), period=1), poll=timedelta(days=30))
    r.tick(now, "start")
    at, why = r.next_wake(now)
    assert why == "period" and at == r.factory.epoch + timedelta(minutes=r.anchor.t + 1)


def test_an_event_wakes_the_loop_and_a_failing_step_does_not_stop_it():
    fake, r, now, lines = _runner(poll=timedelta(days=1))
    stop = threading.Event()
    calls = []

    def log(line):
        calls.append(line)
        if len(calls) == 1:
            fake.problem_status = 500  # the MES goes down: the next step fails
            r.events.put({"type": "COMPLETE"})
        else:
            stop.set()
            r.events.put({"type": "COMPLETE"})

    r.log = log
    r.run(stop, clock=lambda: now)
    assert "start" in calls[0] and "event: step failed" in calls[1]


def test_an_expired_token_is_renewed_once():
    fake, r, _, _ = _runner()
    fake.token = "rotated"  # the MES no longer accepts the old token
    assert r.factory.client.problem().instance.operations
    assert fake.logins == 2


def test_the_runner_needs_its_secrets_in_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("MES_SCHEDULER_PASSWORD", raising=False)
    monkeypatch.delenv("MES_EVENTS_TOKEN", raising=False)
    assert runner_mod.main(["--url", "http://127.0.0.1:9"]) == 2
    assert "MES_EVENTS_TOKEN" in capsys.readouterr().err
