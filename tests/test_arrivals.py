"""Order arrivals, step 1: format (accepted, arrival), packages, visible sub-instance (math/07_order-arrivals.md)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.metrics import run_metrics
from simulation.model.compiled import compile_instance, compile_visible
from simulation.model.instance import Instance, visible_instance
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import dispatch_planner, ect, spt
from simulation.sim.des import PlanNotExecutable, Simulation, replay
from simulation.sim.scenario import sample_scenario

DATA = Path(__file__).parents[1] / "data"


def two_packages(arrival: int = 10) -> dict:
    """toy-carriers twice: package 1 (A, B, C on L1, L2, runs R1, R2) known at 0, package 2 (A2, B2, C2 on L12,
    L22, runs R12, R22) arriving at `arrival`, released then."""
    base = json.loads((DATA / "instances" / "toy-carriers.json").read_text(encoding="utf-8"))
    late = copy.deepcopy(base)
    for o in late["orders"]:
        o["id"] += "2"
        o["arrival"] = o["release"] = arrival
    for c in late["carriers"]:
        c["id"] += "2"
        c["parts"] = [[k + "2", p] for k, p in c["parts"]]
    for r in late["runs"]:
        r["id"] += "2"
        r["carriers"] = [c + "2" for c in r["carriers"]]
    return base | {"name": "two-packages", "orders": base["orders"] + late["orders"],
                   "carriers": base["carriers"] + late["carriers"], "runs": base["runs"] + late["runs"]}


# --- format -------------------------------------------------------------------------------------------------------


def test_defaults_known_from_the_start(toy_data):
    inst = Instance.model_validate(toy_data)
    assert all(o.accepted == 0 and o.arrival == 0 for o in inst.orders)


def test_accepted_arrival_release_in_order(toy_data):
    toy_data["orders"][0] |= {"accepted": 2, "arrival": 5, "release": 7}
    order = Instance.model_validate(toy_data).orders[0]
    assert (order.accepted, order.arrival, order.release) == (2, 5, 7)


def test_two_packages_valid():
    inst = Instance.model_validate(two_packages())
    assert [o.arrival for o in inst.orders] == [0, 0, 0, 10, 10, 10]


def arrival_after_release(d):
    d["orders"][0] |= {"arrival": 6, "release": 5}


def accepted_after_arrival(d):
    d["orders"][0] |= {"accepted": 6, "arrival": 5, "release": 5}


def negative_arrival(d):
    d["orders"][0]["arrival"] = -1


def negative_accepted(d):
    d["orders"][0]["accepted"] = -1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (arrival_after_release, r"order J1: arrival 6 after release 5"),
        (accepted_after_arrival, r"order J1: accepted 6 after arrival 5"),
        (negative_arrival, r"greater than or equal to 0"),
        (negative_accepted, r"greater than or equal to 0"),
    ],
    ids=lambda v: v.__name__ if callable(v) else None,
)
def test_invalid_times_rejected(toy_data, mutate, message):
    mutate(toy_data)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(toy_data)


def test_carrier_across_packages_rejected():
    d = two_packages()
    carriers = {c["id"]: c for c in d["carriers"]}
    carriers["L2"]["parts"] = [["A", "s2"], ["C2", "s"]]  # swap C and C2: both carriers mix the packages
    carriers["L22"]["parts"] = [["A2", "s2"], ["C", "s"]]
    with pytest.raises(ValidationError, match=r"carrier L2: orders with different arrivals \{'A': 0, 'C2': 10\}"):
        Instance.model_validate(d)


def test_run_across_packages_rejected():
    d = two_packages()
    d["runs"] = [r for r in d["runs"] if r["id"] != "R12"]
    next(r for r in d["runs"] if r["id"] == "R1")["carriers"] = ["L1", "L12"]
    with pytest.raises(ValidationError, match=r"run R1: carriers with different arrivals \{'L1': 0, 'L12': 10\}"):
        Instance.model_validate(d)


# --- visible sub-instance -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("t", "orders", "carriers", "runs"), [
    (0, ["A", "B", "C"], ["L1", "L2"], ["R1", "R2"]),
    (9, ["A", "B", "C"], ["L1", "L2"], ["R1", "R2"]),
    (10, ["A", "B", "C", "A2", "B2", "C2"], ["L1", "L2", "L12", "L22"], ["R1", "R2", "R12", "R22"]),
])
def test_visible_instance_holds_the_known_packages(t, orders, carriers, runs):
    inst = Instance.model_validate(two_packages())
    vis = visible_instance(inst, t)
    assert [o.id for o in vis.orders] == orders
    assert [c.id for c in vis.carriers] == carriers
    assert [r.id for r in vis.runs] == runs
    assert vis.name == inst.name  # scenarios and snapshots keep matching by name
    assert Instance.model_validate(vis.model_dump()) == vis  # a valid instance on its own
    ci = compile_instance(vis)
    assert set(ci.order_ids) == set(orders)


def test_visible_instance_after_all_arrivals_is_the_instance():
    inst = Instance.model_validate(two_packages())
    assert visible_instance(inst, 10) == inst


# --- DES (step 2) and planning tool (step 3): arrival event, unplanned operations inert, arrival trigger ---


def by_op(schedule):
    return sorted(schedule, key=lambda a: (a.order_id, a.op_id))


def setup(arrival: int = 10):
    inst = Instance.model_validate(two_packages(arrival))
    return compile_instance(inst), compile_visible(inst)


def start_plan(at):
    return solve(at(0), time_limit=5, workers=1).schedule


def run_with_arrivals(ci, at, plan, scenario=None, planner=None, **policy):
    """execute with arrivals; returns the realized schedule and the times of the arrival reschedulings."""
    policy = ReschedulingPolicy(planner=planner or cpsat_planner(time_limit=5), **policy)
    result = execute(ci, plan, scenario, policy, visible=at)
    return result, [d["t"] for d in result.decisions if d["type"] == "REPLAN" and "arrival" in d["triggers"]]


LATE = {"A2", "B2", "C2", "L12", "L22", "R12", "R22"}  # owners of package 2


def test_hindsight_plan_with_arrivals_replays_unchanged():
    # zero disturbance: a plan of the full instance (all arrivals known) runs exactly as planned
    ci, _ = setup()
    plan = solve(ci, time_limit=5, workers=1).schedule
    realized = replay(ci, plan).schedule
    assert by_op(realized) == by_op(plan)
    assert not check_schedule(ci, realized)


def test_unplanned_package_stays_idle_until_the_tool_plans_it():
    ci, at = setup()
    sim = Simulation(ci, start_plan(at), visible=at)
    assert {a.order_id for a in sim.current_plan()} & LATE == set()
    with pytest.raises(RuntimeError, match="operations never completed"):
        sim.run()
    assert not [e for e in sim.log if e["order_id"] in LATE]
    assert not [f for f in sim.snapshot().frozen if f.order_id in LATE]


def test_plan_with_an_unknown_order_is_rejected():
    # no leakage: before its arrival the factory takes no plan that holds package 2
    ci, at = setup()
    full_plan = solve(ci, time_limit=5, workers=1).schedule
    with pytest.raises(PlanNotExecutable, match=r"\[C0\]"):
        Simulation(ci, full_plan, visible=at)


def test_arrival_with_carriers_is_planned_at_its_arrival():
    ci, at = setup()
    result, replans = run_with_arrivals(ci, at, start_plan(at))
    realized = result.schedule
    assert replans == [10]
    assert not check_schedule(ci, realized)
    assert all(a.start >= 10 for a in realized if a.order_id in LATE)


def test_arrival_during_a_run_keeps_the_run():
    ci0, at0 = setup()
    plan0 = start_plan(at0)
    run = [a for a in plan0 if a.order_id == "R1"]
    t = min(a.start for a in run) + 2  # inside R1 (setup 1, print 4 or 5, removal 1)
    assert t < max(a.end for a in run)
    ci, at = setup(arrival=t)
    result, replans = run_with_arrivals(ci, at, start_plan(at))
    realized = result.schedule
    assert replans == [t]
    assert by_op([a for a in realized if a.order_id == "R1"]) == by_op(run)  # started run untouched, C8/C9
    assert not check_schedule(ci, realized)


def test_arrival_at_a_planned_start():
    ci0, at0 = setup()
    plan0 = start_plan(at0)
    t = min(a.start for a in plan0 if a.start > 0)
    ci, at = setup(arrival=t)
    result, replans = run_with_arrivals(ci, at, start_plan(at))
    realized = result.schedule
    assert replans == [t]
    assert not check_schedule(ci, realized)
    assert all(a.start >= t for a in realized if a.order_id in LATE)


def test_arrival_triggers_a_complete_rescheduling_with_cpsat():
    ci, at = setup()
    result, replans = run_with_arrivals(ci, at, start_plan(at))
    replan = next(d for d in result.decisions if d["t"] == 10 and d["type"] == "REPLAN")
    assert replans == [10] and replan["accepted"]
    assert replan["inserted"] == sum(owner in LATE for owner, _ in ci.op_keys)
    assert not check_schedule(ci, result.schedule)


def test_arrival_with_a_dispatching_rule():
    ci, at = setup()
    result, replans = run_with_arrivals(ci, at, start_plan(at), planner=dispatch_planner(spt, ect))
    assert replans == [10]
    assert not check_schedule(ci, result.schedule)
    assert all(a.start >= 10 for a in result.schedule if a.order_id in LATE)


def test_arrival_rescheduling_respects_the_change_budget_of_the_old_orders():
    # budget 0: no old operation changes its machine; the new orders are placed anyway (never rejected)
    ci, at = setup()
    plan = start_plan(at)
    result, replans = run_with_arrivals(ci, at, plan, planner=cpsat_planner(time_limit=5, change_budget=0),
                                        change_budget=0)
    assert replans == [10]
    machine = {(a.order_id, a.op_id): a.machine for a in plan}
    assert all(a.machine == machine[a.order_id, a.op_id] for a in result.schedule if a.order_id not in LATE)
    assert not check_schedule(ci, result.schedule)


@pytest.mark.parametrize("policy", [None, ReschedulingPolicy()], ids=["no tool", "repair only"])
def test_arrivals_need_a_planner(policy):
    ci, at = setup()
    with pytest.raises(ValueError, match="arrivals need a planner"):
        execute(ci, start_plan(at), policy=policy, visible=at)


def test_hand_computed_arrival():
    # a1 (M1, 4) known at 0; b1 (M1: 2, M2: 5) arrives at 2. At 2, a1 runs on M1 until 4; b1 on M1 ends at 6, on M2
    # at 7: the optimum puts b1 on M1 at [4, 6), makespan 6, equal to the hindsight optimum (nothing lost by not
    # knowing b1 earlier here)
    inst = Instance.model_validate({"schema_version": "0.7", "name": "hand-arrival", "machines": ["M1", "M2"],
                                    "orders": [
        {"id": "A", "operations": [{"id": "a1", "step": "s", "options": {"M1": 4}}]},
        {"id": "B", "arrival": 2, "release": 2,
         "operations": [{"id": "b1", "step": "s", "options": {"M1": 2, "M2": 5}}]},
    ]})
    ci, at = compile_instance(inst), compile_visible(inst)
    result, replans = run_with_arrivals(ci, at, start_plan(at))
    b1 = next(a for a in result.schedule if a.order_id == "B")
    assert replans == [2]
    assert (b1.machine, b1.start, b1.end) == ("M1", 4, 6)
    assert max(a.end for a in result.schedule) == 6 == solve(ci, time_limit=5, workers=1).objective


def test_metrics_of_a_run_with_arrivals():
    # the hand instance with B accepted at 1: A ends 4 (released 0), B ends 6 (released 2); flow times 4, 4, lead
    # times from the acceptance 4, 5; the start plan holds only a1, which keeps its start and machine
    inst = Instance.model_validate({"schema_version": "0.7", "name": "hand-arrival", "machines": ["M1", "M2"],
                                    "orders": [
        {"id": "A", "operations": [{"id": "a1", "step": "s", "options": {"M1": 4}}]},
        {"id": "B", "accepted": 1, "arrival": 2, "release": 2,
         "operations": [{"id": "b1", "step": "s", "options": {"M1": 2, "M2": 5}}]},
    ]})
    ci, at = compile_instance(inst), compile_visible(inst)
    plan = start_plan(at)
    result, _ = run_with_arrivals(ci, at, plan)
    m = run_metrics(ci, plan, result)
    assert (m["mean_flow_time"], m["mean_lead_time"], m["arrival_reschedulings"]) == (4, 4.5, 1)
    assert (m["mean_start_deviation"], m["machine_changes"]) == (0, 0)


@pytest.mark.parametrize("seed", range(4))
def test_disturbed_run_with_arrival_repairs_and_reschedules(seed):
    # deviations before and after the arrival: repairs, threshold reschedulings and the arrival rescheduling mix
    inst = Instance.model_validate(two_packages())
    ci, at = compile_instance(inst), compile_visible(inst)
    scenario = sample_scenario(inst, sigma=0.3, seed=seed, q=0.5, max_early=2, max_late=3)
    result, replans = run_with_arrivals(ci, at, start_plan(at), scenario, max_shift=1, period=20)
    assert replans == [10]
    assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}  # realized durations deviate
    assert all(a.start >= 10 for a in result.schedule if a.order_id in LATE)
