"""Monte Carlo tree search over the dispatcher's decisions (src/simulation/planners/mcts.py, math/15_mcts.md)."""

from pathlib import Path

import pytest
from test_rescheduling import PLAN, TOY, disturbed, of_type

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import dispatch_plan, ect, spt
from simulation.planners.ga import decode, encode, rule_plans
from simulation.planners.mcts import MctsParams, mcts_planner, solve_mcts
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"
FAST = MctsParams(iterations=5, width=3)


def toy(name: str):
    return compile_instance(read_model(DATA / "instances" / f"{name}.json", Instance))


DENTAL = generate_carrier_instance(read_model(DATA / "generator" / "dental-carriers-example.json",
                                              CarrierGeneratorParams))  # no workers: 7 ms per rollout
INSTANCES = {name: (lambda name=name: toy(name)) for name in ("toy-3x3", "toy-dag-3x4", "toy-carriers", "toy-workers")}
INSTANCES["dental-example"] = lambda: compile_instance(DENTAL)


def best_rule(ci) -> int:
    return min(MAKESPAN.evaluate(ci, p.assignments, p.breaks) for p in rule_plans(ci))


def replay_choices(ci, prefix):
    """The joint SPT plan with the decisions (iterations with more than one candidate) fixed by `prefix`, the later
    ones taken as the first candidate; and the number of candidates of the first decision after the prefix (0: none)."""
    k, free = 0, 0

    def choose(eligible, _state):
        nonlocal k, free
        if len(eligible) == 1:
            return 0
        k += 1
        if k <= len(prefix):
            return prefix[k - 1]
        free = free or len(eligible)
        return 0

    return dispatch_plan(ci, spt, choose=choose), free


def all_non_delay_plans(ci):
    """Every plan the joint dispatcher can build: depth-first over the decisions."""
    stack = [[]]
    while stack:
        prefix = stack.pop()
        plan, free = replay_choices(ci, prefix)
        yield plan
        stack.extend(prefix + [i] for i in range(free))


@pytest.mark.parametrize("name", list(INSTANCES))
def test_plan_is_feasible_and_not_worse_than_any_rule(name):
    ci = INSTANCES[name]()
    result = solve_mcts(ci, MAKESPAN, FAST)
    assert check_schedule(ci, result.plan.assignments, breaks=result.plan.breaks) == []
    assert result.value == MAKESPAN.evaluate(ci, result.plan.assignments) <= best_rule(ci)
    assert not result.wall_limited and result.decisions >= 1


def test_every_rule_misses_the_optimum_the_search_finds():
    # toy-dag-3x4: all 15 rule plans end at 12; the best of the 108 non-delay plans ends at 11, which CP-SAT proves
    # optimal, so the optimum is reachable by the tree; with UCB1's beta the search finds it in 100 iterations
    ci = toy("toy-dag-3x4")
    plans = list(all_non_delay_plans(ci))
    assert len(plans) == 108
    assert best_rule(ci) == 12
    assert min(MAKESPAN.evaluate(ci, p.assignments) for p in plans) == 11
    cp = solve(ci, MAKESPAN, time_limit=10, workers=1)
    assert cp.status == "OPTIMAL" and cp.objective == 11
    assert solve_mcts(ci, MAKESPAN, MctsParams(iterations=100)).value == 11
    assert solve_mcts(ci, MAKESPAN, MctsParams(iterations=100, exploration=0.5)).value == 12  # too greedy


def test_beats_the_rules_on_dental_example():
    ci = compile_instance(DENTAL)
    assert solve_mcts(ci, MAKESPAN, MctsParams(iterations=3)).value < best_rule(ci)


def test_same_params_same_plan():
    ci = toy("toy-dag-3x4")
    a, b = (solve_mcts(ci, MAKESPAN, MctsParams(iterations=20)) for _ in range(2))
    assert a == b


def test_first_iteration_finishes_like_the_rollout_rule():
    # one iteration per decision expands the rollout rule's own choice everywhere: its plan, nothing better
    ci = toy("toy-3x3")
    result = solve_mcts(ci, MAKESPAN, MctsParams(iterations=1))
    assert result.value == best_rule(ci)


def test_time_limit_stops_the_search():
    ci = compile_instance(DENTAL)
    result = solve_mcts(ci, MAKESPAN, MctsParams(iterations=1000, time_limit=0.5))
    assert result.wall_limited and result.value <= best_rule(ci)


def test_from_a_snapshot_keeps_the_frozen_part():
    ci = compile_instance(DENTAL)
    start = dispatch_plan(ci, spt, ect)
    sim = Simulation(ci, start.assignments, sample_scenario(DENTAL, 0.3, 1), start.breaks)
    sim.run(until=600)
    snap = sim.snapshot()
    assert snap.frozen
    result = solve_mcts(ci, MAKESPAN, MctsParams(iterations=2), snap, sim.current_plan())
    assert check_schedule(ci, result.plan.assignments, snap, result.plan.breaks) == []


def test_warm_start_is_the_first_incumbent():
    ci = toy("toy-3x3")
    current = dispatch_plan(ci, spt, ect).assignments
    result = solve_mcts(ci, MAKESPAN, FAST, current=current)
    warm = decode(ci, encode(ci, current), 0)
    assert result.value <= MAKESPAN.evaluate(ci, warm.assignments)
    # the warm start is one more evaluation; the tree does not depend on the incumbent
    assert result.evaluations == solve_mcts(ci, MAKESPAN, FAST).evaluations + 1


@pytest.mark.parametrize("name", list(INSTANCES))
def test_zero_disturbance_replays_the_mcts_plan(name):
    # Definition of Done: without disturbances the DES realizes the plan exactly
    ci = INSTANCES[name]()
    plan = solve_mcts(ci, MAKESPAN, FAST).plan
    realized = replay(ci, plan.assignments, breaks=plan.breaks).schedule

    def rows(schedule):  # the DES also records realized share lengths, which a plan leaves out
        return sorted((a.order_id, a.op_id, a.machine, a.start, a.end, a.workers, a.batch) for a in schedule)

    assert rows(realized) == rows(plan.assignments)


def test_reschedules_from_snapshots_in_the_des():
    # b1 takes twice as long: every complete rescheduling searches from the snapshot; the rescheduling checks each
    # plan against the snapshot and raises if it is infeasible
    policy = ReschedulingPolicy(mcts_planner(params=FAST), max_makespan_change=0)
    replans = of_type(execute(TOY, PLAN, disturbed({"b1": 2.0}), policy), "REPLAN")
    assert replans and all(d["accepted"] for d in replans)
    assert all(not d["planner"]["wall_limited"] for d in replans)


def test_change_budget_zero_keeps_every_machine():
    # as for the GA (test_ga): b1 takes three times as long; with budget 0 the warm start keeps every machine and
    # plans over the budget rank behind it
    policy = ReschedulingPolicy(mcts_planner(params=FAST, change_budget=0), max_makespan_change=0, change_budget=0)
    replans = of_type(execute(TOY, PLAN, disturbed({"b1": 3.0}), policy), "REPLAN")
    assert replans and [(d["accepted"], d["changed_assignments"]) for d in replans] == [(True, 0)] * len(replans)
    assert all(d["planner"]["over_budget"] == 0 for d in replans)


@pytest.mark.parametrize(("params", "message"), [
    ({"iterations": 0}, "iterations"), ({"width": 0}, "width"), ({"exploration": -0.1}, "exploration"),
    ({"time_limit": 0}, "time_limit"),
])
def test_invalid_params_rejected(params, message):
    with pytest.raises(ValueError, match=message):
        MctsParams(**params)
