"""The sample-mean objective over the planner's own scenarios (math/14 section 4a). Small instances only."""

from pathlib import Path

import pytest
from test_rescheduling import PLAN, TOY, TOY_INSTANCE, disturbed

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import MAKESPAN, expected
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.planners.ga import GaParams, rule_plans, solve_ga
from simulation.sim.scenario import Scenario, sample_scenario


def test_zero_disturbance_gives_the_planned_value():
    assert expected(MAKESPAN, [disturbed()]).evaluate(TOY, PLAN) == MAKESPAN.evaluate(TOY, PLAN) == 11


def test_mean_by_hand():
    # a3 4x (2 -> 8): a3 [6, 14) on M4, b4 waits for it on M4 and ends at 16; mean of 11 and 16 is 13.5 -> 14
    slow = disturbed({"a3": 4.0})
    assert expected(MAKESPAN, [slow]).evaluate(TOY, PLAN) == 16
    assert expected(MAKESPAN, [disturbed(), slow]).evaluate(TOY, PLAN) == 14


def test_no_scenario_rejected():
    with pytest.raises(ValueError, match="at least one scenario"):
        expected(MAKESPAN, [])


def test_no_cpsat_model():
    with pytest.raises(NotImplementedError):
        expected(MAKESPAN, [disturbed()]).cpsat()


def test_ga_on_the_expected_makespan_is_not_worse_than_any_rule():
    own = [sample_scenario(TOY_INSTANCE, 0.3, seed) for seed in range(1000, 1010)]  # planner's seeds, not the DES's
    objective = expected(MAKESPAN, own)
    result = solve_ga(TOY, objective, GaParams(population=20, generations=10, time_limit=None))
    assert check_schedule(TOY, result.plan.assignments, breaks=result.plan.breaks) == []
    assert result.value == objective.evaluate(TOY, result.plan.assignments, result.plan.breaks)
    assert result.value <= min(objective.evaluate(TOY, p.assignments, p.breaks) for p in rule_plans(TOY))


def test_zero_disturbance_with_workers_and_breaks():
    example = Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-workers.json"
    ci = compile_instance(generate_carrier_instance(read_model(example, CarrierGeneratorParams)))
    plan = dispatch_plan(ci, spt)
    neutral = Scenario(instance=ci.name, seed=0, sigma=0, factors=[
        {"order_id": k, "op_id": j, "factor": 1.0, "start_offset": 0} for k, j in ci.op_keys])
    assert expected(MAKESPAN, [neutral]).evaluate(ci, plan.assignments, plan.breaks) == \
        MAKESPAN.evaluate(ci, plan.assignments, plan.breaks)
