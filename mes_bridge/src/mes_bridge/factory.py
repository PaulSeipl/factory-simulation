"""The MES as a `Factory` of the thesis planning tool (task 2.2a), and one controller step.

`MesFactory` holds the latest problem with its instance and the plan last published. It is what `adapt_plan` sees:
- `snapshot()`: the MES's started tasks as the frozen part (`state.build_snapshot`);
- `current_plan()` / `current_breaks()`: the plan last sent (published), in the current instance's operations;
- `update_plan(plan, breaks)`: check it against the snapshot (decision 23) and publish it as the BOUND schedule; a
  plan with violations is recorded in `rejected` and not published, and the factory keeps its current plan.

`step(factory, policy)` is one turn of the planning tool: fetch the problem, rebuild the instance; if its set of
operations changed (an arrival, a cancellation, a scrap, a rework: decision 18) the step is a complete rescheduling
(`arrived=True`), otherwise `adapt_plan` repairs and maybe reschedules. The first step plans from scratch.
Time: minutes since the epoch fixed at the bridge's start (decision 17).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from simulation.check.feasibility import Violation, check_schedule
from simulation.control.rescheduling import Anchor, ReschedulingPolicy, adapt_plan
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.schedule import Assignment, Break, Plan
from simulation.sim.des import PlanNotExecutable
from simulation.sim.snapshot import Snapshot

from mes_bridge.api import ProblemOut, ScheduleIn
from mes_bridge.client import MesClient
from mes_bridge.instance import build_instance
from mes_bridge.once import VARIANT, schedule_breaks, steps
from mes_bridge.state import IdMap, build_snapshot, id_map


class MesFactory:
    def __init__(self, client: MesClient, *, epoch: datetime, clock=lambda: datetime.now(UTC)):
        self.client, self.epoch, self._clock = client, epoch, clock
        self.problem: ProblemOut | None = None
        self.ci: CompiledInstance | None = None
        self.ids: IdMap | None = None
        self._plan: list[Assignment] = []
        self._breaks: tuple[Break, ...] = ()
        self.rejected: list[list[Violation]] = []  # plans not published (decision 23), newest last
        self.published = 0
        self.publication: UUID | None = None  # id of the last publication in the MES
        self._known: set[tuple[str, str]] | None = None  # the operations of the instance the plan covers

    def refresh(self) -> bool:
        """Fetch the problem and rebuild the instance; True if its set of operations changed (or it is the first)."""
        problem = self.client.problem()
        before = self._known
        self.problem = problem
        if not problem.instance.operations:
            self.ci, self.ids, self._known = None, None, None
            return before is not None
        self.ci = compile_instance(build_instance(problem, epoch=self.epoch))
        self.ids = id_map(problem, self.ci)
        self._known = set(self.ci.op_keys)
        return before != self._known

    def restore(self, plan: Sequence[Assignment], breaks: Sequence[Break], publication: UUID | None) -> None:
        """Continue from a saved state (decision 22): the plan it published, over the operations that plan covers."""
        self._plan, self._breaks, self.publication = list(plan), tuple(breaks), publication
        self._known = {(a.order_id, a.op_id) for a in plan}

    # --- Factory ---

    def snapshot(self) -> Snapshot:
        assert self.problem is not None and self.ci is not None and self.ids is not None
        return build_snapshot(self.problem, self.ci, self.ids, epoch=self.epoch)

    def current_plan(self) -> Sequence[Assignment]:
        """The plan as executed: a started operation with its real machine, workers and times (in the DES the factory
        follows its plan; in the MES a worker may start a step another way than proposed, found by the end-to-end
        run, 2.4)."""
        if not self._plan or self.ci is None or self.problem is None:
            return list(self._plan)
        frozen = {(f.order_id, f.op_id): f for f in self.snapshot().frozen}
        out = []
        for a in self._plan:
            if (f := frozen.get((a.order_id, a.op_id))) is None:
                out.append(a)
                continue
            workers = tuple(w if w is not None else p for w, p in zip(f.workers, a.workers or f.workers, strict=False))
            out.append(
                a.model_copy(
                    update={
                        "machine": f.machine,
                        "start": f.start,
                        "end": f.end,
                        "workers": workers if all(workers) else a.workers,
                        "share_lengths": f.share_lengths,
                    }
                )
            )
        return out

    def current_breaks(self) -> Sequence[Break]:
        return self._breaks

    def update_plan(self, plan: Sequence[Assignment], breaks: Sequence[Break] | None = None) -> None:
        assert self.problem is not None and self.ci is not None and self.ids is not None
        new_breaks = self._breaks if breaks is None else tuple(breaks)
        if violations := check_schedule(self.ci, plan, self.snapshot(), new_breaks):
            self.rejected.append(violations)
            return
        out = self.client.publish(
            ScheduleIn(
                variant=VARIANT,
                snapshot_as_of=self.problem.as_of,
                solved_at=self._clock(),
                steps=steps(self.problem, self.ci, self.ids, Plan(list(plan), new_breaks), self.epoch),
                breaks=schedule_breaks(self.problem, Plan(list(plan), new_breaks), self.epoch),
            )
        )
        # in operation order, as the DES returns its plan: adapt_plan compares plans position by position
        self._plan = sorted(plan, key=lambda x: self.ci.op_index[x.order_id, x.op_id])
        self._breaks = new_breaks
        self.published += 1
        self.publication = out.id


def step(
    factory: MesFactory, policy: ReschedulingPolicy, anchor: Anchor | None, decisions: list[dict]
) -> Anchor | None:
    """One turn of the planning tool over the MES; returns the anchor for the next turn (None: nothing to plan).

    A changed set of operations (or the first turn) is `adapt_plan`'s `arrived` case: a complete rescheduling at once,
    accepted regardless of the budget. A planner plan the checker rejects (facts that break a model rule, see the
    known unknowns) is recorded in `factory.rejected`; the factory keeps its plan."""
    changed = factory.refresh()
    if factory.ci is None:  # nothing has arrived
        return None
    if anchor is None:
        anchor = Anchor([], 0)
    try:
        return adapt_plan(factory.ci, factory, policy, decisions, anchor, arrived=changed)
    except PlanNotExecutable as e:
        factory.rejected.append([Violation(constraint="planner", ops=(), message=str(e))])
        return anchor
