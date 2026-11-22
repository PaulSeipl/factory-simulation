"""The candidate hook `choose` of dispatch_plan (math/11 §5): the decision of an iteration from outside."""

import random
from pathlib import Path

import pytest

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.dispatching import (
    ASSIGNMENT_RULES,
    SEQUENCING_RULES,
    Checkpoint,
    dispatch_plan,
    dispatch_until,
)
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


# --- pause and resume (dispatch_until, Checkpoint) ------------------------------------------------------------------


def seeded_chooser(seed):
    """Random choices that depend only on the seed and the decision's candidates, so a resumed run chooses as the
    uninterrupted one."""
    def choose(eligible, _state):
        return random.Random(f"{seed}/{eligible}").randrange(len(eligible))
    return choose


@pytest.mark.parametrize("name", list(INSTANCES))
def test_resuming_at_any_decision_gives_the_uninterrupted_plan(name):
    ci, seq = INSTANCES[name], SEQUENCING_RULES["spt"]
    choose = seeded_chooser(0)
    whole = dispatch_plan(ci, seq, choose=choose)
    k, checked = 0, 0
    while isinstance(cp := dispatch_until(ci, seq, None, None, choose, k), Checkpoint):
        assert dispatch_plan(ci, seq, choose=choose, resume=cp) == whole
        assert dispatch_plan(ci, seq, choose=choose, resume=cp) == whole  # the checkpoint is not used up
        k, checked = k + 1 + k // 3, checked + 1  # every decision on the toys, a spread on dental
    assert checked >= 1 and cp == whole


def test_checkpoints_chain_from_a_snapshot_with_ga_keys():
    # pause, resume to the next pause, ...: each step continues from the last checkpoint, with delay, overtime and
    # join keys as the GA's decoder passes them and from a snapshot of a disturbed run
    ci = INSTANCES["dental-carriers-workers"]
    rng = random.Random(1)
    start = dispatch_plan(ci, SEQUENCING_RULES["spt"], ASSIGNMENT_RULES["ect"])
    sim = Simulation(ci, start.assignments, sample_scenario(DENTAL, 0.3, 1), start.breaks)
    sim.run(until=600)
    snap = sim.snapshot()
    seq, delay = SEQUENCING_RULES["mwkr"], [rng.randrange(0, 30) for _ in range(ci.n_ops)]
    overtime = [rng.randrange(0, ci.calendar.max_overtime + 1) for _ in range(ci.n_ops)]
    join = [rng.random() < 0.5 for _ in range(ci.n_ops)]
    choose = seeded_chooser(2)
    whole = dispatch_plan(ci, seq, None, snap, delay, overtime, join, choose)
    assert check_schedule(ci, whole.assignments, snap, whole.breaks) == []
    cp, steps = None, 0
    while isinstance(cp := dispatch_until(ci, seq, None, snap, choose, 25, cp, delay, overtime, join), Checkpoint):
        steps += 1
    assert steps >= 3 and cp == whole


def test_resume_with_other_arguments_rejected():
    ci, seq = INSTANCES["toy-dag-3x4"], SEQUENCING_RULES["spt"]
    cp = dispatch_until(ci, seq, None, None, seeded_chooser(0), 1)
    assert isinstance(cp, Checkpoint)
    with pytest.raises(ValueError, match="arguments its checkpoint"):
        dispatch_plan(ci, SEQUENCING_RULES["fifo"], choose=seeded_chooser(0), resume=cp)
