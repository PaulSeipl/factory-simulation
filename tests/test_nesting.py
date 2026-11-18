"""Nesting during the run (math/33 step B3): release at the nesting times inside `execute`.

Zero-change test of the feature: without a norm every accepted order is bound at the next nesting time, which is the
static arrival rule, so the run with nesting inside `execute` must equal the run on the hindsight instance with
arrivals (same realized schedule, same decisions), both with keyed disturbances.
"""

from pathlib import Path

import pytest

from simulation.arrival_generator import ArrivalParams, generate_arrival_instance
from simulation.carrier_generator import CarrierGeneratorParams
from simulation.control.nesting import Nesting, average_daily_capacity, default_order_load
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance, compile_visible
from simulation.model.instance import Calendar
from simulation.planners.dispatching import dispatch_plan, dispatch_planner, ect, spt
from simulation.sim.scenario import sample_scenario

ROOT = Path(__file__).parents[1]
# the small dental example, not the Fidentis case (user 2026-11-18: that one only in experiments and notebooks)
BASE = read_model(ROOT / "data" / "generator" / "dental-carriers-workers.json", CarrierGeneratorParams).model_copy(
    update={"release_range": (0, 0), "due_date_tightness": ()})
MILLS = ("mill1", "mill2", "mill3")
DISTURBED = {"sigma": 0.2, "q": 0.5, "max_early": 5, "max_late": 5}


def params(**changes) -> ArrivalParams:
    return ArrivalParams(**{"seed": 1, "base": BASE, "rates": dict.fromkeys(range(5), 3.0), "window_days": 3,
                            "backlog": 1, "backlog_earliest_cutoff": 5, "due_working_days": 10} | changes)


def plain(schedule):
    return sorted((a.order_id, a.op_id, a.machine, a.start, a.end, a.workers) for a in schedule)


def scenario_for(seed):
    return lambda inst: sample_scenario(inst, seed=seed, keyed=True, **DISTURBED)


def run_static(p: ArrivalParams):
    inst = generate_arrival_instance(p)
    ci, at = compile_instance(inst), compile_visible(inst)
    start = dispatch_plan(at(0), spt, ect)
    return inst, execute(ci, start.assignments, scenario_for(p.seed)(inst),
                         ReschedulingPolicy(planner=dispatch_planner(spt, ect)), start.breaks, visible=at)


def run_nesting(p: ArrivalParams):
    nesting = Nesting(p)
    inst0 = nesting.instance()
    ci0 = compile_instance(inst0)
    start = dispatch_plan(ci0, spt, ect)
    result = execute(ci0, start.assignments, scenario_for(p.seed)(inst0),
                     ReschedulingPolicy(planner=dispatch_planner(spt, ect)), start.breaks, nesting=nesting,
                     scenario_for=scenario_for(p.seed))
    return nesting, result


@pytest.mark.parametrize("seed", [1, 2])
def test_binding_all_during_the_run_equals_the_static_arrivals(seed):
    p = params(seed=seed)
    inst, static = run_static(p)
    nesting, dynamic = run_nesting(p)
    # every nesting time up to the last arrival binds something (else the nesting run has extra time points)
    arrivals = sorted({o.arrival for o in inst.orders} - {0})
    assert nesting.done and nesting.instance() == inst
    assert plain(dynamic.schedule) == plain(static.schedule)
    def timeless(decisions):  # planner_time is wall clock
        return [{k: v for k, v in d.items() if k != "planner_time"} for d in decisions]

    assert timeless(dynamic.decisions) == timeless(static.decisions)
    assert len(arrivals) >= 2  # at least two packages after the backlog


# --- the norm (N5) by hand ---------------------------------------------------------------------------------------


def test_budget_by_hand():
    # norm 2 days * 1000 = 2000, reserve 1 forecast order * 500 = 500, wip 900 -> 600 minutes = 600 / (500 / 4)
    # = 4.8 telescopes; capacity 1500 minutes = 12 telescopes
    from simulation.arrival_generator import ReleaseNorm
    from simulation.model.schedule import Assignment
    from simulation.sim.snapshot import FrozenOperation, Snapshot

    norm = ReleaseNorm(machines=("mill1",), capacity_per_day=1000, window_days=2, default_load=500,
                       forecast=dict.fromkeys(range(5), 1.0))
    nesting = Nesting(params(norm=norm))
    plan = [Assignment(order_id="a", op_id="x", machine="mill1", start=100, end=500),  # running, expected end 400
            Assignment(order_id="a", op_id="y", machine="mill1", start=500, end=1100),  # planned: 600
            Assignment(order_id="a", op_id="z", machine="print1", start=0, end=900)]  # not gated
    snap = Snapshot(instance="x", t=200, frozen=(FrozenOperation(order_id="a", op_id="x", machine="mill1", start=100,
                                                                  end=500, running=True),))
    # wip = (500 - 200) + 600 = 900
    assert nesting.budget(200, 1680, plan, snap) == pytest.approx((4.8, 12.0))


def test_average_daily_capacity_by_hand():
    # default calendar: shift 08:00, last start 17:30 + 120 = 19:30 (690 min after shift start); longest job 1240:
    # Monday-Thursday capped at the next 08:00 (1440), Friday 690 + 1240 = 1930; average (4 * 1440 + 1930) / 5
    assert average_daily_capacity(Calendar(), 1240) == pytest.approx((4 * 1440 + 1930) / 5)
    assert average_daily_capacity(Calendar(), 300) == pytest.approx(690 + 300)


def test_default_order_load_by_hand():
    # one order of 4 telescopes alone: blank 10 + 4 * 8 + 10 = 52, plate 10 + 4 * 3 + 10 = 32; longest operation 32
    assert default_order_load(BASE, MILLS) == (84, 32)


def test_norm_holds_orders_back_and_every_order_still_arrives_before_its_due_date():
    # a tight norm on purpose (one default order per day): with three mills the computed one would never bind here
    load, _ = default_order_load(BASE, MILLS)
    norm = {"machines": MILLS, "capacity_per_day": load, "window_days": 1, "default_load": load,
            "forecast": dict.fromkeys(range(5), 0.5)}
    p = params(norm=norm, seed=2)
    inst, _ = run_static(params(seed=2))
    nesting, result = run_nesting(p)
    held = nesting.instance()
    assert nesting.done
    free = {o.id: o.arrival for o in inst.orders}
    assert all(o.arrival >= free[o.id] and o.arrival <= o.due_date for o in held.orders)
    assert any(o.arrival > free[o.id] for o in held.orders)  # the norm binds in this setting


@pytest.mark.parametrize(("changes", "message"), [
    ({"norm": {"machines": (), "capacity_per_day": 1, "window_days": 1, "default_load": 1}}, r"at least 1 item"),
    ({"norm": {"machines": ("mill1",), "capacity_per_day": 1, "default_load": 1}}, r"window_days"),
    ({"norm": {"machines": ("mill1",), "capacity_per_day": 1, "window_days": 1, "default_load": 1,
               "forecast": {6: 1.0}}}, r"forecast for weekdays \[6\] without nesting"),
    ({"norm": {"machines": ("mill1",), "capacity_per_day": 1, "window_days": 1, "default_load": 1},
      "quota": dict.fromkeys(range(5), 2)}, r"quota and norm: one release rule"),
])
def test_invalid_norm_rejected(changes, message):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=message):
        params(**changes)


def test_nesting_needs_a_planner():
    nesting = Nesting(params())
    ci0 = compile_instance(nesting.instance())
    start = dispatch_plan(ci0, spt, ect)
    with pytest.raises(ValueError, match="needs a planner"):
        execute(ci0, start.assignments, nesting=nesting)


# --- experiment runner ---------------------------------------------------------------------------------------------


def norm_for(window_days=2, forecast=1.0):
    load, longest = default_order_load(BASE, MILLS)
    return {"machines": MILLS, "capacity_per_day": average_daily_capacity(BASE.calendar, longest, len(MILLS)),
            "window_days": window_days, "default_load": load, "forecast": dict.fromkeys(range(5), forecast)}


def test_hindsight_with_a_norm_rejected():
    from pydantic import ValidationError

    from simulation.experiment import ExperimentConfig

    with pytest.raises(ValidationError, match=r"policies \['h'\]: hindsight needs fixed arrivals"):
        ExperimentConfig(name="x", arrivals=params(norm=norm_for()), seeds=(1,),
                         policies={"h": {"planner": "rule", "hindsight": True}})


@pytest.mark.parametrize("backlog", [0, 1])
def test_run_one_with_a_norm_and_without_backlog(tmp_path, backlog):
    # backlog 0: nothing is known at 0, the start plan is empty and the first plan comes with the first nesting
    from simulation.experiment import ExperimentConfig, run_one

    config = ExperimentConfig(name="n", arrivals=params(norm=norm_for(), rates=dict.fromkeys(range(5), 2.0),
                                                        window_days=3, backlog=backlog), seeds=(1,),
                              policies={"rule": {"planner": "rule"}})
    row = run_one(config, "rule", 1, tmp_path)
    if backlog == 0:
        assert row["start_status"] == "EMPTY"
    assert row["orders"] >= 1 and row["mean_pool_time"] >= 0 and row["max_pool_time"] >= row["mean_pool_time"]


def test_run_one_without_backlog_and_without_norm(tmp_path):
    # the crash of protocol 2026-11-18 (65): backlog 0 with fixed arrivals
    from simulation.experiment import ExperimentConfig, run_one

    config = ExperimentConfig(name="b0", arrivals=params(rates=dict.fromkeys(range(5), 2.0), window_days=3,
                                                         backlog=0), seeds=(1,), policies={"rule": {"planner": "rule"}})
    row = run_one(config, "rule", 1, tmp_path)
    assert row["start_status"] == "EMPTY" and row["orders"] >= 1
