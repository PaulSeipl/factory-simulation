"""The planning tool against the `Factory` protocol (math/05, section 5): the DES is one factory; `adapt_plan` needs
nothing else from it."""

from collections.abc import Sequence
from pathlib import Path

from simulation.control.rescheduling import Anchor, Factory, ReschedulingPolicy, adapt_plan, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break, Plan
from simulation.planners.dispatching import dispatch, ect, spt
from simulation.sim.des import Simulation
from simulation.sim.snapshot import Snapshot

TOY = compile_instance(read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-dag-3x4.json", Instance))


class Recorder:
    """A factory that is not the DES: it forwards to one and records every plan it is sent."""

    def __init__(self, sim: Simulation):
        self._sim, self.sent = sim, []

    def snapshot(self) -> Snapshot:
        return self._sim.snapshot()

    def current_plan(self) -> Sequence[Assignment]:
        return self._sim.current_plan()

    def current_breaks(self) -> Sequence[Break]:
        return self._sim.current_breaks()

    def update_plan(self, plan: Sequence[Assignment], breaks: Sequence[Break] | None = None) -> None:
        self.sent.append(list(plan))
        self._sim.update_plan(plan, breaks)


def _started(plan):
    sim = Simulation(TOY, plan)
    sim.process_events()
    return sim


def test_the_des_is_a_factory():
    assert isinstance(Simulation(TOY, dispatch(TOY, spt, ect)), Factory)
    assert isinstance(Recorder(Simulation(TOY, dispatch(TOY, spt, ect))), Factory)


def test_without_disturbance_another_factory_is_sent_nothing():
    plan = dispatch(TOY, spt, ect)
    factory = Recorder(_started(plan))
    anchor = Anchor(plan, 0)
    assert adapt_plan(TOY, factory, ReschedulingPolicy(), [], anchor) is anchor
    assert factory.sent == []


def test_a_changed_instance_is_rescheduled_completely_through_the_protocol():
    plan = dispatch(TOY, spt, ect)
    calls = []

    def planner(ci, snap, current):
        calls.append(snap.t)
        return Plan(dispatch(ci, spt, ect, snapshot=snap), ())

    factory = Recorder(_started(plan))
    decisions: list[dict] = []
    anchor = adapt_plan(TOY, factory, ReschedulingPolicy(planner=planner), decisions, Anchor(plan, 0), arrived=True)
    assert calls == [0] and len(factory.sent) == 1 and anchor.plan == factory.sent[0]
    assert decisions[-1]["type"] == "REPLAN" and decisions[-1]["accepted"]


def test_zero_disturbance_the_realized_schedule_is_the_plan():
    """The zero-disturbance test with the typed tool: repair only, no events, realized = plan."""
    plan = dispatch(TOY, spt, ect)
    result = execute(TOY, plan, policy=ReschedulingPolicy())
    key = lambda a: (a.order_id, a.op_id)  # noqa: E731
    assert [(a.start, a.end, a.machine) for a in sorted(result.schedule, key=key)] == [
        (a.start, a.end, a.machine) for a in sorted(plan, key=key)
    ]
