import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.calendar import day_index, is_working_day, minute_of_day, next_cutoff
from simulation.carrier_generator import CarrierGeneratorParams, PerCarrierStep, generate_carrier_instance
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance
from simulation.objectives import MAKESPAN
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import dispatch, dispatch_plan, ect, spt
from simulation.sim.des import replay

# dental-like route: design, milling of the primary parts, carrier from print to saw with one QM per carrier
ROUTE = [
    {"id": "design", "step": "design"},
    {"id": "mill", "step": "mill", "scope": "primary", "predecessors": ["design"]},
    {"id": "print", "step": "print", "scope": "carrier", "role": "form", "predecessors": ["design"]},
    {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["print"]},
    {"id": "qm", "step": "qm", "scope": "carrier", "predecessors": ["oven", "mill"]},
    {"id": "saw", "step": "saw", "scope": "carrier", "role": "separate", "predecessors": ["qm"]},
    {"id": "finish", "step": "finish", "predecessors": ["saw"]},
]
BASE = {
    "seed": 3, "n_orders": 10, "release_range": (0, 30), "route": ROUTE,
    "machines": {"design": 2, "mill": 3, "print": 2, "oven": 1, "qm": 1, "saw": 1, "finish": 2},
    "durations": {"design": (10, 20), "mill": (5, 10), "print": (60, 90), "oven": (90, 90), "qm": (10, 15),
                  "saw": (5, 10), "finish": (10, 20)},
    "setup": 10, "removal": 10, "unit_time": 8, "estimator": {"fixed": 20, "share": 0.5},
}


def params(**changes) -> CarrierGeneratorParams:
    return CarrierGeneratorParams(**{**BASE, **changes})


def test_nesting_by_hand():
    # 7 orders with 4 primary parts each (size 4), capacity 12: three orders per carrier, in index order (no due
    # dates, all released at 0); two carriers per run
    inst = generate_carrier_instance(params(n_orders=7, release_range=(0, 0), count_range=(4, 4),
                                            carriers_per_run=2))
    assert [(c.id, [k for k, _ in c.parts]) for c in inst.carriers] == [
        ("C1", ["O1", "O2", "O3"]), ("C2", ["O4", "O5", "O6"]), ("C3", ["O7"])]
    assert [(r.id, r.carriers) for r in inst.runs] == [("R1", ("C1", "C2")), ("R2", ("C3",))]
    assert all(len([p for p in o.parts if p.type == "primary"]) == 4 for o in inst.orders)


def test_same_seed_same_instance():
    assert generate_carrier_instance(params()) == generate_carrier_instance(params())
    assert generate_carrier_instance(params()) != generate_carrier_instance(params(seed=4))


@pytest.mark.parametrize("seed", range(10))
def test_nesting_respects_capacity_runs_and_due_date_order(seed):
    inst = generate_carrier_instance(params(seed=seed, n_orders=15, due_date_tightness=(1.5, 2.0)))
    size = {o.id: sum(p.type == "primary" for p in o.parts) for o in inst.orders}
    due = {o.id: o.due_date for o in inst.orders}
    assert all(1 <= n <= 7 for n in size.values())
    assert sorted(k for c in inst.carriers for k, _ in c.parts) == sorted(size)  # every order on one carrier
    assert all(sum(size[k] for k, _ in c.parts) <= 12 for c in inst.carriers)
    assert all(len(r.carriers) <= 4 for r in inst.runs)
    in_nesting_order = [due[k] for c in inst.carriers for k, _ in c.parts]
    assert in_nesting_order == sorted(in_nesting_order)  # earliest due date first


def test_part_type_operations_scale_with_the_number_of_parts():
    inst = generate_carrier_instance(params())
    for o in inst.orders:
        n = sum(p.type == "primary" for p in o.parts)
        mill = next(op for op in o.operations if op.id == "mill")
        assert all(d % n == 0 and 5 * n <= d <= 10 * n for d in mill.options.values())
        assert next(p for p in o.parts if p.type == "secondary").times == {"print": 8 * n}


def test_generated_instance_is_solvable_and_replays_unchanged():
    ci = compile_instance(generate_carrier_instance(params(n_orders=6)))
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []
        realized = replay(ci, plan).schedule
        def key(a):
            return a.order_id, a.op_id

        assert sorted(realized, key=key) == sorted(plan, key=key)


@pytest.mark.parametrize(("changes", "message"), [
    ({"count_range": (1, 13)}, r"a carried part of size 13 exceeds the carrier capacity 12"),
    ({"machines": {**BASE["machines"], "oven": 0}}, r"greater than 0"),
    ({"machines": {k: v for k, v in BASE["machines"].items() if k != "saw"}}, r"no machines for steps \['saw'\]"),
    ({"durations": {k: v for k, v in BASE["durations"].items() if k != "qm"}}, r"no durations for steps \['qm'\]"),
    ({"run_step": "design"}, r"run step 'design' is not a carrier step of the route"),
    ({"unit_time": None}, r"the estimator needs unit_time"),
    ({"count_range": (5, 2)}, r"count_range: min 5 > max 2"),
    ({"batch_capacity": {"print": 3}}, r"batch_capacity for \['print'\]: only carrier steps other than the run step"),
    ({"batch_capacity": {"oven": 1}}, r"greater than or equal to 2"),
])
def test_invalid_parameters_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


# blanks: primary parts of several orders on one blank (mill per blank, separation, polishing), carrier milling
# per plate after the oven; both milling steps on the same mills
BLANK_ROUTE = [
    {"id": "design", "step": "design"},
    {"id": "mill_blank", "step": "mill_blank", "scope": "carrier", "carries": "primary", "role": "form",
     "predecessors": ["design"]},
    {"id": "separate", "step": "separate", "scope": "carrier", "carries": "primary", "role": "separate",
     "predecessors": ["mill_blank"]},
    {"id": "polish", "step": "polish", "scope": "primary", "predecessors": ["separate"]},
    {"id": "print", "step": "print", "scope": "carrier", "carries": "secondary", "role": "form",
     "predecessors": ["design"]},
    {"id": "oven", "step": "oven", "scope": "carrier", "carries": "secondary", "predecessors": ["print"]},
    {"id": "mill_carrier", "step": "mill_carrier", "scope": "carrier", "carries": "secondary",
     "predecessors": ["oven"]},
    {"id": "qm", "step": "qm", "scope": "carrier", "carries": "secondary", "predecessors": ["mill_carrier", "polish"]},
    {"id": "saw", "step": "saw", "scope": "carrier", "carries": "secondary", "role": "separate",
     "predecessors": ["qm"]},
    {"id": "finish", "step": "finish", "predecessors": ["saw"]},
]
BLANKS = {
    "route": BLANK_ROUTE,
    "machines": {"design": 2, "mill": 3, "bench": 2, "print": 2, "oven": 1, "qm": 1, "saw": 1, "finish": 2},
    "machine_pool": {"mill_blank": "mill", "mill_carrier": "mill", "separate": "bench", "polish": "bench"},
    "durations": {**{k: v for k, v in BASE["durations"].items() if k != "mill"}, "mill_blank": (30, 30),
                  "mill_carrier": (20, 20), "separate": (5, 5), "polish": (3, 6)},
    "per_carrier": {"mill_blank": {"setup": 5, "removal": 5, "unit_time": 12},
                    "mill_carrier": {"setup": 5, "removal": 5, "unit_time": 4}},
    "batch_capacity": {"oven": 3}, "blank_capacity": 6,
}


def test_blank_nesting_and_times_by_hand():
    # 3 orders with 4 primary parts each, blank capacity 6, index order: B1 = O1 n1..n4 + O2 n1, n2;
    # B2 = O2 n3, n4 + O3 n1..n4 (O2 spans two blanks)
    inst = generate_carrier_instance(params(**BLANKS, n_orders=3, release_range=(0, 0), count_range=(4, 4)))
    blanks = [(c.id, c.parts) for c in inst.carriers if c.id.startswith("B")]
    assert blanks == [("B1", (("O1", "n1"), ("O1", "n2"), ("O1", "n3"), ("O1", "n4"), ("O2", "n1"), ("O2", "n2"))),
                      ("B2", (("O2", "n3"), ("O2", "n4"), ("O3", "n1"), ("O3", "n2"), ("O3", "n3"), ("O3", "n4")))]
    parts = {p.id: p for p in inst.orders[0].parts}
    assert parts["c"].times == {"print": 32, "mill_carrier": 16}  # 4 telescopes * 4
    assert parts["n1"].times == {"mill_blank": 12}
    assert set(inst.carrier_steps["mill_blank"].options) == set(inst.carrier_steps["mill_carrier"].options) == {
        "mill1", "mill2", "mill3"}
    assert inst.carrier_steps["mill_carrier"].runs == "per_carrier"
    ci = compile_instance(inst)
    assert dict(ci.options[ci.op_index["B1", "mill_blank"]]) == dict.fromkeys(
        (ci.machine_index[m] for m in ("mill1", "mill2", "mill3")), 6 * 12)
    polish = {ci.op_keys[q] for q in ci.predecessors[ci.op_index["O2", "polish"]]}
    assert polish == {("B1", "separate"), ("B2", "separate")}  # O2's primary parts are on both blanks


def test_generated_instance_with_blanks_is_solvable_and_replays_unchanged():
    ci = compile_instance(generate_carrier_instance(params(**BLANKS, n_orders=6)))
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []
        assert {(a.order_id, a.op_id): (a.machine, a.start) for a in replay(ci, plan).schedule} == {
            (a.order_id, a.op_id): (a.machine, a.start) for a in plan}


@pytest.mark.parametrize(("changes", "message"), [
    ({"blank_capacity": None}, r"blank_capacity is needed exactly when carrier operations carry 'primary'"),
    ({"per_carrier": {**BLANKS["per_carrier"], "print": {"unit_time": 1}}},
     r"per_carrier for \['print'\]: only carrier steps other than the run step and batch steps"),
    ({"per_carrier": {**BLANKS["per_carrier"], "oven": {"unit_time": 1}}}, r"per_carrier for \['oven'\]"),
    ({"machine_pool": {**BLANKS["machine_pool"], "grind": "mill"}}, r"machine_pool for steps \['grind'\] not in the"),
    ({"machine_pool": {**BLANKS["machine_pool"], "polish": "lathe"}}, r"no machines for steps \['polish'\]"),
    ({"route": [{**op, "carries": "tertiary"} if op["id"] == "oven" else op for op in BLANK_ROUTE]},
     r"carrier operations carry \['tertiary'\]"),
    ({"route": [{**op, "carries": "primary"} if op["id"] == "print" else op for op in BLANK_ROUTE]},
     r"run step 'print' must not carry 'primary'"),
])
def test_invalid_blank_parameters_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**{**BLANKS, **changes})


def test_blank_capacity_without_blanks_rejected():
    with pytest.raises(ValidationError, match=r"blank_capacity is needed exactly when"):
        params(blank_capacity=6)


def test_example_parameter_file():
    path = Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-example.json"
    inst = generate_carrier_instance(read_model(path, CarrierGeneratorParams))
    assert len(inst.orders) == 40 and all(o.due_date is not None for o in inst.orders)
    assert inst.carrier_steps["oven"].batch_capacity == 3


# --- workers and calendar (step 4b, math/21_instance-generator.md) ---------------------------------------------------

SHARES = [{"worker": {"whole": True}}, {"worker": {"whole": True}}, {"attended": ["setup", "removal"]},
          {"worker": {"prefix": 10, "suffix": 10}}, {"worker": {"whole": True, "qualified": ["A"]}},
          {"worker": {"whole": True}}, {"worker": {"whole": True}}]
WORKERS = {"route": [op | s for op, s in zip(ROUTE, SHARES, strict=True)], "workers": ["A", "B", "C"], "calendar": {}}


def test_worker_shares_and_calendar_reach_the_instance():
    inst = generate_carrier_instance(params(**WORKERS, due_date_tightness=(2.0,)))
    assert inst.workers == ("A", "B", "C") and inst.calendar is not None
    ops = {op.id: op for op in inst.orders[0].operations}
    assert ops["design"].worker.whole and ops["mill"].worker.whole and ops["finish"].worker.whole
    assert ops["oven"].worker is None  # a carrier operation takes its share from the carrier step
    steps = inst.carrier_steps
    assert (steps["oven"].worker.prefix, steps["oven"].worker.suffix) == (10, 10)
    assert steps["qm"].worker.qualified == ("A",) and steps["saw"].worker.whole
    assert steps["print"].setup_attended and steps["print"].removal_attended and steps["print"].worker is None
    assert all(next_cutoff(inst.calendar, o.due_date) == o.due_date for o in inst.orders)  # V11


def test_generated_instance_with_workers_keeps_shift_hours():
    # without workers 35 of 66 operations of such an instance started outside the shift (protocol 2026-11-12)
    ci = compile_instance(generate_carrier_instance(params(**WORKERS, n_orders=6)))
    result = solve(ci, MAKESPAN, time_limit=20, workers=1)
    assert result.schedule and not check_schedule(ci, result.schedule, breaks=result.breaks)
    cal = ci.calendar
    for a in result.schedule:
        o = ci.op_index[a.order_id, a.op_id]
        if any(sh.kind == "whole" for sh in ci.shares[o]):  # a worker's whole share lies inside a working day
            assert is_working_day(cal, day_index(cal, a.start))
            assert cal.shift_start <= minute_of_day(cal, a.start) < cal.shift_end + cal.max_overtime
    def plain(schedule):  # realized schedules carry the share lengths, plans do not
        return sorted((a.model_copy(update={"share_lengths": ()}) for a in schedule),
                      key=lambda a: (a.order_id, a.op_id))

    assert plain(replay(ci, result.schedule, breaks=result.breaks).schedule) == plain(result.schedule)


def test_attended_only_on_carrier_operations():
    route = [ROUTE[0] | {"attended": ["setup"]}, *ROUTE[1:]]
    with pytest.raises(ValidationError, match=r"attended \['setup'\] on design: only for carrier operations"):
        params(route=route)


def test_worker_shares_need_workers():
    with pytest.raises(ValidationError, match=r"\[V7\]"):
        generate_carrier_instance(params(route=WORKERS["route"]))


def test_example_parameter_file_with_workers():
    path = Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-workers.json"
    inst = generate_carrier_instance(read_model(path, CarrierGeneratorParams))
    assert inst.workers == ("A", "B", "C", "D") and inst.calendar is not None
    # every order and part operation and every carrier step needs a worker somewhere (no robot steps)
    assert all(op.worker is not None for o in inst.orders for op in o.operations if op.scope != "carrier")
    assert all(cs.worker is not None or cs.setup_attended for cs in inst.carrier_steps.values())


DATA = Path(__file__).parents[1] / "data"


def test_route_reference_resolves_like_the_inline_route(tmp_path):
    referenced = read_model(DATA / "generator" / "dental-carriers-workers.json", CarrierGeneratorParams)
    inline = tmp_path / "inline.json"
    raw = referenced.model_dump(mode="json")
    inline.write_text(json.dumps(raw), encoding="utf-8")
    assert read_model(inline, CarrierGeneratorParams) == referenced
    assert [op.id for op in referenced.route][:2] == ["design", "mill_blank"]


def test_route_reference_in_experiment_config_resolves_relative_to_the_config():
    from simulation.experiment import ExperimentConfig

    config = read_model(Path(__file__).parents[1] / "experiments" / "arrivals-rate6.json", ExperimentConfig)
    workers = read_model(DATA / "generator" / "dental-carriers-workers.json", CarrierGeneratorParams)
    assert config.arrivals.base.route == workers.route


def test_route_reference_to_missing_file_rejected(tmp_path):
    raw = read_model(DATA / "generator" / "dental-carriers-example.json", CarrierGeneratorParams)
    raw = raw.model_dump(mode="json")
    path = tmp_path / "params.json"
    path.write_text(json.dumps(raw | {"route": "routes/missing.json"}), encoding="utf-8")
    with pytest.raises(ValidationError, match="referenced file .* not found"):
        read_model(path, CarrierGeneratorParams)


def test_route_reference_without_a_file_rejected():
    raw = read_model(DATA / "generator" / "dental-carriers-example.json", CarrierGeneratorParams)
    raw = raw.model_dump(mode="json")
    with pytest.raises(ValidationError, match="needs read_model"):
        CarrierGeneratorParams.model_validate(raw | {"route": "../routes/dental.json"})


ROOT = Path(__file__).parents[1]

# --- options added for the Fidentis case (2026-11-16, math/21_instance-generator.md §4a) ---

# instance digests of every parameter file before the options existed: unset options change nothing
DIGESTS_BEFORE = {
    "data/generator/dental-carriers-example.json": "c90eaeb9f0b4aee9",
    "data/generator/dental-carriers-workers.json": "78f387eacc615135",
}
# configuration hashes of the experiments running when the options were added (rows carry them, math/07 §5)
CONFIG_HASHES_BEFORE = {
    "arrivals-rate4": "583b92a7a3cd", "arrivals-rate6-undisturbed": "239f7d5d296e", "arrivals-rate6": "2287d12d6b96",
    "arrivals-rate8-double": "f1c4c1f3be5f", "arrivals-rate8": "eaf43e4b3216", "nesting-daily": "37627a445be3",
    "nesting-weekly": "7139374f68ee",
}


@pytest.mark.parametrize("path", sorted(DIGESTS_BEFORE))
def test_unset_options_leave_instances_unchanged(path):
    import hashlib

    inst = generate_carrier_instance(read_model(ROOT / path, CarrierGeneratorParams))
    assert hashlib.sha256(inst.model_dump_json().encode()).hexdigest()[:16] == DIGESTS_BEFORE[path]


@pytest.mark.parametrize("name", sorted(CONFIG_HASHES_BEFORE))
def test_unset_options_leave_experiment_hashes_unchanged(name):
    from simulation.experiment import ExperimentConfig

    assert read_model(ROOT / "experiments" / f"{name}.json", ExperimentConfig).digest() == CONFIG_HASHES_BEFORE[name]


def test_run_capacity_closes_runs_by_size_by_hand():
    # 6 orders of size 4, carrier capacity 8: carriers O1+O2, O3+O4, O5+O6 (8 each); runs of at most 4 carriers
    # but 20 size units: two carriers (16) per run, a third would give 24
    inst = generate_carrier_instance(params(n_orders=6, release_range=(0, 0), count_range=(4, 4),
                                            carrier_capacity=8, run_capacity=20))
    assert [r.carriers for r in inst.runs] == [("C1", "C2"), ("C3",)]
    inst = generate_carrier_instance(params(n_orders=6, release_range=(0, 0), count_range=(4, 4),
                                            carrier_capacity=8, run_capacity=24))
    assert [r.carriers for r in inst.runs] == [("C1", "C2", "C3")]


def test_unit_base_adds_to_the_run_step_part_time():
    inst = generate_carrier_instance(params(unit_base=150))
    for o in inst.orders:
        n = sum(p.type == "primary" for p in o.parts)
        assert next(p for p in o.parts if p.type == "secondary").times == {"print": 150 + 8 * n}


def test_lognormal_count_by_seed_statistics():
    # median 4, sigma 0.5, clipped to [1, 12]: median of the draws 4, all within the range, not all equal
    sizes = [sum(p.type == "primary" for p in o.parts) for o in generate_carrier_instance(
        params(n_orders=400, count_range=(1, 12), count_lognormal=(4, 0.5))).orders]
    assert sorted(sizes)[200] == 4 and min(sizes) >= 1 and max(sizes) <= 12 and len(set(sizes)) > 4
    # clipping: sigma large, upper bound 5
    sizes = [sum(p.type == "primary" for p in o.parts) for o in generate_carrier_instance(
        params(n_orders=200, count_range=(1, 5), count_lognormal=(4, 2.0))).orders]
    assert max(sizes) == 5 and min(sizes) == 1


def test_no_machine_steps_get_a_duration_and_stay_solvable():
    # an operation without machine needs a worker share ([V6]): design and finish whole, by workers A and B
    route = [op | {"worker": {"whole": True}} if op["id"] in ("design", "finish") else op for op in ROUTE]
    ci_params = params(n_orders=5, route=route, workers=("A", "B"), no_machine=("design", "finish"),
                       machines={k: v for k, v in BASE["machines"].items() if k not in ("design", "finish")})
    inst = generate_carrier_instance(ci_params)
    for o in inst.orders:
        ops = {op.id: op for op in o.operations}
        assert ops["design"].options is None and 10 <= ops["design"].duration <= 20
        assert ops["finish"].options is None and ops["mill"].options is not None
    ci = compile_instance(inst)
    for plan in (dispatch(ci, spt, ect), solve(ci, time_limit=10, workers=1).schedule):
        assert check_schedule(ci, plan) == []


def test_base_durations_add_once_per_operation():
    inst = generate_carrier_instance(params(base_durations={"mill": 7, "finish": 3}))
    for o in inst.orders:
        n = sum(p.type == "primary" for p in o.parts)
        ops = {op.id: op for op in o.operations}
        assert all((d - 7) % n == 0 and 5 * n <= d - 7 <= 10 * n for d in ops["mill"].options.values())
        assert all(13 <= d <= 23 for d in ops["finish"].options.values())


@pytest.mark.parametrize(("changes", "message"), [
    ({"base_durations": {"oven": 5}}, r"base_durations for carrier steps \['oven'\]"),
    ({"base_durations": {"polish": 5}}, r"base_durations for steps \['polish'\] not in the route"),
    ({"no_machine": ("oven",)}, r"no_machine for carrier steps \['oven'\]"),
    ({"no_machine": ("polish",)}, r"no_machine for steps \['polish'\] not in the route"),
    ({"no_machine": ("design",)}, r"no_machine steps \['design'\] also have machines"),
    ({"run_capacity": 10}, r"run_capacity 10 below carrier_capacity 12"),
    ({"count_lognormal": (9, 0.5)}, r"count_lognormal median 9.0 outside count_range \[1, 7\]"),
    ({"count_lognormal": (4, 0)}, r"greater than 0"),
    ({"unit_base": 5, "unit_time": None, "estimator": None}, r"unit_base needs unit_time"),
])
def test_invalid_fidentis_options_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        params(**changes)


def test_fidentis_mill_minutes_by_hand():
    # one order of 4 telescopes (math/21 §4a, MES seed times with the corrections of 2026-11-16): primary
    # 15 + 4 * 62 + 10 (blank, pass 1) + 15 + 4 * 60 (pass 2) = 528; secondary 15 + 4 * 30 + 5 (plate) +
    # 2 rework rounds of 20 + 4 * 70 = 740
    base = read_model(ROOT / "data/generator/fidentis.json", CarrierGeneratorParams)
    # the stand-in pool for worker-only carrier steps must never bind before the workers (math/21 §6)
    assert base.machines["hand"] >= len(base.workers)
    ci = compile_instance(generate_carrier_instance(base.model_copy(update={
        "n_orders": 1, "count_range": (4, 4), "count_lognormal": None})))
    mill = {}
    for o, (_, op_id) in enumerate(ci.op_keys):
        if ci.options[o] and ci.machine_ids[ci.options[o][0][0]] == "mill1":
            step = next(s for s in ("mill_blank", "mill_flipped", "mill_carrier", "rework") if s in op_id)
            mill[step] = mill.get(step, 0) + ci.options[o][0][1]
    assert mill == {"mill_blank": 273, "mill_flipped": 255, "mill_carrier": 140, "rework": 600}
    assert mill["mill_blank"] + mill["mill_flipped"] == 528 and mill["mill_carrier"] + mill["rework"] == 740


def test_fidentis_worker_carrier_steps_by_hand():
    # one order of 4 telescopes, one plate and one blank (user 2026-11-17): base once per carrier as the setup of a
    # per-carrier run, then per unit. qm 15 + 4 * 15; recheck the same, twice; saw 15 + 15 per secondary part;
    # gegenbetten 5 + 4 * 5 attended + 15 unattended (the removal); separation 10 + 4 * 10; clean, blast one plate
    base = read_model(ROOT / "data/generator/fidentis.json", CarrierGeneratorParams)
    inst = generate_carrier_instance(base.model_copy(update={
        "n_orders": 1, "count_range": (4, 4), "count_lognormal": None}))
    ci = compile_instance(inst)
    hand = {}
    for o, (_, op_id) in enumerate(ci.op_keys):
        if ci.options[o] and ci.machine_ids[ci.options[o][0][0]].startswith("hand"):
            step = next(s for s in ("clean", "blast", "qm", "recheck", "saw", "gegenbetten", "separate")
                        if s in op_id)
            hand[step] = hand.get(step, 0) + ci.options[o][0][1]
    assert hand == {"clean": 25, "blast": 10, "qm": 75, "recheck": 150, "saw": 30, "gegenbetten": 40,
                    "separate": 50}
    gb = inst.carrier_steps["gegenbetten"]
    assert gb.setup_attended and not gb.removal_attended  # the 15 of curing need no worker


def test_per_carrier_part_time_must_be_positive():
    with pytest.raises(ValidationError, match=r"part_base \+ unit_time must be > 0"):
        PerCarrierStep(unit_time=0)


def test_fidentis_parameter_file_is_solvable_and_replays_unchanged():
    ci = compile_instance(generate_carrier_instance(read_model(ROOT / "data/generator/fidentis.json",
                                                               CarrierGeneratorParams)))
    plan = dispatch_plan(ci, spt, ect)
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
    result = solve(ci, MAKESPAN, time_limit=20, workers=1)
    assert result.schedule and not check_schedule(ci, result.schedule, breaks=result.breaks)

    def plain(schedule):
        return sorted((a.model_copy(update={"share_lengths": ()}) for a in schedule),
                      key=lambda a: (a.order_id, a.op_id))

    assert plain(replay(ci, result.schedule, breaks=result.breaks).schedule) == plain(result.schedule)
