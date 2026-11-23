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
from mes_bridge.client import MesClient, MesError
from mes_bridge.factory import MesFactory
from mes_bridge.instance import epoch_of
from mes_bridge.runner import Runner, _login_when_up, event_server
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
    fake, r, now, _ = _runner(poll=timedelta(seconds=30))
    fake.stale_minutes = 10**6  # the keep-alive deadline is not under test here
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
        if " start:" not in line and " event:" not in line:
            return  # the resume line
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


class _FlakyLogin:
    """A fake client whose login raises the given errors in order, then succeeds."""

    def __init__(self, *errors: Exception):
        self.errors = list(errors)
        self.calls = 0
        self.logged_in = False

    def login(self, user: str, password: str) -> None:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        self.logged_in = True


def test_login_retries_while_the_mes_is_unreachable():
    client = _FlakyLogin(ConnectionRefusedError(), urllib.error.URLError("refused"))
    sleeps, lines = [], []
    _login_when_up(client, "scheduler", "pw", "http://mes", sleep=sleeps.append, log=lines.append)
    assert client.logged_in and client.calls == 3
    assert sleeps == [5.0, 5.0]
    assert lines == ["MES not reachable at http://mes, retrying in 5 s"] * 2


def test_login_http_error_is_raised_without_retry():
    client = _FlakyLogin(MesError("POST", "/api/v1/auth/login", 401, {"detail": "bad password"}))
    sleeps = []
    with pytest.raises(MesError):
        _login_when_up(client, "scheduler", "pw", "http://mes", sleep=sleeps.append, log=lambda _: None)
    assert client.calls == 1 and sleeps == []


def test_login_reraises_when_every_attempt_fails():
    client = _FlakyLogin(*[ConnectionRefusedError()] * 3)
    sleeps, lines = [], []
    with pytest.raises(ConnectionRefusedError):
        _login_when_up(client, "scheduler", "pw", "http://mes", attempts=3, sleep=sleeps.append, log=lines.append)
    assert client.calls == 3 and sleeps == [5.0, 5.0] and len(lines) == 2


# --- keep-alive: the MES serves a schedule only while it is younger than scheduler_stale_minutes ---


def _clocked():
    """A runner whose factory clock is a mutable time: (fake, runner, clock cell, log lines)."""
    fake, r, now, lines = _runner()
    t = [now]
    r.factory._clock = lambda: t[0]
    return fake, r, t, lines


def test_keep_alive_does_not_republish_while_the_publication_is_young():
    fake, r, t, lines = _clocked()
    r.tick(t[0], "start")
    n = len(fake.published)
    t[0] += timedelta(minutes=14)  # < 30 / 2
    r.tick(t[0], "poll")
    assert len(fake.published) == n
    assert "kept alive" not in lines[-1]


def test_keep_alive_republishes_the_unchanged_plan_once_when_older_than_half_the_threshold():
    fake, r, t, lines = _clocked()
    r.tick(t[0], "start")
    first = fake.published[-1]
    n = len(fake.published)
    t[0] += timedelta(minutes=16)
    r.tick(t[0], "poll")
    assert len(fake.published) == n + 1
    again = fake.published[-1]
    assert again.steps == first.steps
    assert again.breaks == first.breaks
    assert again.solved_at > first.solved_at
    assert lines[-1].endswith("1 kept alive")
    r.tick(t[0], "poll")  # just published: nothing more
    assert len(fake.published) == n + 1


def test_the_first_tick_after_restore_republishes():
    fake, r, t, _ = _clocked()
    r.tick(t[0], "start")
    f = r.factory
    f2 = MesFactory(f.client, epoch=f.epoch, clock=lambda: t[0])
    f2.restore(f.current_plan(), f.current_breaks(), f.publication)
    r2 = Runner(f2, POLICY, anchor=r.anchor, log=lambda _m: None)
    n = len(fake.published)
    r2.tick(t[0], "start")
    assert len(fake.published) == n + 1  # the MES does not know the bridge restarted
    assert f2.last_published_at == t[0]


def test_a_failing_settings_call_does_not_break_the_tick():
    fake, r, t, lines = _clocked()
    fake.settings_status = 500
    r.tick(t[0], "start")
    assert len(fake.published) == 1  # the step itself published
    assert any("keep-alive failed" in x for x in lines)
    assert r.stale_minutes is None


def test_next_wake_is_the_keep_alive_deadline_when_it_is_the_earliest_timer():
    fake, r, t, _ = _clocked()
    fake.stale_minutes = 2  # deadline 1 min after the publication, before any other timer
    r.tick(t[0], "start")
    assert r.next_wake(t[0]) == (t[0] + timedelta(minutes=1), "keep_alive")
    fake.stale_minutes = 2000  # a late deadline loses against the poll
    r.tick(t[0], "poll")
    assert r.next_wake(t[0])[1] != "keep_alive"


def test_a_clock_behind_the_mes_never_publishes_a_solve_before_its_snapshot():
    """Found live: the MES's database clock ran 0.6 s ahead; a keep-alive right after reading the problem was
    refused (snapshot_as_of after solved_at). solved_at is at least the snapshot's time."""
    fake, r, t, _ = _clocked()
    r.factory._clock = lambda: t[0] - timedelta(hours=1)  # far behind the MES
    r.tick(t[0], "start")
    s = fake.published[-1]
    assert s.solved_at >= s.snapshot_as_of
