"""The DES reuses the snapshot entries of finished operations (math/13 section 6): at every time point the snapshot
equals a freshly built one, also after plan updates. Small instances only."""

from pathlib import Path

import pytest

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.planners.repair import repair_plan
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import snapshot

DATA = Path(__file__).parents[1] / "data"


@pytest.mark.parametrize("name", ["toy-workers.json", "dental-carriers-workers.json"])
def test_reused_entries_equal_a_fresh_snapshot(name):
    inst = (read_model(DATA / "instances" / name, Instance) if name.startswith("toy")
            else generate_carrier_instance(read_model(DATA / "generator" / name, CarrierGeneratorParams)))
    ci = compile_instance(inst)
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"])
    sim = Simulation(ci, plan.assignments, sample_scenario(inst, 0.45, 2, q=0.5, max_early=5, max_late=5), plan.breaks)
    checked = reused = 0
    while not sim.done:
        sim.process_events()
        sim.start_operations()
        snap = sim.snapshot()
        assert snap == snapshot(ci, sim.current_plan(), sim.state, sim.breaks, sim.share_len)  # no cache
        checked, reused = checked + 1, max(reused, len(sim._finished))
        if checked % 5 == 0:  # plan updates too: the repaired plan
            new, breaks = repair_plan(ci, snap, sim.current_plan(), sim.current_breaks())
            sim.update_plan(new, breaks)
    assert checked > 10 and reused > 2  # the cache was used
