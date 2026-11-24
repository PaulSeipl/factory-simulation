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
- Proposals (task 7.3): after each step the BOUND runner starts the oldest requested proposal in the background
  (`proposals.ProposalWorker`, thorough profile); before each step it takes an applied one over as its plan.
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback
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
from mes_bridge.once import BOUND
from mes_bridge.proposals import ProposalWorker
from mes_bridge.store import Saved, Store, resumable

SAFETY_POLL = timedelta(minutes=5)  # decision 14: a step without any event
RETRY = timedelta(seconds=30)  # after a failed step (the MES restarting, say): not the safety poll
STARTUP_ATTEMPTS = 60  # the MES may start after the bridge: 60 x 5 s, about 5 min
STARTUP_WAIT = 5.0


def _login_when_up(
    client: MesClient,
    user: str,
    password: str,
    url: str,
    *,
    attempts: int = STARTUP_ATTEMPTS,
    wait: float = STARTUP_WAIT,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> None:
    """Log in, retrying while the MES is unreachable (OSError, e.g. connection refused). An HTTP error status
    (MesError, e.g. 401) is not retried. Re-raises the last OSError after `attempts` tries."""
    for attempt in range(1, attempts + 1):
        try:
            client.login(user, password)
            return
        except OSError:
            if attempt == attempts:
                raise
            log(f"MES not reachable at {url}, retrying in {wait:g} s")
            sleep(wait)


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
    policy: ReschedulingPolicy  # the automatic path, always the fast profile (task 7.2)
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    # BOUND only: requested proposals, solved with the thorough profile in their own thread (task 7.3); `tick` itself
    # always plans with the policy's fast planner
    proposals: ProposalWorker | None = None
    poll: timedelta = SAFETY_POLL
    anchor: Anchor | None = None
    decisions: list[dict] = field(default_factory=list)
    log: Callable[[str], None] = print
    store: Store | None = None
    stale_minutes: int | None = None  # the MES's scheduler_stale_minutes as last read (keep-alive deadline)
    _logged: int = 0  # decisions already written to the store

    def tick(self, now: datetime, reason: str) -> None:
        """One step for everything that happened since the last one."""
        merged = []
        while True:
            try:
                merged.append(self.events.get_nowait())
            except queue.Empty:
                break
        self._take_applied(now)
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
        kept = self._keep_alive()
        self.log(
            f"{now.isoformat()} {reason}: {len(merged)} events, {published} published, {rejected} not published"
            + (f", {kept} kept alive" if kept else "")
        )
        self._start_proposal()

    def _take_applied(self, now: datetime) -> None:
        """An applied proposal is the current plan: continue from it (the step after it repairs, it does not replan
        the new orders with the fast profile), as a complete rescheduling at `now` (the anchor)."""
        if self.proposals is None:
            return
        try:
            applied = self.proposals.take_applied()
        except Exception as e:  # the MES may be down: the next tick asks again
            self.log(f"proposal check failed: {str(e)[:300]}")
            return
        if applied is None:
            return
        f = self.factory
        current = next((s for s in f.client.schedules() if s.variant == f.variant), None)
        f.restore(applied.plan.assignments, applied.plan.breaks, current.id if current is not None else None)
        t = int((now - f.epoch).total_seconds() // 60)
        self.anchor = Anchor(list(applied.plan.assignments), t, tuple(applied.plan.breaks))
        self.log(f"proposal {applied.proposal_id}: applied, continuing from its plan")

    def _start_proposal(self) -> None:
        if self.proposals is None:
            return
        try:
            self.proposals.start_next()
        except Exception as e:  # the MES may be down: the next tick tries again
            self.log(f"proposal start failed: {str(e)[:300]}")

    def _keep_alive(self) -> int:
        """Republish an unchanged plan before the MES calls the scheduler stale; a failure is logged, not raised."""
        try:
            self.stale_minutes = self.factory.client.settings().scheduler_stale_minutes
            return int(self.factory.keep_alive(self.stale_minutes))
        except Exception as e:  # the step itself went through
            self.log(f"keep-alive failed: {str(e)[:300]}")
            return 0

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
        if f.last_published_at is not None and self.stale_minutes is not None and f.ci is not None and f.current_plan():
            at = f.last_published_at + timedelta(minutes=self.stale_minutes / 2)
            if now < at < best[0]:
                best = (at, "keep_alive")
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
    failed: bool = False  # the last tick had a failing variant: retry after RETRY

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
        self.failed = False
        for r in self.runners:
            try:
                r.tick(now, f"{r.factory.variant} {reason} ({len(merged)} events)")
            except Exception as e:  # one variant failing does not stop the other
                self.failed = True
                self.log(f"{now.isoformat()} {r.factory.variant} {reason}: step failed: {e}\n{traceback.format_exc()}")

    def next_wake(self, now: datetime) -> tuple[datetime, str]:
        wakes = [r.next_wake(now) for r in self.runners]
        if self.failed:
            wakes.append((now + RETRY, "retry"))
        return min(wakes, key=lambda w: w[0])

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
    if hasattr(sys.stdout, "reconfigure"):  # a log redirected to a file shows every line at once
        sys.stdout.reconfigure(line_buffering=True)
    password, token = os.environ.get("MES_SCHEDULER_PASSWORD"), os.environ.get("MES_EVENTS_TOKEN")
    if not password or not token:
        print("MES_SCHEDULER_PASSWORD and MES_EVENTS_TOKEN must be set", file=sys.stderr)
        return 2
    client = MesClient(http(args.url))
    _login_when_up(client, os.environ.get("MES_SCHEDULER_USERNAME", "scheduler"), password, args.url)
    tz = ZoneInfo(client.problem().instance.calendar.time_zone)
    config = SchedulerConfig.load(args.config)
    epoch = epoch_of(datetime.now(UTC), tz)
    runner = Runners(
        [
            Runner(
                MesFactory(client, epoch=epoch, variant=variant),
                config.rescheduling_policy(),
                proposals=ProposalWorker(client, config.thorough_planner(), epoch=epoch) if variant == BOUND else None,
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
