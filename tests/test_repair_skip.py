"""The planning tool skips the shift repair when the factory ran as planned (math/05 section 5): every run equals the
run that always repairs. Small instances only."""

from pathlib import Path

import pytest

import simulation.control.rescheduling as rescheduling
from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan, dispatch_planner
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"
POLICIES = {
    "repair": ReschedulingPolicy(),
    "rule": ReschedulingPolicy(planner=dispatch_planner(SEQUENCING_RULES["edd"]), max_makespan_change=2, period=60),
}


def instance(name: str) -> Instance:
    if name.startswith("toy"):
        return read_model(DATA / "instances" / name, Instance)
    return generate_carrier_instance(read_model(DATA / "generator" / name, CarrierGeneratorParams))


def run(ci, inst, plan, seed, policy):
    res = execute(ci, plan.assignments, sample_scenario(inst, 0.45, seed, q=0.5, max_early=5, max_late=5), policy,
                  plan.breaks)
    # planner_time is wall clock, the only field that may differ between two equal runs
    return res.schedule, [{k: v for k, v in d.items() if k != "planner_time"} for d in res.decisions], res.breaks


@pytest.mark.parametrize(("name", "seeds"), [("toy-dag-3x4.json", range(6)), ("toy-carriers.json", range(6)),
                                             ("toy-workers.json", range(6)), ("dental-carriers-workers.json", [2])])
@pytest.mark.parametrize("policy", POLICIES)
def test_skipping_the_repair_changes_nothing(name, seeds, policy, monkeypatch):
    inst = instance(name)
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"])
    fast = [run(ci, inst, plan, s, POLICIES[policy]) for s in seeds]
    monkeypatch.setattr(rescheduling, "_unaffected", lambda *_args: False)  # always repair
    assert [run(ci, inst, plan, s, POLICIES[policy]) for s in seeds] == fast


def test_a_late_operation_is_affected():
    inst = instance("toy-dag-3x4.json")
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"])
    sim = rescheduling.Simulation(ci, plan.assignments, sample_scenario(inst, 0.0, 0))
    sim.run(until=3)
    assert rescheduling._unaffected(ci, sim.snapshot(), sim.current_plan(), sim.current_breaks())
    slow = sample_scenario(inst, 0.0, 0).model_copy()
    factors = [f.model_copy(update={"factor": 3.0}) if f.op_id == "a1" else f for f in slow.factors]
    sim = rescheduling.Simulation(ci, plan.assignments, slow.model_copy(update={"factors": tuple(factors)}))
    sim.run(until=3)  # a1 planned [0, 3) still runs: its expected end 4 differs from the plan
    assert not rescheduling._unaffected(ci, sim.snapshot(), sim.current_plan(), sim.current_breaks())
