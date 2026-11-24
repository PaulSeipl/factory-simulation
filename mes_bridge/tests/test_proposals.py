"""Proposals (task 7.3): requested thorough solves in the background, and the take-over of an applied one."""

import copy
import json
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fake_mes import FakeMes
from simulation.model.schedule import Plan
from simulation.planners.dispatching import dispatch_planner, spt
from test_runner import DATA, POLICY, _runner

from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory
from mes_bridge.instance import epoch_of
from mes_bridge.proposals import ProposalWorker
from mes_bridge.runner import Runner

FAST = dispatch_planner(spt)


def _worker(r, planner, **kw) -> ProposalWorker:
    w = ProposalWorker(r.factory.client, planner, epoch=r.factory.epoch, clock=r.factory._clock, log=r.log, **kw)
    r.proposals = w
    return w


def _spy(calls: list, planner=FAST):
    def thorough(ci, snap, plan):
        calls.append(len(ci.op_keys))
        return planner(ci, snap, plan)

    return thorough


def test_a_requested_proposal_is_solved_with_the_thorough_planner_and_published():
    fake, r, _now, _ = _runner()
    calls: list = []
    w = _worker(r, _spy(calls), background=False)
    pid = fake.request()
    assert str(w.start_next()) == pid
    assert calls  # the thorough planner, not the policy's
    assert fake.proposals[pid]["status"] == "READY"
    assert fake.proposal_schedules[pid].variant == "BOUND" and fake.proposal_schedules[pid].steps
    assert fake.published == []  # never the current schedule
    assert w.start_next() is None  # nothing requested any more


def test_one_solve_at_a_time_and_the_automatic_steps_go_on():
    fake, r, now, _ = _runner()
    release, entered = threading.Event(), threading.Event()

    def slow(ci, snap, plan):
        entered.set()
        release.wait(5)
        return FAST(ci, snap, plan)

    w = _worker(r, slow)
    first = fake.request()
    assert str(w.start_next()) == first and entered.wait(5)
    second = fake.request()  # the MES discards the first
    assert w.busy and w.start_next() is None
    r.tick(now, "event")  # the automatic step is not blocked by the solve
    assert fake.published
    release.set()
    w._thread.join(5)
    assert fake.proposals[first]["status"] == "DISCARDED"  # its publication was refused (409): dropped
    assert first not in fake.proposal_schedules
    assert str(w.start_next()) == second


def test_a_failing_solve_reports_failed_with_why():
    fake, r, _now, _ = _runner()

    def broken(*_a):
        raise RuntimeError("solver crashed")

    w = _worker(r, broken, background=False)
    pid = fake.request()
    w.start_next()
    assert fake.proposals[pid]["status"] == "FAILED"
    assert "solver crashed" in fake.proposals[pid]["message"]


def test_a_proposal_the_fast_rule_planned_says_so():
    """CP-SAT found no plan (real MES data can make it infeasible, finding uu): the proposal is READY with the rule's
    plan, and its note tells the planner it is not the thorough solve."""
    fake, r, _now, _ = _runner()

    def thorough(ci, snap, plan):
        thorough.last = {"status": "INFEASIBLE", "fallback": "no solution"}
        return FAST(ci, snap, plan)

    w = _worker(r, thorough, background=False)
    pid = fake.request()
    w.start_next()
    assert fake.proposals[pid]["status"] == "READY"
    assert "fast rule planned instead" in fake.proposals[pid]["message"]
    plain = fake.request()
    _worker(r, _spy([]), background=False).start_next()
    assert fake.proposals[plain]["message"] is None


def test_a_plan_the_checker_rejects_is_failed_not_published():
    fake, r, _now, _ = _runner()
    w = _worker(r, lambda *_a: Plan([], ()), background=False)  # leaves every operation out
    pid = fake.request()
    w.start_next()
    assert fake.proposals[pid]["status"] == "FAILED" and "rules" in fake.proposals[pid]["message"]
    assert pid not in fake.proposal_schedules


def test_the_runner_starts_a_proposal_and_takes_an_applied_one_over():
    fake, r, now, lines = _runner()
    calls: list = []
    _worker(r, _spy(calls), background=False)
    r.tick(now, "start")  # the fast plan; nothing requested
    assert not calls
    pid = fake.request()
    r.tick(now, "event")  # PROPOSAL: the worker solves it
    assert calls and fake.proposals[pid]["status"] == "READY"
    proposal = {s.key: (s.start, s.end) for s in fake.proposal_schedules[pid].steps}
    fake.apply(pid)
    later = now + timedelta(minutes=1)
    r.tick(later, "event")
    assert any("applied, continuing from its plan" in line for line in lines)
    current = {s.key: (s.start, s.end) for s in r.factory.client.schedules()[0].steps}
    assert current == proposal  # the fast profile did not replan it
    assert r.anchor.t == int((later - r.factory.epoch).total_seconds() // 60)
    assert r.proposals.take_applied() is None  # taken once


def _without(raw: dict, order_id: str) -> dict:
    """The problem before `order_id` was planned (an un-nested order: order-keyed steps only)."""
    out = copy.deepcopy(raw)
    inst = out["instance"]
    gone = {o["key"] for o in inst["operations"] if order_id in o["order_ids"]}
    inst["orders"] = [o for o in inst["orders"] if o["id"] != order_id]
    inst["parts"] = [p for p in inst["parts"] if p["order_id"] != order_id]
    inst["operations"] = [o for o in inst["operations"] if o["key"] not in gone]
    inst["assignments"] = [a for a in inst["assignments"] if a["key"] not in gone]
    out["snapshot"]["tasks"] = [t for t in out["snapshot"]["tasks"] if t["key"] not in gone]
    return out


def test_after_the_take_over_the_new_orders_are_repaired_not_replanned():
    """Found in the end-to-end run: the step after the take-over compared the machine options of the instance
    before the apply (without the new order) and saw a machine change: a complete rescheduling with the fast
    profile replaced the proposal. The plan already covers the new order: a repair."""
    raw = json.loads((DATA / "problem_planned_flow.json").read_text(encoding="utf-8"))
    new = next(o["id"] for o in raw["instance"]["orders"] if o["short_id"] == "a31c7e44")  # un-nested
    fake = FakeMes(_without(raw, new))
    fake.whatif = raw
    client = MesClient(fake)
    client.login("scheduler", "pw")
    now = datetime.fromisoformat(raw["as_of"])
    factory = MesFactory(client, epoch=epoch_of(now, ZoneInfo("Europe/Berlin")), clock=lambda: now)
    r = Runner(factory, POLICY, log=[].append)
    _worker(r, FAST, background=False)
    r.tick(now, "start")
    assert not any(k.startswith(f"order:{new}:") for s in fake.published for k in (x.key for x in s.steps))
    pid = fake.request([new])
    r.tick(now, "event")  # solves the what-if
    proposal = {s.key: (s.start, s.end) for s in fake.proposal_schedules[pid].steps}
    assert any(k.startswith(f"order:{new}:") for k in proposal)
    fake.apply(pid)
    fake.problem = raw  # the MES plans the order: the live problem is the what-if now
    r.decisions.clear()
    r.tick(now, "event")
    assert not [d for d in r.decisions if d["type"] == "REPLAN"], r.decisions
    current = {s.key: (s.start, s.end) for s in client.schedules()[0].steps}
    assert current == proposal


def test_a_discarded_proposal_is_not_taken_over():
    fake, r, now, lines = _runner()
    _worker(r, FAST, background=False)
    pid = fake.request()
    r.tick(now, "start")
    fake.discard(pid)
    r.tick(now, "event")
    assert not any("applied" in line for line in lines)
    assert r.proposals._solved == {}


def test_solving_says_when_the_proposal_is_ready_at_the_latest():
    """The planners' "ready by" (task 7.5a): now + the thorough profile's longest solve + a minute."""
    fake, r, now, _ = _runner()
    w = _worker(r, FAST, background=False, max_seconds=1800)
    pid = fake.request()
    seen = {}
    status = w.client.proposal_status

    def spy(proposal_id, s, message=None, expected_by=None):
        seen.setdefault(s, expected_by)
        return status(proposal_id, s, message, expected_by)

    w.client.proposal_status = spy
    w.start_next()
    assert seen["SOLVING"] == r.factory._clock() + timedelta(minutes=31)
    assert fake.proposals[pid]["status"] == "READY"


def test_a_solve_left_behind_by_a_restart_is_failed_once():
    fake, r, _now, _ = _runner()
    left = fake.request()
    fake.proposals[left]["status"] = "SOLVING"  # the previous process took it and died
    w = _worker(r, FAST, background=False)
    assert w.start_next() is None
    assert fake.proposals[left]["status"] == "FAILED" and "restarted" in fake.proposals[left]["message"]
    fresh = fake.request()
    fake.proposals[fresh]["status"] = "SOLVING"  # this process's own solve: never failed again
    w.start_next()
    assert fake.proposals[fresh]["status"] == "SOLVING"


def test_the_longest_solve_of_a_profile():
    from mes_bridge.config import SolverConfig

    assert SolverConfig(kind="rule").max_solve_seconds == 0
    assert SolverConfig(kind="cpsat", time_limit=360).max_solve_seconds == 1800  # five levels: 30 min
    assert SolverConfig(kind="cpsat", objective="makespan", time_limit=360).max_solve_seconds == 360
    assert SolverConfig(kind="ga", time_limit=60).max_solve_seconds == 60
