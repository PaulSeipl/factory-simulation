"""The long-running scheduler (task 2.2b): wake on MES events and timers, run one planning step per wake.

    MES_SCHEDULER_PASSWORD=... MES_EVENTS_TOKEN=... uv run python -m mes_bridge.runner [--url] [--port 8765]

- Events (decision 14): the MES posts `{type, ids, at}` to `POST /events` with `Authorization: Bearer <token>` (the
  shared token from the environment). An event only wakes the loop; the state is always rebuilt from
  `GET /planning/problem`, so a lost event costs only delay. Events arriving during a step are merged into the next.
- Timers (scheduler-side, never sent by the MES): OVERDUE (a running step reaches its expected end), PLANNED_START
  (a planned start is reached; a step not started by then is repaired right), the periodic rescheduling deadline of
  the policy, and the safety poll (a step without any event).
- Variants (decision 4, task 6.1): one `Runner` per variant (BOUND, FREE), each with its factory, anchor and state
  directory; `Runners` drains the events once per wake, steps every variant and wakes at the earliest timer of any.
"""

import argparse
import json
import os
import queue
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from simulation.control.rescheduling import Anchor, ReschedulingPolicy

from mes_bridge.client import MesClient, http
from mes_bridge.config import SchedulerConfig
from mes_bridge.factory import MesFactory, step
from mes_bridge.instance import epoch_of
from mes_bridge.store import Saved, Store, resumable

SAFETY_POLL = timedelta(minutes=5)  # decision 14: a step without any event


def event_server(
    token: str, events: "queue.Queue[dict]", host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """`POST /events` into `events`; 401 without the shared token, 400 for a body that is not a JSON object."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 (http.server's name)
            if self.path != "/events":
                return self._reply(404)
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._reply(401)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
            except ValueError:
                return self._reply(400)
            if not isinstance(body, dict):
                return self._reply(400)
            events.put(body)
            self._reply(202)

        def log_message(self, *_args) -> None:  # quiet; the runner logs what it does
            pass

    return ThreadingHTTPServer((host, port), Handler)


@dataclass
class Runner:
    factory: MesFactory
    policy: ReschedulingPolicy
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    poll: timedelta = SAFETY_POLL
    anchor: Anchor | None = None
    decisions: list[dict] = field(default_factory=list)
    log: Callable[[str], None] = print
    store: Store | None = None
    _logged: int = 0  # decisions already written to the store

    def tick(self, now: datetime, reason: str) -> None:
        """One step for everything that happened since the last one."""
        merged = []
        while True:
            try:
                merged.append(self.events.get_nowait())
            except queue.Empty:
                break
        before = len(self.factory.rejected), self.factory.published
        self.anchor = step(self.factory, self.policy, self.anchor, self.decisions)
        rejected, published = len(self.factory.rejected) - before[0], self.factory.published - before[1]
        if self.store is not None:
            self.store.append_decisions(self.decisions[self._logged :], now)
            self._logged = len(self.decisions)
            if self.anchor is not None:
                f = self.factory
                saved = Saved(f.epoch, self.anchor, list(f.current_plan()), tuple(f.current_breaks()), f.publication)
                self.store.save(saved)
        self.log(f"{now.isoformat()} {reason}: {len(merged)} events, {published} published, {rejected} not published")

    def resume(self) -> bool:
        """Decision 22: continue from the saved state if the MES still serves its publication, else start fresh
        (the first step is then a complete rescheduling)."""
        saved = self.store.load() if self.store is not None else None
        if not resumable(saved, self.factory.client.schedules(), self.factory.variant, self.factory.epoch):
            self.log("no matching saved state: complete rescheduling")
            return False
        assert saved is not None
        self.factory.restore(saved.plan, saved.breaks, saved.publication)
        self.anchor = saved.anchor
        self.log(f"resumed from publication {saved.publication}")
        return True

    def next_wake(self, now: datetime) -> tuple[datetime, str]:
        """The earliest timer after now, at the latest the safety poll."""
        best = (now + self.poll, "poll")
        f = self.factory
        if f.ci is not None and f.current_plan():
            frozen = {(x.order_id, x.op_id): x for x in f.snapshot().frozen}
            for a in f.current_plan():
                fr = frozen.get((a.order_id, a.op_id))
                if fr is not None and not fr.running:
                    continue  # finished
                t, why = (a.end, "overdue") if fr is not None else (a.start, "planned_start")
                at = f.epoch + timedelta(minutes=t)
                if now < at < best[0]:
                    best = (at, why)
        if self.anchor is not None and self.policy.period is not None:
            at = f.epoch + timedelta(minutes=self.anchor.t + self.policy.period)
            if now < at < best[0]:
                best = (at, "period")
        return best

    def run(self, stop: threading.Event, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        _loop(self, self.events, stop, clock)


@dataclass
class Runners:
    """Several variants over one event queue (decision 4): each wake steps every variant, BOUND first."""

    runners: list[Runner]
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    log: Callable[[str], None] = print

    def resume(self) -> None:
        for r in self.runners:
            try:
                r.resume()
            except Exception as e:  # the MES may be down: that variant starts fresh
                self.log(f"{r.factory.variant}: resume failed: {e}")

    def tick(self, now: datetime, reason: str) -> None:
        merged = []
        while True:
            try:
                merged.append(self.events.get_nowait())
            except queue.Empty:
                break
        for r in self.runners:
            try:
                r.tick(now, f"{r.factory.variant} {reason} ({len(merged)} events)")
            except Exception as e:  # one variant failing does not stop the other
                self.log(f"{now.isoformat()} {r.factory.variant} {reason}: step failed: {e}")

    def next_wake(self, now: datetime) -> tuple[datetime, str]:
        return min((r.next_wake(now) for r in self.runners), key=lambda w: w[0])

    def run(self, stop: threading.Event, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        _loop(self, self.events, stop, clock)


def _loop(target, events: "queue.Queue[dict]", stop: threading.Event, clock: Callable[[], datetime]) -> None:
    """Resume, then step and sleep until the next timer or an event, until `stop`."""
    reason = "start"
    try:
        target.resume()
    except Exception as e:  # the MES may be down: start fresh
        target.log(f"resume failed: {e}")
    while not stop.is_set():
        now = clock()
        try:
            target.tick(now, reason)
        except Exception as e:  # the MES may be down: keep serving, try again at the next wake
            target.log(f"{now.isoformat()} {reason}: step failed: {e}")
        wake, reason = target.next_wake(clock())
        try:  # an event wakes the loop at once; it stays in the queue for the next tick
            events.put(events.get(timeout=max(0.0, (wake - clock()).total_seconds())))
            reason = "event"
        except queue.Empty:
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=os.environ.get("MES_URL", "http://localhost:8080"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--state-dir", default="mes_bridge_state", help="anchor.json and decisions.jsonl per variant")
    ap.add_argument("--config", help="SchedulerConfig JSON file (default: the defaults)")
    args = ap.parse_args(argv)
    password, token = os.environ.get("MES_SCHEDULER_PASSWORD"), os.environ.get("MES_EVENTS_TOKEN")
    if not password or not token:
        print("MES_SCHEDULER_PASSWORD and MES_EVENTS_TOKEN must be set", file=sys.stderr)
        return 2
    client = MesClient(http(args.url))
    client.login(os.environ.get("MES_SCHEDULER_USERNAME", "scheduler"), password)
    tz = ZoneInfo(client.problem().instance.calendar.time_zone)
    config = SchedulerConfig.load(args.config)
    epoch = epoch_of(datetime.now(UTC), tz)
    runner = Runners(
        [
            Runner(
                MesFactory(client, epoch=epoch, variant=variant),
                config.rescheduling_policy(),
                poll=timedelta(minutes=config.safety_poll_minutes),
                store=Store(args.state_dir, variant),
            )
            for variant in config.variants
        ]
    )
    server = event_server(token, runner.events, args.host, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()
    try:
        runner.run(stop)
    except KeyboardInterrupt:
        stop.set()
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
