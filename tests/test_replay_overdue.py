"""replay drops the OVERDUE events (math/13 section 5): the realized schedule, breaks and log stay the same as with
them, since OVERDUE only gives a planning tool time points. Small instances only."""

import random
from pathlib import Path

import pytest

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.planners.ga import N_KEYS, decode
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"


def instance(name: str) -> Instance:
    if name.startswith("toy"):
        return read_model(DATA / "instances" / name, Instance)
    return generate_carrier_instance(read_model(DATA / "generator" / name, CarrierGeneratorParams))


@pytest.mark.parametrize("name", ["toy-dag-3x4.json", "toy-carriers.json", "toy-workers.json",
                                  "dental-carriers-example.json", "dental-carriers-workers.json"])
def test_replay_without_overdue_equals_the_full_run(name):
    inst = instance(name)
    ci = compile_instance(inst)
    genes = [random.Random(7).random() for _ in range(N_KEYS * ci.n_ops)]
    for plan in (dispatch_plan(ci, spt), decode(ci, genes, 100)):
        for seed in range(4):
            scenario = sample_scenario(inst, 0.45, seed, q=0.5, max_early=5, max_late=5)
            full = Simulation(ci, plan.assignments, scenario, plan.breaks)
            full.run()
            fast = replay(ci, plan.assignments, scenario, plan.breaks)
            assert fast.schedule == full.realized()
            assert fast.breaks == full.realized_breaks()
            assert fast.log == full.log


def test_a_start_enables_a_swap_in_the_same_minute():
    # dental workers, spt plan, seed 2: at 612 D starts a removal, so D is busy for O37's design (planned for D);
    # C is free with room, so C takes it at 612 (before the repeated start step: at the next time point, 613)
    inst = instance("dental-carriers-workers.json")
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, spt)
    run = replay(ci, plan.assignments, sample_scenario(inst, 0.45, 2, q=0.5, max_early=5, max_late=5), plan.breaks)
    design = next(a for a in run.schedule if (a.order_id, a.op_id) == ("O37", "design"))
    assert (design.start, design.workers) == (612, ("C",))
