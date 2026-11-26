"""Proposals (task 7.3): thorough solves a planner requested, run in the background.

A planner's *Plan selected* or *Update plan* creates a REQUESTED proposal in the MES (planned nesting flow). The
worker takes the oldest one (SOLVING), solves its what-if problem (the selected orders planned) with the thorough
profile in its own thread, so the automatic steps go on with the fast one, and publishes the schedule to the proposal
(READY) or gives up (FAILED, with why). Only one solve runs at a time. A proposal discarded meanwhile refuses the
publication (409); the solve is then dropped.

When the planner applies a proposal, the MES makes its schedule the current BOUND one; `take_applied` hands the
plan to the BOUND runner, which continues from it (`MesFactory.restore`) instead of replanning the new orders with
the fast profile.
"""

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from simulation.control.rescheduling import Planner
from simulation.planners.cpsat import Stopped
from simulation.model.schedule import Plan

from mes_bridge.client import MesClient, MesError
from mes_bridge.once import BOUND, solve

REQUESTED, SOLVING, APPLIED, DISCARDED, FAILED = "REQUESTED", "SOLVING", "APPLIED", "DISCARDED", "FAILED"
MESSAGE_LIMIT = 500  # characters of a FAILED message
MARGIN = timedelta(minutes=1)  # export, check and publish around the solve
RESTARTED = "The scheduler restarted during the solve; request the proposal again."


@dataclass(frozen=True)
class Solved:
    proposal_id: UUID
    plan: Plan  # in the minutes of the worker's epoch (the factory's)


class ProposalWorker:
    def __init__(
        self,
        client: MesClient,
        planner: Planner,
        *,
        epoch: datetime,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        log: Callable[[str], None] = print,
        background: bool = True,  # tests: solve in the caller's thread
        max_seconds: float = 0.0,  # the thorough profile's longest solve, for the planners' "ready by"
        stop: threading.Event | None = None,  # the planner's stop hook: set when the running proposal is dropped
    ):
        self.client, self.planner, self.epoch, self._clock, self.log = client, planner, epoch, clock, log
        self.background, self.max_seconds = background, max_seconds
        self._recovered = False
        self.stop = stop
        self._running: UUID | None = None  # the proposal being solved
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._solved: dict[UUID, Solved] = {}  # published, waiting for the planner

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_next(self) -> UUID | None:
        """Take the oldest REQUESTED proposal unless a solve is running; its id, or None. A running solve whose
        proposal was discarded meanwhile (or replaced by a new request) is stopped, so the next need not wait."""
        if self.busy:
            self._stop_if_dropped()
            return None
        if not self._recovered:  # a solve this process does not run any more: nobody would ever finish it
            for left in self.client.proposals(status=SOLVING):
                self._fail(left.id, RESTARTED)
            self._recovered = True
        requested = self.client.proposals(status=REQUESTED)
        if not requested:
            return None
        proposal = requested[-1]  # the list is newest first; the MES keeps one open anyway
        try:
            expected_by = self._clock() + timedelta(seconds=self.max_seconds) + MARGIN
            self.client.proposal_status(proposal.id, SOLVING, expected_by=expected_by)
        except MesError as e:
            if e.status == 409:  # discarded or taken meanwhile
                return None
            raise
        self.log(f"proposal {proposal.id}: solving ({len(proposal.order_ids)} orders)")
        self._running = proposal.id
        if self.stop is not None:
            self.stop.clear()
        if self.background:
            self._thread = threading.Thread(target=self._solve, args=(proposal.id,), daemon=True)
            self._thread.start()
        else:
            self._solve(proposal.id)
        return proposal.id

    def _stop_if_dropped(self) -> None:
        if self.stop is None or self._running is None or self.stop.is_set():
            return
        if self.client.proposal(self._running).status != SOLVING:  # discarded: nobody wants this plan any more
            self.log(f"proposal {self._running}: dropped during the solve, stopping it")
            self.stop.set()

    def take_applied(self) -> Solved | None:
        """A solved proposal the planner applied since the last call (dropped: discarded ones)."""
        with self._lock:
            waiting = list(self._solved)
        for pid in waiting:
            status = self.client.proposal(pid).status
            if status in (APPLIED, DISCARDED):
                with self._lock:
                    solved = self._solved.pop(pid, None)
                if status == APPLIED and solved is not None:
                    return solved
        return None

    def _solve(self, proposal_id: UUID) -> None:
        try:
            problem = self.client.proposal_problem(proposal_id)
            outcome = solve(problem, epoch=self.epoch, solved_at=self._clock(), variant=BOUND, planner=self.planner)
            if outcome.schedule is None:
                why = "; ".join(f"{v.constraint}: {v.message}" for v in outcome.violations[:5])
                self._fail(proposal_id, f"the plan breaks {len(outcome.violations)} rules: {why}")
                return
            solved_at = max(self._clock(), problem.as_of)  # the solve took a while; the MES clock may run ahead
            schedule = outcome.schedule.model_copy(update={"solved_at": solved_at})
            fallback = (getattr(self.planner, "last", None) or {}).get("fallback")
            note = f"The thorough solver found no plan ({fallback}); the fast rule planned instead." if fallback else None
            self.client.publish_proposal(proposal_id, schedule, note[:MESSAGE_LIMIT] if note else None)
            if outcome.plan is not None:
                with self._lock:
                    self._solved[proposal_id] = Solved(proposal_id, outcome.plan)
            self.log(f"proposal {proposal_id}: ready ({len(schedule.steps)} steps)")
        except Stopped:
            self.log(f"proposal {proposal_id}: solve stopped")
        except MesError as e:
            if e.status == 409:
                self.log(f"proposal {proposal_id}: dropped ({e})")
                return
            self._fail(proposal_id, str(e))
        except Exception as e:  # the thread must not die silently: the planner waits for an answer
            self.log(f"proposal {proposal_id}: failed: {e}\n{traceback.format_exc()}")
            self._fail(proposal_id, f"{type(e).__name__}: {e}")

    def _fail(self, proposal_id: UUID, message: str) -> None:
        self.log(f"proposal {proposal_id}: failed: {message}")
        try:
            self.client.proposal_status(proposal_id, FAILED, message[:MESSAGE_LIMIT])
        except Exception as e:  # discarded meanwhile, or the MES is down: nothing more to do
            self.log(f"proposal {proposal_id}: could not report the failure: {e}")
