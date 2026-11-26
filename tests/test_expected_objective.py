"""The sample-mean objective over the planner's own scenarios, static and from a snapshot (math/14 section 4a).
Small instances only."""

from pathlib import Path

import pytest
from test_rescheduling import PLAN, TOY, TOY_INSTANCE, disturbed

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import MAKESPAN, expected, planner_scenarios, replay_from
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.planners.ga import GaParams, ga_planner, rule_plans, solve_ga
from simulation.planners.repair import repair
from simulation.sim.des import PlanNotExecutable, Simulation
from simulation.sim.scenario import Scenario, sample_planner_scenario, sample_scenario


def times(schedule):
    return {(a.order_id, a.op_id): (a.start, a.end) for a in schedule}


def test_zero_disturbance_gives_the_planned_value():
    assert expected(MAKESPAN, lambda _ci: [disturbed()]).evaluate(TOY, PLAN) == MAKESPAN.evaluate(TOY, PLAN) == 11


def test_mean_by_hand():
    # a3 4x (2 -> 8): a3 [6, 14) on M4, b4 waits for it on M4 and ends at 16; mean of 11 and 16 is 13.5 -> 14
    slow = disturbed({"a3": 4.0})
    assert expected(MAKESPAN, lambda _ci: [slow]).evaluate(TOY, PLAN) == 16
    assert expected(MAKESPAN, lambda _ci: [disturbed(), slow]).evaluate(TOY, PLAN) == 14


def test_no_scenario_rejected():
    with pytest.raises(ValueError, match="at least one scenario"):
        expected(MAKESPAN, lambda _ci: []).evaluate(TOY, PLAN)


def test_no_cpsat_model():
    with pytest.raises(NotImplementedError):
        expected(MAKESPAN, lambda _ci: [disturbed()]).cpsat()


def test_planner_scenarios_are_the_keyed_draws():
    own = planner_scenarios(0.3, [1000, 1001])(TOY)
    keyed = sample_scenario(TOY_INSTANCE, 0.3, 1000, keyed=True)
    assert [f.factor for f in own[0].factors] == [f.factor for f in keyed.factors]
    assert own[0].factors != own[1].factors
    assert sample_planner_scenario(TOY, 0.0, 5).factors[0].factor == 1.0


def test_ga_on_the_expected_makespan_is_not_worse_than_any_rule():
    objective = expected(MAKESPAN, planner_scenarios(0.3, range(1000, 1010)))  # planner's seeds, not the DES's
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
    assert expected(MAKESPAN, lambda _ci: [neutral]).evaluate(ci, plan.assignments, plan.breaks) == \
        MAKESPAN.evaluate(ci, plan.assignments, plan.breaks)


def snapshot_at_5():
    # b1 planned [3, 5) on M1 takes 4 (factor 2): at 5 a1 is finished [0, 3), a2 runs [3, 6), b1 runs, expected end 6
    sim = Simulation(TOY, PLAN, disturbed({"b1": 2.0}))
    sim.run(until=5)
    snap = sim.snapshot()
    return snap, repair(TOY, snap, PLAN)


def test_replay_from_a_snapshot_keeps_the_frozen_part_and_the_plan():
    snap, plan = snapshot_at_5()
    frozen = {(f.order_id, f.op_id): (f.start, f.end) for f in snap.frozen}
    assert frozen[("B", "b1")] == (3, 6)
    realized = times(replay_from(TOY, snap, plan, disturbed()).schedule)
    assert realized == times(plan)  # zero disturbance from the snapshot: the repaired plan
    assert expected(MAKESPAN, lambda _ci: [disturbed()]).with_snapshot(snap).evaluate(TOY, plan) == \
        MAKESPAN.evaluate(TOY, plan)


def test_a_running_operation_ends_at_its_own_draw_not_before_t_plus_one():
    snap, plan = snapshot_at_5()
    # planner's draw 3: b1 lasts 2 * 3 = 6 from 3, ends at 9; draw 0.5: 1 minute, but it runs at 5, so it ends at 6
    assert times(replay_from(TOY, snap, plan, disturbed({"b1": 3.0})).schedule)["B", "b1"] == (3, 9)
    assert times(replay_from(TOY, snap, plan, disturbed({"b1": 0.5})).schedule)["B", "b1"] == (3, 6)


def test_a_plan_that_ignores_the_snapshot_is_rejected():
    snap, _ = snapshot_at_5()
    with pytest.raises(PlanNotExecutable):
        replay_from(TOY, snap, PLAN, disturbed())  # PLAN still has b1 ending at 5


def test_ga_planner_on_the_expected_makespan_in_the_des():
    planner = ga_planner(expected(MAKESPAN, planner_scenarios(0.3, range(1000, 1005))),
                         GaParams(population=12, generations=3, time_limit=None))
    result = execute(TOY, PLAN, disturbed({"b1": 2.0, "a3": 3.0}), ReschedulingPolicy(planner=planner, period=2))
    assert any(d["type"] == "REPLAN" for d in result.decisions)
    assert len(result.schedule) == TOY.n_ops  # every operation ran; each accepted plan passed the snapshot check
