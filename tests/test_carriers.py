"""Carriers and runs (math/03_loads.md): format, derived synchronization, checker C8 / C9."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.due_dates import assign_due_dates, lead_time_bound
from simulation.metrics import run_metrics
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.model.instance import Instance, estimate_run_duration
from simulation.model.schedule import Assignment
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import cpsat_planner, solve
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch, dispatch_planner, ect, spt
from simulation.sim.des import Simulation, replay
from simulation.sim.scenario import Scenario, sample_scenario

PATH = Path(__file__).parents[1] / "data" / "instances" / "toy-carriers.json"
# A has parts on L1 and L2 (split order), B on L1 (with a primary part), C on L2 (no primary part).
# Print runs R1 = [L1], R2 = [L2]; setup 1, print 4 on P, removal 1.
INSTANCE = Instance.model_validate_json(PATH.read_text(encoding="utf-8"))
CI = compile_instance(INSTANCE)

# hand-computed plan, one machine of each kind:
# design D: A [0,2) B [2,4) C [4,6); mill M: A [2,5) B [5,8)
# R1 on P: setup [4,5) print [5,9) removal [9,10); R2 waits for P and C's design: [10,11) [11,15) [15,16)
# oven O: L1 [10,13) L2 [16,19); QM: L1 waits for B's mill (8) and its oven: [13,14), L2 [19,20)
# saw S: L1 [14,15) L2 [20,21); finish F: B [15,16), A waits for both saws [21,22), C [22,23)
PLAN = [
    Assignment(order_id=o, op_id=j, machine=m, start=s, end=e)
    for o, j, m, s, e in [
        ("A", "design", "D", 0, 2), ("B", "design", "D", 2, 4), ("C", "design", "D", 4, 6),
        ("A", "mill", "M", 2, 5), ("B", "mill", "M", 5, 8),
        ("R1", "setup", "P", 4, 5), ("R1", "print", "P", 5, 9), ("R1", "removal", "P", 9, 10),
        ("R2", "setup", "P", 10, 11), ("R2", "print", "P", 11, 15), ("R2", "removal", "P", 15, 16),
        ("L1", "oven", "O", 10, 13), ("L2", "oven", "O", 16, 19),
        ("L1", "qm", "Q", 13, 14), ("L2", "qm", "Q", 19, 20),
        ("L1", "saw", "S", 14, 15), ("L2", "saw", "S", 20, 21),
        ("B", "finish", "F", 15, 16), ("A", "finish", "F", 21, 22), ("C", "finish", "F", 22, 23),
    ]
]


def preds(ci, key):
    return {ci.op_keys[p] for p in ci.predecessors[ci.op_index[key]]}


def changed(plan, **moves):
    """moves: 'owner/op' -> (machine, start, end)."""
    out = []
    for a in plan:
        if (m := moves.get(f"{a.order_id}/{a.op_id}")) is not None:
            a = a.model_copy(update={"machine": m[0], "start": m[1], "end": m[2]})
        out.append(a)
    return out


# --- derived synchronization --------------------------------------------------------------------


def test_one_operation_per_carrier_and_run_instead_of_per_order():
    owners = {}
    for owner, op in CI.op_keys:
        owners.setdefault(owner, []).append(op)
    assert owners == {"A": ["design", "mill", "finish"], "B": ["design", "mill", "finish"], "C": ["design", "finish"],
                      "L1": ["oven", "qm", "saw"], "L2": ["oven", "qm", "saw"],
                      "R1": ["setup", "print", "removal"], "R2": ["setup", "print", "removal"]}
    assert [CI.order_ids[k] for k in CI.op_orders[CI.op_index["L2", "qm"]]] == ["A", "C"]
    assert CI.machine_groups == tuple(tuple(CI.op_index[r, j] for j in ("setup", "print", "removal"))
                                      for r in ("R1", "R2"))


def test_synchronization_in_qm_per_carrier_and_out():
    assert preds(CI, ("R1", "setup")) == {("A", "design"), ("B", "design")}  # every order on the plate designed
    assert preds(CI, ("L1", "oven")) == {("R1", "removal")}  # the plate leaves the printer after removal
    assert preds(CI, ("L1", "qm")) == {("L1", "oven"), ("A", "mill"), ("B", "mill")}  # primary parts of its orders
    assert preds(CI, ("L2", "qm")) == {("L2", "oven"), ("A", "mill")}  # C has no primary part
    assert preds(CI, ("A", "finish")) == {("L1", "saw"), ("L2", "saw")}  # A continues after both plates are sawn


def test_one_print_run_with_two_carriers():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    data["runs"] = [{"id": "R1", "step": "print", "carriers": ["L1", "L2"]}]
    ci = compile_instance(Instance.model_validate(data))
    assert preds(ci, ("R1", "setup")) == {("A", "design"), ("B", "design"), ("C", "design")}
    assert preds(ci, ("L1", "oven")) == preds(ci, ("L2", "oven")) == {("R1", "removal")}


# --- checker ------------------------------------------------------------------------------------


def test_hand_computed_plan_is_feasible():
    assert check_schedule(CI, PLAN) == []
    assert max(a.end for a in PLAN) == 23


def test_run_on_two_machines_is_reported():
    plan = changed(PLAN, **{"R1/print": ("P2", 5, 10), "R1/removal": ("P", 10, 11)})
    assert "C8" in {v.constraint for v in check_schedule(CI, plan)}


def test_machine_is_blocked_between_print_and_removal():
    # R1's removal waits one minute after the print ([9,10) idle on P); R2's setup is placed in that gap. No pair of
    # single operations overlaps there, only the blocked span of R1 does.
    plan = changed(PLAN, **{"R1/removal": ("P", 10, 11), "R2/setup": ("P", 9, 10), "R2/print": ("P", 11, 15),
                            "L1/oven": ("O", 11, 14), "L1/qm": ("Q", 14, 15), "L1/saw": ("S", 15, 16),
                            "B/finish": ("F", 16, 17)})
    violations = check_schedule(CI, plan)
    assert {v.constraint for v in violations} == {"C9"}
    assert [v.ops for v in violations] == [(("R1", "setup"), ("R2", "setup"))]


@pytest.mark.parametrize(("move", "pair"), [
    ({"L1/qm": ("Q", 7, 8), "L1/oven": ("O", 4, 7)}, (("B", "mill"), ("L1", "qm"))),  # QM before B's primary part
    ({"A/finish": ("F", 16, 17)}, (("L2", "saw"), ("A", "finish"))),  # A before its second plate is sawn
])
def test_waiting_across_orders_is_checked(move, pair):
    assert pair in {v.ops for v in check_schedule(CI, changed(PLAN, **move)) if v.constraint == "C3"}


# --- validation: one negative test per rule ----------------------------------------------------


def data():
    return json.loads(PATH.read_text(encoding="utf-8"))


def op(d, order, op_id):
    return next(o for o in next(x for x in d["orders"] if x["id"] == order)["operations"] if o["id"] == op_id)


def m_duplicate_part(d):
    d["orders"][0]["parts"].append({"id": "s1", "type": "secondary"})


def m_unknown_scope(d):
    op(d, "A", "mill")["scope"] = "tertiary"


def m_carrier_op_with_options(d):
    op(d, "A", "oven")["options"] = {"O": 3}


def m_no_carrier_step(d):
    for o in d["orders"]:
        op(d, o["id"], "oven")["step"] = "bake"


def m_options_missing(d):
    del op(d, "A", "mill")["options"]


def m_role_on_order_op(d):
    op(d, "A", "finish")["role"] = "separate"


def m_no_forming_op(d):
    del op(d, "C", "print")["role"]


def m_unknown_machine_in_step(d):
    d["carrier_steps"]["saw"]["options"]["S9"] = 1


def m_owner_id_twice(d):
    d["carriers"][0]["id"] = "A"


def m_unknown_part(d):
    d["carriers"][0]["parts"].append(["B", "x"])


def m_part_on_two_carriers(d):
    d["carriers"][1]["parts"].append(["B", "s"])


def m_carrier_ops_without_carrier(d):
    d["carriers"][1]["parts"] = [["A", "s2"]]


def m_carried_without_carrier_ops(d):
    d["orders"].append({"id": "D", "parts": [{"id": "s", "type": "secondary"}],
                        "operations": [{"id": "design", "step": "design", "options": {"D": 2}}]})
    d["carriers"][1]["parts"].append(["D", "s"])


def m_different_carrier_routes(d):
    op(d, "C", "oven")["id"] = "bake"
    op(d, "C", "qm")["predecessors"] = ["bake"]


def m_run_unknown_step(d):
    d["runs"][0]["step"] = "glaze"


def m_run_unknown_carrier(d):
    d["runs"][0]["carriers"] = ["L9"]


def m_run_step_not_passed(d):
    d["carrier_steps"]["glaze"] = {"options": {"O": 1}, "runs": "given"}
    d["runs"].append({"id": "R3", "step": "glaze", "carriers": ["L1"]})


def m_carrier_in_two_runs(d):
    d["runs"][1]["carriers"] = ["L2", "L1"]


def m_carrier_in_no_run(d):
    d["runs"] = d["runs"][:1]


def m_cycle_through_runs(d):
    # D passes qm before oven; runs that group oven and qm of L1 (oven first) with L3 (qm first) wait for each other
    d["orders"].append({"id": "D", "parts": [{"id": "s", "type": "secondary"}], "operations": [
        {"id": "design", "step": "design", "options": {"D": 2}},
        {"id": "print", "step": "print", "scope": "carrier", "role": "form", "predecessors": ["design"]},
        {"id": "qm", "step": "qm", "scope": "carrier", "predecessors": ["print"]},
        {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["qm"]},
        {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["oven"]},
    ]})
    d["carriers"].append({"id": "L3", "parts": [["D", "s"]]})
    d["runs"] += [{"id": "R3", "step": "print", "carriers": ["L3"]},
                  {"id": "R4", "step": "oven", "carriers": ["L1", "L2", "L3"]},
                  {"id": "R5", "step": "qm", "carriers": ["L1", "L2", "L3"]}]
    for step in ("oven", "qm"):
        d["carrier_steps"][step]["runs"] = "given"


@pytest.mark.parametrize(("mutate", "message"), [
    (m_duplicate_part, r"order A: duplicate part IDs: \['s1'\]"),
    (m_unknown_scope, r"order A, op mill: unknown scope 'tertiary'"),
    (m_carrier_op_with_options, r"order A, op oven: carrier operation with options"),
    (m_no_carrier_step, r"order A, op oven: no carrier step 'bake'"),
    (m_options_missing, r"order A, op mill: options or duration missing"),
    (m_role_on_order_op, r"order A, op finish: role 'separate' only for carrier operations"),
    (m_no_forming_op, r"order C: carrier operations must form one chain from a forming to a separating"),
    (m_unknown_machine_in_step, r"carrier step saw: unknown machines \['S9'\]"),
    (m_owner_id_twice, r"duplicate IDs across orders, carriers and runs: \['A'\]"),
    (m_unknown_part, r"carrier L1: unknown part \('B', 'x'\)"),
    (m_part_on_two_carriers, r"part \('B', 's'\) on carriers L1 and L2"),
    (m_carrier_ops_without_carrier, r"order C has carrier operations but no part on a carrier"),
    (m_carried_without_carrier_ops, r"order D has parts on carriers but no carrier operations"),
    (m_different_carrier_routes, r"carrier L2: member orders have different carrier routes"),
    (m_run_unknown_step, r"run R1: no carrier step 'glaze'"),
    (m_run_unknown_carrier, r"run R1: unknown carrier L9"),
    (m_run_step_not_passed, r"run R3: carrier L1 does not pass step glaze"),
    (m_carrier_in_two_runs, r"carrier L1 in runs R1 and R2 of step print"),
    (m_carrier_in_no_run, r"carrier L2 passes step print but is in no run of it"),
    (m_cycle_through_runs, r"cycle across orders and carriers"),
], ids=lambda v: v.__name__ if callable(v) else None)
def test_invalid_carrier_instance_rejected(mutate, message):
    d = data()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)


# --- step 2: dispatching and DES -----------------------------------------------------------------


def by_key(schedule):
    return sorted(schedule, key=lambda a: (a.order_id, a.op_id))


def scenario(**offsets):
    """No duration deviation; start offsets per 'owner/op'."""
    return Scenario(instance=CI.name, seed=0, sigma=0, factors=[
        {"order_id": k, "op_id": j, "factor": 1.0, "start_offset": offsets.get(f"{k}/{j}", 0)} for k, j in CI.op_keys])


def test_spt_with_ect_reproduces_the_hand_computed_plan():
    assert by_key(dispatch(CI, spt, ect)) == by_key(PLAN)


@pytest.mark.parametrize("rule", [(s, a) for s in SEQUENCING_RULES for a in [*ASSIGNMENT_RULES, None]],
                         ids=lambda r: f"{r[0]}-{r[1] or 'joint'}")
def test_every_rule_keeps_runs_on_one_machine_and_replays_unchanged(rule):
    plan = dispatch(CI, SEQUENCING_RULES[rule[0]], ASSIGNMENT_RULES[rule[1]] if rule[1] else None)
    assert check_schedule(CI, plan) == []  # incl. C8 and C9
    assert by_key(replay(CI, plan).schedule) == by_key(plan)  # zero-disturbance


def test_zero_disturbance_of_the_hand_plan():
    assert by_key(replay(CI, PLAN).schedule) == by_key(PLAN)
    assert by_key(replay(CI, PLAN, scenario()).schedule) == by_key(PLAN)


def test_late_removal_blocks_the_printer():
    # R1's removal (planned [9,10)) starts 2 minutes late: [11,12). The printer stays blocked: R2's setup
    # (planned [10,11)) waits until 12, and L1 leaves the printer only then (oven from 12).
    schedule = replay(CI, PLAN, scenario(**{"R1/removal": 2})).schedule
    realized = {(a.order_id, a.op_id): (a.start, a.end) for a in schedule}
    assert realized["R1", "removal"] == (11, 12)
    assert realized["R2", "setup"] == (12, 13)
    assert realized["L1", "oven"] == (12, 15)


@pytest.mark.parametrize("seed", range(5))
def test_disturbed_execution_with_repair_keeps_runs_together(seed):
    sc = sample_scenario(INSTANCE, sigma=0.3, seed=seed, q=0.5, max_early=2, max_late=2)
    realized = execute(CI, PLAN, sc, ReschedulingPolicy()).schedule
    assert {v.constraint for v in check_schedule(CI, realized)} <= {"C2"}  # durations differ by design


def test_order_completions_count_carrier_operations():
    # A ends with its finish at 22 (after both saws), B at 16, C at 23; flow times from release 0
    m = run_metrics(CI, PLAN, execute(CI, PLAN))
    assert m["mean_flow_time"] == pytest.approx((22 + 16 + 23) / 3)
    assert MAKESPAN.evaluate(CI, PLAN) == 23


# --- step 3: CP-SAT ------------------------------------------------------------------------------


def test_cpsat_optimum_by_hand():
    # Lower bound 20: the first print run needs two designs (>= 4) and 6 minutes on a printer, so its carrier reaches
    # the single oven at 10 at the earliest; the second carrier's oven ends at >= 16, its saw at >= 18, and both of
    # its orders (A and one other) finish after it, one after the other on F: >= 20. CP-SAT reaches it with R2 on P2.
    result = solve(CI, time_limit=10, workers=1)
    assert (result.status, result.objective, result.bound) == ("OPTIMAL", 20, 20)
    assert check_schedule(CI, result.schedule) == []


def test_zero_disturbance_of_the_cpsat_plan():
    plan = solve(CI, time_limit=10, workers=1).schedule
    realized = replay(CI, plan).schedule
    assert by_key(realized) == by_key(plan) and MAKESPAN.evaluate(CI, realized) == 20


def one_printer() -> CompiledInstance:
    d = data()
    d["carrier_steps"]["print"]["options"] = {"P": 4}
    return compile_instance(Instance.model_validate(d))


def test_cpsat_keeps_the_printer_blocked_while_a_removal_waits():
    # one printer; R1's removal starts 2 minutes late, so at t = 10 the print is done and the removal is still
    # pending. Without C9 the solver could put R2's setup into the gap before R1's removal.
    ci = one_printer()
    sim = Simulation(ci, PLAN, Scenario(instance=ci.name, seed=0, sigma=0, factors=[
        {"order_id": k, "op_id": j, "factor": 1.0, "start_offset": 2 if (k, j) == ("R1", "removal") else 0}
        for k, j in ci.op_keys]))
    sim.run(until=10)
    snap = sim.snapshot()
    plan = {(a.order_id, a.op_id): a for a in solve(ci, time_limit=10, workers=1, snapshot=snap).schedule}
    assert check_schedule(ci, plan.values(), snap) == []
    assert plan["R2", "setup"].start >= plan["R1", "removal"].end


def test_cpsat_continues_a_partly_started_run_on_its_machine():
    # at t = 5 R1's setup is done and its print is running on P; the removal must follow on P
    sim = Simulation(CI, PLAN)
    sim.run(until=5)
    snap = sim.snapshot()
    plan = {(a.order_id, a.op_id): a for a in solve(CI, time_limit=10, workers=1, snapshot=snap).schedule}
    assert check_schedule(CI, plan.values(), snap) == []
    assert plan["R1", "removal"].machine == "P"


# --- step 4: duration of a run from its parts -----------------------------------------------------


@pytest.mark.parametrize(("times", "fixed", "share", "expected"), [
    ([2, 2], 1, 0.5, 3),  # 1 + 0.5 * 4 = 3, inside [2, 4]
    ([1, 2], 0, 0.5, 2),  # 0.5 * 3 = 1.5 rounds up to 2
    ([5, 1], 0, 0.0, 5),  # never shorter than the longest part (p-batch bound)
    ([2, 2], 10, 0.5, 4),  # never longer than all parts one after another (s-batch bound)
])
def test_estimate_run_duration_by_hand(times, fixed, share, expected):
    assert estimate_run_duration(times, fixed, share) == expected


def with_part_times(**run_durations):
    """Print times of the parts alone: A/s1 2, B/s 2, A/s2 2, C/s 3; estimator 1 + 0.5 * sum."""
    d = data()
    times = {("A", "s1"): 2, ("B", "s"): 2, ("A", "s2"): 2, ("C", "s"): 3}
    for o in d["orders"]:
        for part in o["parts"]:
            if (o["id"], part["id"]) in times:
                part["times"] = {"print": times[o["id"], part["id"]]}
    d["carrier_steps"]["print"]["estimator"] = {"fixed": 1, "share": 0.5}
    for r in d["runs"]:
        if r["id"] in run_durations:
            r["duration"] = run_durations[r["id"]]
    return compile_instance(Instance.model_validate(d))


def print_times(ci):
    return {r: dict(ci.options[ci.op_index[r, "print"]]) for r in ("R1", "R2")}


def test_run_duration_from_the_estimator_on_every_printer():
    # R1 holds A/s1 and B/s: 1 + 0.5 * 4 = 3; R2 holds A/s2 and C/s: 1 + 0.5 * 5 = 3.5 -> 4
    ci = with_part_times()
    p, p2 = ci.machine_index["P"], ci.machine_index["P2"]
    assert print_times(ci) == {"R1": {p: 3, p2: 3}, "R2": {p: 4, p2: 4}}


def test_nesting_duration_overrides_the_estimate():
    ci = with_part_times(R1=7)
    assert set(print_times(ci)["R1"].values()) == {7} and set(print_times(ci)["R2"].values()) == {4}


def test_estimated_durations_reach_every_consumer():
    # one interface (compilation): rules, CP-SAT and the DES all see the estimated print times
    ci = with_part_times()
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []
        assert {a.end - a.start for a in plan if a.op_id == "print"} <= {3, 4}
        assert by_key(replay(ci, plan).schedule) == by_key(plan)


def m_time_for_unknown_step(d):
    d["orders"][0]["parts"][0]["times"] = {"glaze": 2}


def m_estimator_without_part_times(d):
    d["carrier_steps"]["print"]["estimator"] = {"fixed": 1, "share": 0.5}


def m_share_above_one(d):
    d["carrier_steps"]["print"]["estimator"] = {"fixed": 1, "share": 1.5}


@pytest.mark.parametrize(("mutate", "message"), [
    (m_time_for_unknown_step, r"order A, part s1: times for unknown carrier steps \['glaze'\]"),
    (m_estimator_without_part_times, r"run R1: no print time for parts"),
    (m_share_above_one, r"less than or equal to 1"),
], ids=lambda v: v.__name__ if callable(v) else None)
def test_invalid_estimator_input_rejected(mutate, message):
    d = data()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)


# --- step 5: rescheduling and due dates ------------------------------------------------------------


def test_dispatching_continues_a_partly_started_run():
    # at t = 5 R1's setup is done and its print is running on P: the removal follows on P right after the print
    sim = Simulation(CI, PLAN)
    sim.run(until=5)
    snap = sim.snapshot()
    plan = {(a.order_id, a.op_id): a for a in dispatch(CI, spt, ect, snap)}
    assert check_schedule(CI, plan.values(), snap) == []
    assert (plan["R1", "removal"].machine, plan["R1", "removal"].start) == ("P", 9)


@pytest.mark.parametrize("planner", ["rule", "cpsat"])
@pytest.mark.parametrize("seed", range(4))
def test_rescheduling_on_carriers_keeps_every_constraint(planner, seed):
    plan_of = {"rule": dispatch_planner(spt, ect), "cpsat": cpsat_planner(time_limit=2)}
    policy = ReschedulingPolicy(plan_of[planner], max_makespan_change=0, period=5)
    sc = sample_scenario(INSTANCE, sigma=0.3, seed=seed, q=0.5, max_early=2, max_late=2)
    result = execute(CI, PLAN, sc, policy)
    assert {v.constraint for v in check_schedule(CI, result.schedule)} <= {"C2"}  # durations differ by design
    assert any(d["type"] == "REPLAN" for d in result.decisions)


def test_due_dates_for_carrier_instances():
    # lead-time bound of A: design 2 + print (average of P 4 and P2 5, plus setup 1 and removal 1) 6.5 + oven 3
    # + QM 1 + saw 1 + finish 1 = 14.5 (the milling path is shorter); B and C the same
    assert [lead_time_bound(o, INSTANCE.carrier_steps) for o in INSTANCE.orders] == [14.5, 14.5, 14.5]
    # from the hand plan: carrier and run entries count for their orders; A ends 22, B 16, C 23
    assert [o.due_date for o in assign_due_dates(INSTANCE, (1.0,), 0, reference=PLAN).orders] == [22, 16, 23]
