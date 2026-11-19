"""The BRKGA (math/14_genetic-algorithm.md): the decoder's delay window, decoding, the GA loop. Small instances only."""

from pathlib import Path

import pytest
from test_rescheduling import PLAN, TOY, disturbed, of_type
from test_s_batch_format import tiny

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.objectives import MAKESPAN, OVERTIME, overtime
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import dispatch_plan, ect, spt
from simulation.planners.ga import N_KEYS, GaParams, decode, delay_unit, encode, ga_planner, rule_plans, solve_ga
from simulation.sim.des import replay

DATA = Path(__file__).parents[1] / "data"
FAST = GaParams(population=20, generations=15, time_limit=None)
N_RULES = 15  # 5 sequencing x (2 assignment + joint) rule plans, each decoded once


def toy(name: str):
    return compile_instance(read_model(DATA / "instances" / name, Instance))


def dental():
    return compile_instance(generate_carrier_instance(
        read_model(DATA / "generator" / "dental-carriers-workers.json", CarrierGeneratorParams)))


INSTANCES = {
    "toy-3x3": lambda: toy("toy-3x3.json"),
    "toy-dag-3x4": lambda: toy("toy-dag-3x4.json"),
    "toy-workers": lambda: toy("toy-workers.json"),
    "mk01": lambda: compile_instance(load_fjs(DATA / "benchmarks" / "brandimarte" / "BrandimarteMk1.fjs")),
    "dental-workers": dental,
    # s-batches (polish, pack) with worker A and the default calendar: about two days of polish, so random overtime
    # keys plan overtime next to batches
    "s-batches": lambda: compile_instance(Instance.model_validate(
        tiny(6, orders=12, polish={"setup": 5, "capacity": 12}, pack={"setup": 5}).model_dump(mode="json")
        | {"calendar": {}})),
}


def wait_for_batch():
    """Two orders: prep on M1 (1 min), then polish on M2 (5 min incl. setup 2), polish an s-batch step. A non-delay
    pass starts the first polish alone at 1 and the second at 6: makespan 11. Waiting until 2 puts both in one
    batch [2, 2 + 2 + 3 + 3) = [2, 10): makespan 10, optimal (the second prep ends at 2 at the earliest, a batch of
    both lasts 8; apart, the second polish ends at 1 + 5 + 5 = 11)."""
    order = lambda k: {"id": k, "operations": [  # noqa: E731
        {"id": "a", "step": "prep", "options": {"M1": 1}},
        {"id": "b", "step": "polish", "options": {"M2": 5}, "predecessors": ["a"]}]}
    return compile_instance(Instance.model_validate({
        "schema_version": "0.8", "name": "wait", "machines": ["M1", "M2"], "orders": [order("J1"), order("J2")],
        "s_batch_steps": {"polish": {"setup": 2}}}))


@pytest.mark.parametrize("name", INSTANCES)
def test_zero_delay_is_the_non_delay_plan(name):
    ci = INSTANCES[name]()
    assert dispatch_plan(ci, spt, ect, delay=[0] * ci.n_ops) == dispatch_plan(ci, spt, ect)


def test_every_rule_misses_the_wait_and_cpsat_confirms_ten():
    ci = wait_for_batch()
    assert min(MAKESPAN.evaluate(ci, p.assignments) for p in rule_plans(ci)) == 11
    cp = solve(ci, MAKESPAN, time_limit=10)
    assert cp.status == "OPTIMAL" and cp.objective == 10


def test_hand_chromosome_waits_and_batches():
    # keys: J1/a, J2/a, J2/b, J1/b; iteration 3 sees J2/b (start 2) within its delay, it leads, J1/b joins
    ci = wait_for_batch()
    seq = {("J1", "a"): 0.1, ("J2", "a"): 0.2, ("J2", "b"): 0.3, ("J1", "b"): 0.4}
    genes = [seq[k] for k in ci.op_keys] + [0.5] * ci.n_ops + [0.5] * ci.n_ops + [0.0] * ci.n_ops
    plan = decode(ci, genes, delay_unit(ci, 1.5))
    by_key = {(a.order_id, a.op_id): a for a in plan.assignments}
    j1, j2 = by_key["J1", "b"], by_key["J2", "b"]
    assert (j1.start, j1.end) == (2, 10) == (j2.start, j2.end)
    assert by_key["J1", "b"].batch == by_key["J2", "b"].batch is not None
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
    without_delay = decode(ci, genes[:2 * ci.n_ops] + [0.0] * (2 * ci.n_ops), delay_unit(ci, 1.5))
    assert MAKESPAN.evaluate(ci, without_delay.assignments) == 11


def test_ga_finds_the_wait():
    ci = wait_for_batch()
    result = solve_ga(ci, MAKESPAN, FAST)
    assert result.value == 10 == MAKESPAN.evaluate(ci, result.plan.assignments)
    assert check_schedule(ci, result.plan.assignments, breaks=result.plan.breaks) == []


@pytest.mark.parametrize("name", INSTANCES)
def test_ga_plan_is_feasible_and_not_worse_than_any_rule(name):
    ci = INSTANCES[name]()
    # the dental case decodes in about 0.15 s (287 operations with workers): a smaller run
    params = GaParams(population=10, generations=3, time_limit=None) if name == "dental-workers" else FAST
    result = solve_ga(ci, MAKESPAN, params)
    assert check_schedule(ci, result.plan.assignments, breaks=result.plan.breaks) == []
    assert result.value == MAKESPAN.evaluate(ci, result.plan.assignments, result.plan.breaks)
    assert result.value <= min(MAKESPAN.evaluate(ci, p.assignments, p.breaks) for p in rule_plans(ci))
    assert list(result.history) == sorted(result.history, reverse=True)  # the incumbent never gets worse
    n = params.population
    assert result.generations == params.generations
    assert result.evaluations == N_RULES + n + params.generations * (n - params.n_elite)


@pytest.mark.parametrize("name", ["toy-workers", "dental-workers", "s-batches"])
def test_random_chromosomes_decode_to_feasible_plans(name):
    # every key vector is a valid chromosome: no repair needed (Bean 1994)
    import random
    ci, rng = INSTANCES[name](), random.Random(3)
    planned_overtime = 0
    for _ in range(10):
        plan = decode(ci, [rng.random() for _ in range(N_KEYS * ci.n_ops)], delay_unit(ci, 1.5))
        assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
        planned_overtime += overtime(ci, plan.assignments)
    assert planned_overtime > 0 or ci.calendar is None or name == "toy-workers"  # the overtime keys are used


def test_same_seed_same_plan_other_seed_runs():
    ci = INSTANCES["mk01"]()
    a, b = solve_ga(ci, MAKESPAN, FAST), solve_ga(ci, MAKESPAN, FAST)
    assert a.plan == b.plan and a.history == b.history


def test_machine_key_picks_the_machine():
    # toy-3x3 J1/1 may use M1 (4) or M2 (5): key < 0.5 picks the first option, >= 0.5 the second
    ci = toy("toy-3x3.json")
    o = ci.op_index["J1", "1"]
    names = [ci.machine_ids[m] for m, _ in ci.options[o]]
    for key, machine in ((0.2, names[0]), (0.7, names[1])):
        genes = [0.5] * ci.n_ops + [0.5] * ci.n_ops + [0.0] * (2 * ci.n_ops)
        genes[ci.n_ops + o] = key
        plan = decode(ci, genes, delay_unit(ci, 1.5))
        assert next(a.machine for a in plan.assignments if (a.order_id, a.op_id) == ("J1", "1")) == machine


def test_encode_ranks_by_start_and_keeps_the_machines():
    ci = toy("toy-3x3.json")
    plan = dispatch_plan(ci, spt, ect)
    genes = encode(ci, plan.assignments)
    assert len(genes) == N_KEYS * ci.n_ops and all(0 <= g < 1 for g in genes)
    assert genes[2 * ci.n_ops:] == [0.0] * (2 * ci.n_ops)
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in plan.assignments}
    order = sorted(range(ci.n_ops), key=lambda o: genes[o])
    assert [by_op[o].start for o in order] == sorted(a.start for a in plan.assignments)
    machines = {(a.order_id, a.op_id): a.machine for a in decode(ci, genes, 1.0).assignments}
    assert machines == {(a.order_id, a.op_id): a.machine for a in plan.assignments}


@pytest.mark.parametrize(("params", "message"), [
    ({"generations": None, "time_limit": None}, "generation limit, a time limit or both"),
    ({"population": 5, "elite": 0.1}, "at least one elite"),
    ({"population": 10, "elite": 0.5, "mutants": 0.5}, "at least one elite and one child"),
])
def test_invalid_params_rejected(params, message):
    with pytest.raises(ValueError, match=message):
        GaParams(**params)


# --- overtime key (step 2): t = 0 is Monday 08:00, shift end 17:30 is t = 570, maximum overtime 120 ------------------

DAY = 1440


def late_pack():
    """One 90-minute pack (worker A, whole share) released Monday 16:30: it ends 18:00 with 30 minutes of overtime,
    otherwise it waits for Tuesday 08:00 and ends 09:30."""
    order = {"id": "k", "release": 510,
             "operations": [{"id": "pack", "step": "pack", "duration": 90, "worker": {"whole": True}}]}
    return compile_instance(Instance.model_validate({
        "schema_version": "0.8", "name": "late", "machines": ["M"], "workers": ["A"], "calendar": {},
        "orders": [order]}))


def pack_times(plan):
    a = plan.assignments[0]
    return a.start, a.end


def test_overtime_allowance_by_hand():
    ci = late_pack()
    assert pack_times(dispatch_plan(ci, spt)) == (DAY, DAY + 90)
    assert pack_times(dispatch_plan(ci, spt, overtime=[29])) == (DAY, DAY + 90)  # 1 minute short
    plan = dispatch_plan(ci, spt, overtime=[30])
    assert pack_times(plan) == (510, 600) and overtime(ci, plan.assignments) == 30
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
    assert dispatch_plan(ci, spt, overtime=[0]) == dispatch_plan(ci, spt)


def test_overtime_allowance_above_the_maximum_rejected():
    with pytest.raises(ValueError, match="exceeds the maximum overtime 120"):
        dispatch_plan(late_pack(), spt, overtime=[121])


def test_ga_trades_overtime_for_makespan_only_when_the_objective_wants_it():
    ci = late_pack()
    fast = GaParams(population=10, generations=5, time_limit=None)
    short = solve_ga(ci, MAKESPAN, fast)
    assert short.value == 600 and overtime(ci, short.plan.assignments) > 0
    none = solve_ga(ci, OVERTIME, fast)
    assert none.value == 0 and pack_times(none.plan) == (DAY, DAY + 90)


# --- step 3: rescheduling planner (snapshot, warm start, change budget, time limit) -----------------------------------



@pytest.mark.parametrize("name", ["toy-3x3", "toy-workers", "s-batches"])
def test_zero_disturbance_replays_the_ga_plan(name):
    # Definition of Done: without disturbances the DES realizes the plan exactly
    ci = INSTANCES[name]()
    plan = solve_ga(ci, MAKESPAN, GaParams(population=10, generations=3, time_limit=None)).plan
    realized = replay(ci, plan.assignments, breaks=plan.breaks).schedule
    def rows(schedule):  # the DES also records realized share lengths, which a plan leaves out
        return sorted((a.order_id, a.op_id, a.machine, a.start, a.end, a.workers, a.batch) for a in schedule)

    assert rows(realized) == rows(plan.assignments)


def test_ga_reschedules_from_snapshots_in_the_des():
    # b1 takes twice as long: every complete rescheduling decodes from the snapshot with the frozen part kept; the
    # rescheduling checks each plan against the snapshot and raises if it is infeasible
    policy = ReschedulingPolicy(ga_planner(params=FAST), max_makespan_change=0)
    result = execute(TOY, PLAN, disturbed({"b1": 2.0}), policy)
    replans = of_type(result, "REPLAN")
    assert replans and all(d["accepted"] for d in replans)
    assert all(d["planner"]["generations"] == FAST.generations for d in replans)


def test_change_budget_zero_keeps_every_machine():
    # b1 takes three times as long: without a budget the GA moves two machines in its third rescheduling; with budget
    # 0 it stays within it (the warm start keeps every machine, plans over the budget rank behind it), and the policy
    # with the same budget accepts every plan
    free = of_type(execute(TOY, PLAN, disturbed({"b1": 3.0}),
                           ReschedulingPolicy(ga_planner(params=FAST), max_makespan_change=0)), "REPLAN")
    assert max(d["changed_assignments"] for d in free) > 0
    policy = ReschedulingPolicy(ga_planner(params=FAST, change_budget=0), max_makespan_change=0, change_budget=0)
    replans = of_type(execute(TOY, PLAN, disturbed({"b1": 3.0}), policy), "REPLAN")
    assert replans and [(d["accepted"], d["changed_assignments"]) for d in replans] == [(True, 0)] * len(replans)
    assert all(d["planner"]["over_budget"] == 0 for d in replans)


def test_warm_start_decodes_the_current_plan_first():
    ci = toy("toy-3x3.json")
    current = dispatch_plan(ci, spt, ect).assignments
    tiny = GaParams(population=10, time_limit=1e-9)  # out of time after the first decode
    result = solve_ga(ci, MAKESPAN, tiny, current=current)
    assert result.evaluations == 1 and result.generations == 0
    assert result.plan == decode(ci, encode(ci, current), delay_unit(ci, 1.5))
    # without a current plan the first rule plan is the fallback
    assert solve_ga(ci, MAKESPAN, tiny).evaluations == 1


def test_encode_puts_operations_missing_from_the_plan_last():
    ci = toy("toy-3x3.json")
    plan = dispatch_plan(ci, spt, ect).assignments
    late = ("J3", "2")
    genes = encode(ci, [a for a in plan if (a.order_id, a.op_id) != late])
    assert genes[ci.op_index[late]] == max(genes[:ci.n_ops])
