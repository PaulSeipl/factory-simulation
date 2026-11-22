"""The candidate hook `choose` of dispatch_plan (math/11 §5): the decision of an iteration from outside."""

import random
from pathlib import Path

import pytest

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch_plan
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"
TOYS = {name: compile_instance(read_model(DATA / "instances" / f"{name}.json", Instance))
        for name in ("toy-dag-3x4", "toy-carriers", "toy-workers")}
DENTAL = generate_carrier_instance(read_model(DATA / "generator" / "dental-carriers-workers.json",
                                              CarrierGeneratorParams))
INSTANCES = TOYS | {"dental-carriers-workers": compile_instance(DENTAL)}
RULES = [(s, a) for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None]]


def ranking_like(ci, sequencing):
    """A chooser that ranks the eligible candidates as dispatch_plan does without one."""
    def choose(eligible, state):
        return min(range(len(eligible)), key=lambda i: (
            *sequencing(ci, state, *eligible[i][1:]), eligible[i][1], eligible[i][2] is None, eligible[i][2] or 0))
    return choose


@pytest.mark.parametrize("name", list(INSTANCES))
@pytest.mark.parametrize(("s", "a"), RULES, ids=lambda r: str(r))
def test_a_chooser_that_ranks_like_the_rule_gives_the_rule_plan(name, s, a):
    ci, seq, assign = INSTANCES[name], SEQUENCING_RULES[s], ASSIGNMENT_RULES.get(a)
    assert dispatch_plan(ci, seq, assign, choose=ranking_like(ci, seq)) == dispatch_plan(ci, seq, assign)


@pytest.mark.parametrize("name", list(INSTANCES))
@pytest.mark.parametrize("seed", [0, 1])
def test_any_choice_gives_a_feasible_plan(name, seed):
    ci, rng = INSTANCES[name], random.Random(seed)
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"], choose=lambda eligible, _state: rng.randrange(len(eligible)))
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []


def test_the_chooser_decides():
    # guards against a hook that is called but ignored: a random choice changes the dental plan
    ci, rng = INSTANCES["dental-carriers-workers"], random.Random(0)
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"], choose=lambda eligible, _state: rng.randrange(len(eligible)))
    assert plan.assignments != dispatch_plan(ci, SEQUENCING_RULES["spt"]).assignments


def test_any_choice_from_a_snapshot_keeps_the_frozen_part():
    ci = INSTANCES["dental-carriers-workers"]
    start = dispatch_plan(ci, SEQUENCING_RULES["spt"], ASSIGNMENT_RULES["ect"])
    sim = Simulation(ci, start.assignments, sample_scenario(DENTAL, 0.3, 1), start.breaks)
    sim.run(until=600)
    snap, rng = sim.snapshot(), random.Random(0)
    assert snap.frozen
    plan = dispatch_plan(ci, SEQUENCING_RULES["spt"], snapshot=snap,
                         choose=lambda eligible, _state: rng.randrange(len(eligible)))
    assert check_schedule(ci, plan.assignments, snap, plan.breaks) == []
