"""The MES as a `Factory` of the thesis planning tool (task 2.2a), and one controller step.

`MesFactory` holds the latest problem with its instance and the plan last published. It is what `adapt_plan` sees:
- `snapshot()`: the MES's started tasks as the frozen part (`state.build_snapshot`);
- `current_plan()` / `current_breaks()`: the plan last sent (published), in the current instance's operations;
- `update_plan(plan, breaks)`: check it against the snapshot (decision 23) and publish it as its variant's schedule;
  a plan with violations is recorded in `rejected` and not published, and the factory keeps its current plan.

One factory per variant (decision 4, task 6.1): BOUND plans the instance with the assignments as pins
(`state.pin`), FREE the instance without them. In BOUND a changed pin is an instance change as well.

`step(factory, policy)` is one turn of the planning tool: fetch the problem, rebuild the instance; if its set of
operations changed (an arrival, a cancellation, a scrap, a rework: decision 18) the step is a complete rescheduling
(`arrived=True`), otherwise `adapt_plan` repairs and maybe reschedules. The first step plans from scratch.
Time: minutes since the epoch fixed at the bridge's start (decision 17).
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from simulation.check.feasibility import Violation, check_schedule
from simulation.control.rescheduling import Anchor, ReschedulingPolicy, adapt_plan
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.schedule import Assignment, Break, Plan
from simulation.sim.des import PlanNotExecutable
from simulation.sim.snapshot import Snapshot

from mes_bridge.api import ProblemOut, ScheduleIn
from mes_bridge.assumed import Aliases, assume_plates
from mes_bridge.client import MesClient
from mes_bridge.instance import build_instance
from mes_bridge.mapping import map_plan, retime
from mes_bridge.once import BOUND, FREE, schedule_breaks, steps
from mes_bridge.state import IdMap, Pins, build_snapshot, id_map, out_of_service, pin


class MesFactory:
    def __init__(self, client: MesClient, *, epoch: datetime, clock=lambda: datetime.now(UTC), variant: str = BOUND):
        if variant not in (BOUND, FREE):
            raise ValueError(f"unknown variant {variant!r}")
        self.client, self.epoch, self._clock, self.variant = client, epoch, clock, variant
        self.pins: Pins | None = None  # BOUND: the pins of the current instance
        self._pin_values: dict = {}  # BOUND: machine options and qualified workers per pinned operation
        self.problem: ProblemOut | None = None  # with assumed plates (`assume_plates`)
        self.aliases: Aliases = {}  # assumed key -> the MES keys it is published under
        self.ci: CompiledInstance | None = None
        self.ids: IdMap | None = None
        self._plan: list[Assignment] = []
        self._breaks: tuple[Break, ...] = ()
        self.rejected: list[list[Violation]] = []  # plans not published (decision 23), newest last
        self.published = 0
        self.publication: UUID | None = None  # id of the last publication in the MES
        self.last_published_at: datetime | None = None  # `_clock()` at the last publish (None: not since the start)
        self._known: set[tuple[str, str]] | None = None  # the operations of the instance the plan covers
        self._machines: dict | None = None  # machine options per operation of the last instance (a machine went down)
        self._calendar = None  # the last instance's calendar (break window, shift)
        self.mapped = False  # the last refresh mapped the plan onto real carriers after a nesting (task 7.4)

    def refresh(self) -> bool:
        """Fetch the problem and rebuild the instance; True if its set of operations changed (or it is the first).
        Orders not nested yet (planned nesting flow) get assumed plates and prints (`assumed.assume_plates`)."""
        problem, self.aliases = assume_plates(self.client.problem())
        before, old = self._known, self.problem
        self.problem = problem
        self.mapped = False
        if not problem.instance.operations:
            self.ci, self.ids, self._known, self._machines = None, None, None, None
            return before is not None
        self.ci = compile_instance(build_instance(problem, epoch=self.epoch))
        self.ids = id_map(problem, self.ci)
        changed_pins = False
        # pins and machines are compared over the operations the last instance had too: a new or removed operation
        # is the set change below. After a proposal's take-over (`restore`) the plan covers the new orders already,
        # while the last instance did not have them. Without a last instance (a resume): over all.
        ops = set(self.ci.op_keys)
        common = ops & self._machines.keys() if self._machines is not None else ops
        started = {(f.order_id, f.op_id) for f in self.snapshot().frozen}
        self.ci = out_of_service(self.ci, problem, started)
        if self.variant == BOUND:
            self.pins = pin(self.ci, problem, self.ids, started)
            self.ci = self.pins.ci
            # a new, changed or removed pin on an operation that has not started is an instance change (decision 18)
            values = {
                k: (self.ci.options[self.ci.op_index[k]], self.ci.shares[self.ci.op_index[k]]) for k in self.pins.pinned
            }
            changed_pins = before is not None and _differ(values, self._pin_values, common)
            self._pin_values = values
        self._known = set(self.ci.op_keys)
        # a machine going down (or coming back) changes the options of the operations that have not started: the plan
        # may sit on it, and a repair would keep it there, so it is a complete rescheduling as well
        machines = {
            k: tuple(self.ci.machine_ids[m] for m, _ in self.ci.options[self.ci.op_index[k]]) for k in self._known
        }
        changed_machines = self._machines is not None and _differ(machines, self._machines, common)
        self._machines = machines
        # a new break window or day start (planning settings) changes the calendar every break and shift is planned
        # in; a repair keeps the old breaks, so it is a complete rescheduling as well
        changed_calendar = self._calendar is not None and self.ci.calendar != self._calendar
        self._calendar = self.ci.calendar
        changed_ops = before != self._known
        # a nesting renames the assumed carriers' operations: the plan is mapped onto the real ones (task 7.4), the
        # step repairs it (`step`), nothing is re-optimized
        if changed_ops and old is not None and self._plan:
            mapped = map_plan(self._plan, old, problem, self.ci)
            if mapped is not None:
                self._plan = sorted(mapped, key=lambda a: self.ci.op_index[a.order_id, a.op_id])
                self.mapped, changed_ops = True, False
        return changed_ops or changed_pins or changed_machines or changed_calendar

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
                variant=self.variant,
                snapshot_as_of=self.problem.as_of,
                solved_at=max(self._clock(), self.problem.as_of),  # the MES clock may run ahead of ours
                steps=steps(
                    self.problem, self.ci, self.ids, Plan(list(plan), new_breaks), self.epoch, aliases=self.aliases
                ),
                breaks=schedule_breaks(self.problem, Plan(list(plan), new_breaks), self.epoch),
            )
        )
        # in operation order, as the DES returns its plan: adapt_plan compares plans position by position
        self._plan = sorted(plan, key=lambda x: self.ci.op_index[x.order_id, x.op_id])
        self._breaks = new_breaks
        self.published += 1
        self.publication = out.id
        self.last_published_at = self._clock()

    def keep_alive(self, stale_minutes: int) -> bool:
        """Republish the current plan unchanged if the last publication is older than half the MES's stale threshold
        (`scheduler_stale_minutes`), so a quiet stretch does not mark a healthy scheduler offline. After `restore()`
        nothing was published yet, so the first call republishes. True if it published."""
        if not self._plan or self.ci is None or self.problem is None:
            return False
        last = self.last_published_at
        if last is not None and self._clock() - last < timedelta(minutes=stale_minutes / 2):
            return False
        before = self.published
        self.update_plan(self.current_plan(), self.current_breaks())
        return self.published > before


def _repair_mapped(factory: MesFactory, decisions: list[dict]) -> Anchor | None:
    """Task 7.4: the plan mapped onto the real carriers, re-timed with its machines, workers and order (`retime`; no
    replan, whatever the shifts: the planner's *Update plan* re-optimizes); the new anchor. None if the result does
    not pass the checker."""
    ci = factory.ci
    assert ci is not None
    snap = factory.snapshot()
    try:
        repaired, repaired_breaks = retime(ci, snap, factory.current_plan())
    except (PlanNotExecutable, KeyError, ValueError) as e:  # the mapping left the plan unexecutable
        factory.rejected.append([Violation(constraint="mapping", ops=(), message=str(e))])
        return None
    before = len(factory.rejected)
    factory.update_plan(repaired, repaired_breaks)
    if len(factory.rejected) > before:
        return None
    decisions.append({"t": snap.t, "type": "MAP", "operations": len(repaired)})
    return Anchor(list(repaired), snap.t, tuple(repaired_breaks))


def _differ(new: dict, old: dict, keys) -> bool:
    """A value differs on one of `keys` (missing counts as a value: a pin set or cleared)."""
    return any(new.get(k) != old.get(k) for k in keys)


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
    if factory.mapped and not changed:
        mapped = _repair_mapped(factory, decisions)
        if mapped is not None:
            return mapped
        changed = True  # the mapped plan does not pass the checker: plan the instance anew
    try:
        return adapt_plan(factory.ci, factory, policy, decisions, anchor, arrived=changed)
    except PlanNotExecutable as e:
        factory.rejected.append([Violation(constraint="planner", ops=(), message=str(e))])
        return anchor
