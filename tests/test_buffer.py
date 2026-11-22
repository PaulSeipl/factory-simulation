"""Time-buffer baseline (math/14 section 4b): inflate, plan, shorten. Small instances only."""

import math
from pathlib import Path

import pytest
from test_rescheduling import PLAN, TOY

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.buffer import inflate, quantile_factor, shorten
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.sim.des import replay

DATA = Path(__file__).parents[1] / "data"


def compiled(name: str):
    if name.startswith("toy"):
        return compile_instance(read_model(DATA / "instances" / name, Instance))
    return compile_instance(generate_carrier_instance(read_model(DATA / "generator" / name, CarrierGeneratorParams)))


def test_quantile_factor():
    assert quantile_factor(0.0, 0.8) == 1.0
    assert quantile_factor(0.45, 0.8) == pytest.approx(math.exp(-0.45**2 / 2 + 0.841621 * 0.45), abs=1e-5)  # 1.320
    with pytest.raises(ValueError, match="outside"):
        quantile_factor(0.45, 1.0)


def test_inflate_by_hand():
    big = inflate(TOY, 1.5)
    a1, a3 = TOY.op_index["A", "a1"], TOY.op_index["A", "a3"]
    m = TOY.machine_index
    assert dict(big.options[a1]) == {m["M1"]: 5, m["M2"]: 8}  # 3 * 1.5 = 4.5 -> 5 (half up), 5 * 1.5 = 7.5 -> 8
    assert dict(big.options[a3]) == {m["M4"]: 3}
    assert inflate(TOY, 1.0).options == TOY.options


def test_inflate_keeps_fixed_programs():
    ci = compiled("dental-carriers-example.json")  # its oven is a p-batch step
    big = inflate(ci, 2.0)
    fixed = [o for o in range(ci.n_ops) if ci.batch_capacity[o] > 1]
    assert fixed and all(big.options[o] == ci.options[o] for o in fixed)


def test_factor_below_one_rejected():
    with pytest.raises(ValueError, match="below 1"):
        inflate(TOY, 0.9)


@pytest.mark.parametrize("name", ["toy-dag-3x4.json", "toy-carriers.json", "toy-workers.json",
                                  "dental-carriers-example.json", "dental-carriers-workers.json"])
def test_shortened_rule_plans_are_feasible_and_replay_unchanged(name):
    ci = compiled(name)
    big = inflate(ci, 1.3)
    for rule in SEQUENCING_RULES.values():
        plan = dispatch_plan(big, rule)
        short = shorten(ci, plan.assignments, plan.breaks)  # raises if infeasible on ci
        by = {(a.order_id, a.op_id): a for a in plan.assignments}
        assert all(a.start == by[a.order_id, a.op_id].start for a in short)
        times = lambda xs: {(x.order_id, x.op_id, x.machine, x.start, x.end, x.workers) for x in xs}  # noqa: E731
        assert times(replay(ci, short, None, plan.breaks).schedule) == times(short)  # zero disturbance: gaps kept


def test_infeasible_shortened_plan_rejected():
    # b1 moved onto M1 at 0 overlaps a1 [0, 3) there, also with nominal durations
    clash = [a.model_copy(update={"start": 0, "end": 2}) if a.op_id == "b1" else a for a in PLAN]
    with pytest.raises(ValueError, match="infeasible"):
        shorten(TOY, clash)
