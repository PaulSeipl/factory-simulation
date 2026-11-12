"""Shift repair with workers and machine-less operations, no calendar (math/05_rescheduling-frozen-part.md,
math/04_workers.md C7^o; plan phase 4 task 1).

Instances: toy-workers without its calendar (print with prefix, Gegenbetten machine-less, packaging as whole shares)
and the carrier instance (oven batch with prefix and suffix, attended mill runs), plus two machine-less packaging
orders that occupy W1 or W2 at the oven's removal.
"""

import pytest
from test_des_workers import scenario
from test_dispatching_workers import RULES, TOY, by_key
from test_dispatching_workers import TOY_MODEL as TOY_MODEL_WITH_CALENDAR
from test_forced_overstay import ONE_WORKER, ROWS, SLOW_POLISH
from test_worker_compile import CARRIERS, carriers

from simulation.check.feasibility import check_schedule
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch, spt
from simulation.planners.repair import repair, repair_plan, shift_repair
from simulation.sim.scenario import sample_scenario
from simulation.sim.snapshot import FrozenOperation, Snapshot

REPAIR = ReschedulingPolicy()


def rule_plan(ci, s, a):
    return dispatch(ci, SEQUENCING_RULES[s], ASSIGNMENT_RULES[a] if a else None)


@pytest.mark.parametrize(("s", "a"), RULES)
@pytest.mark.parametrize("ci", [TOY, CARRIERS], ids=["toy-workers", "carriers"])
def test_zero_disturbance_repair_changes_nothing(ci, s, a):
    plan = rule_plan(ci, s, a)
    result = execute(ci, plan, policy=REPAIR)
    assert result.decisions == []  # every repair returned the current plan unchanged
    assert by_key(result.schedule) == by_key(plan)


def toy_plan(pack_start):
    """print by A (prefix [0, 15)), then k2 packaging by A at pack_start; Gegenbetten by A after print."""
    return [
        Assignment(order_id="k1", op_id="print", machine="P", start=0, end=60, workers=("A",)),
        Assignment(order_id="k2", op_id="pack", machine=None, start=pack_start, end=pack_start + 20, workers=("A",)),
        Assignment(order_id="k1", op_id="gb", machine=None, start=60, end=150, workers=("A",)),
        Assignment(order_id="k1", op_id="pack", machine=None, start=150, end=170, workers=("B",)),
    ]


def repaired_pack(pack_start, t, prefix_done):
    """Repair at t with print running since 0 and its prefix by A done at `prefix_done` (None: still running, so
    expected until t + 1, as the snapshot shows an overrun); k2's packaging start after the repair. On the planner's
    side only: in the DES the packaging is released at its planned start and a free qualified worker takes it."""
    length = t + 1 if prefix_done is None else prefix_done
    snap = Snapshot(instance=TOY.name, t=t, frozen=(FrozenOperation(
        order_id="k1", op_id="print", machine="P", start=0, end=60, running=True, workers=("A",),
        share_lengths=(length,)),))
    out = repair(TOY, snap, toy_plan(pack_start))
    assert check_schedule(TOY, out, snap) == []
    return next((a.start, a.workers) for a in out if (a.order_id, a.op_id) == ("k2", "pack"))


def test_late_prefix_pushes_the_same_workers_next_share():
    # prefix planned [0, 15), still running at 15: A's packaging, tight after it, moves to 16
    assert repaired_pack(15, t=15, prefix_done=None) == (16, ("A",))


def test_early_prefix_pulls_a_tight_share_forward():
    assert repaired_pack(15, t=9, prefix_done=9) == (9, ("A",))


def test_a_workers_gap_is_kept():
    # packaging planned at 20, 5 after the prefix: an early prefix does not pull it, one running until 20 not
    # either; one still running at 21 pushes it to 22
    assert repaired_pack(20, t=9, prefix_done=9) == (20, ("A",))
    assert repaired_pack(20, t=19, prefix_done=None) == (20, ("A",))
    assert repaired_pack(20, t=21, prefix_done=None) == (22, ("A",))


def test_cross_worker_cycle_reaches_the_fixpoint():
    # X: prefix A, suffix B; Y: prefix B, suffix A; A does X's prefix before Y's suffix, B Y's prefix before X's
    # suffix: the blockers form a cycle between X and Y. A late release of Y moves Y, and X stays clear of it.
    data = {"schema_version": "0.7", "name": "cycle", "machines": ["M1", "M2"], "workers": ["A", "B"], "orders": [
        {"id": "X", "operations": [{"id": "x", "step": "s", "options": {"M1": 150},
                                    "worker": {"prefix": 10, "suffix": 10}}]},
        {"id": "Y", "operations": [{"id": "y", "step": "s", "options": {"M2": 110},
                                    "worker": {"prefix": 10, "suffix": 10}}]},
    ]}
    ci = compile_instance(Instance.model_validate(data))
    x, y = ci.op_index["X", "x"], ci.op_index["Y", "y"]
    machine, order_on = [0, 1], [[x], [y]]
    workers = [[0, 1], [1, 0]]  # X: prefix A [50, 60), suffix B [190, 200); Y: prefix B [0, 10), suffix A [100, 110)
    planned_start, planned_end = [50, 0], [200, 110]
    start, end = shift_repair(ci, 0, machine, order_on, planned_start, planned_end, [None, None], [None, None],
                              workers)
    assert (start, end) == ([50, 0], [200, 110])  # nothing late: nothing moves
    # at t = 5 nothing has started: Y moves to 5 (its suffix A [105, 115)), X keeps its gap (prefix A [50, 60))
    start, end = shift_repair(ci, 5, machine, order_on, planned_start, planned_end, [None, None], [None, None],
                              workers)
    assert (start, end) == ([50, 5], [200, 115])


# --- pending removal of a running oven (C7^o) ----------------------------------------------------------------

def carriers_with_packaging() -> Instance:
    data = carriers()
    data["orders"] += [{"id": k, "operations": [{"id": "pack", "step": "pack", "duration": 4,
                                                 "worker": {"whole": True, "qualified": [w]}}]}
                       for k, w in (("C", "W2"), ("D", "W1"))]
    return Instance.model_validate(data)


PACK = compile_instance(carriers_with_packaging())
TOY_MODEL = Instance.model_validate(TOY_MODEL_WITH_CALENDAR.model_dump(exclude={"calendar"}))
MODELS = {"toy-workers": TOY_MODEL, "carriers": Instance.model_validate(carriers()),
          "carriers+pack": carriers_with_packaging()}


def oven_snapshot(busy):
    """t = 8: prints done, the oven batch of L1 and L2 running [4, 9), loaded by W1, its removal [8, 9) by W2 not
    started; `busy`: packaging orders, planned at 0, started late at 7 (C by W2 until 11, D by W1 until 10)."""
    plan = {(a.order_id, a.op_id): a for a in dispatch(PACK, spt)}
    assert (plan["L1", "oven"].start, plan["L2", "oven"].start, plan["L1", "oven"].workers) == (4, 4, ("W1", "W2"))
    frozen = [FrozenOperation(order_id=k, op_id="print", machine="P", start=a.start, end=a.end, running=False)
              for k in ("L1", "L2") for a in [plan[k, "print"]]]
    frozen += [FrozenOperation(order_id=k, op_id="oven", machine="O", start=4, end=9, running=True,
                               workers=("W1", None), share_lengths=(1, 1)) for k in ("L1", "L2")]
    ends = {"C": 11, "D": 10}
    frozen += [FrozenOperation(order_id=k, op_id="pack", machine=None, start=7, end=ends[k], running=True,
                               workers=plan[k, "pack"].workers, share_lengths=(ends[k] - 7,)) for k in sorted(busy)]
    current = [a.model_copy(update={"start": 7, "end": ends[k]}) if j == "pack" and k in busy else a
               for (k, j), a in plan.items()]
    return Snapshot(instance=PACK.name, t=8, frozen=tuple(frozen)), current


def oven(out):
    return {(a.end, a.workers) for a in out if a.op_id == "oven"}  # one run: the same for both members


def test_pending_removal_takes_the_free_worker_at_the_expected_end():
    snap, current = oven_snapshot({"C"})  # planned remover W2 busy until 11, W1 free: W1 removes at [8, 9)
    out = repair(PACK, snap, current)
    assert oven(out) == {(9, ("W1", "W1"))}
    assert check_schedule(PACK, out, snap) == []


def test_pending_removal_keeps_its_worker_if_free():
    snap, current = oven_snapshot(set())
    assert oven(repair(PACK, snap, current)) == {(9, ("W1", "W2"))}


def test_pending_removal_waits_for_the_first_free_worker():
    snap, current = oven_snapshot({"C", "D"})  # W1 free at 10, W2 at 11: forced overstay, removal [10, 11) by W1
    out = repair(PACK, snap, current)
    assert oven(out) == {(11, ("W1", "W1"))}
    assert check_schedule(PACK, out, snap) == []
    assert min(a.start for a in out if a.op_id == "mill/setup") >= 11


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize(("s", "a"), [("spt", None), ("mwkr", "least_load"), ("edd", "ect")])
@pytest.mark.parametrize("name", MODELS)
def test_disturbed_execution_with_repair_is_feasible(name, s, a, seed):
    model = MODELS[name]
    ci = compile_instance(model)
    sc = sample_scenario(model, sigma=0.4, seed=seed, q=0.5, max_early=5, max_late=5)
    result = execute(ci, rule_plan(ci, s, a), sc, REPAIR)
    assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}  # durations differ by design


def test_forced_overstay_through_execute_with_repair():
    # one worker, polishing [5, 8) takes 6 (tests/test_forced_overstay.py): at 8, 9 and 10 the repair moves the
    # pending removal to the polishing's expected end (+1 each); every repaired plan passes update_plan's checker;
    # removal realized [11, 12), the oven batch ends at 12, the mill runs follow 3 later
    result = execute(ONE_WORKER, ROWS, SLOW_POLISH, REPAIR)
    got = by_key(result.schedule)
    assert got["L1", "oven"] == got["L2", "oven"] == ("O", 4, 12, ("W1", "W1"))
    assert got["L1", "mill/setup"][1:3] == (12, 13) and got["L2", "mill/removal"][1:3] == (23, 24)
    assert [(d["t"], d["makespan_change"]) for d in result.decisions] == [(8, 1), (9, 1), (10, 1)]
    assert {v.constraint for v in check_schedule(ONE_WORKER, result.schedule)} <= {"C2"}


def test_zero_weight_cycle_stays_unchanged():
    # X and Y start together, each fully covered by prefix and suffix, workers swapped: each is tight only to the
    # other. The passes start from the planned starts of the prefixes, not from 0, so nothing moves without a
    # deviation (from 0, both would left-shift to t)
    data = {"schema_version": "0.7", "name": "cycle0", "machines": ["M1", "M2"], "workers": ["A", "B"], "orders": [
        {"id": k, "operations": [{"id": k.lower(), "step": "s", "options": {m: 20},
                                  "worker": {"prefix": 10, "suffix": 10}}]} for k, m in (("X", "M1"), ("Y", "M2"))
    ]}
    ci = compile_instance(Instance.model_validate(data))
    workers = [[0, 1], [1, 0]]  # X: A [30, 40), B [40, 50); Y: B [30, 40), A [40, 50)
    assert shift_repair(ci, 0, [0, 1], [[0], [1]], [30, 30], [50, 50], [None, None], [None, None], workers) == (
        [30, 30], [50, 50])


def one_worker_with_packaging() -> Instance:
    """The carrier instance with one worker and a packaging released at 6 (2 minutes): the rules plan it into the
    oven run, right before or after its removal, so an overrun of either forces the removal later."""
    data = carriers() | {"workers": ["W1"]}
    data["orders"].append({"id": "P", "release": 6, "operations": [
        {"id": "pack", "step": "pack", "duration": 2, "worker": {"whole": True}}]})
    return Instance.model_validate(data)


def test_sweep_with_forced_overstays(monkeypatch):
    # sweep coverage (protocol 2026-11-09 (32)): the other sweeps never force an overstay. Here rule plans (fifo,
    # mwkr) over 20 seeds and the hand plan of tests/test_forced_overstay.py with slower polishings. Every repaired
    # plan passes update_plan's checker, the realized schedules pass up to C2, and forced overstays occur in both
    import simulation.control.rescheduling as rescheduling

    forced = []

    def counting_repair(ci, snap, plan, breaks=(), **options):
        out = repair_plan(ci, snap, plan, breaks, **options)
        frozen = {(f.order_id, f.op_id): f for f in snap.frozen}
        forced.extend(a for a in out.assignments if (f := frozen.get((a.order_id, a.op_id))) is not None and f.running
                      and None in f.workers and a.end > f.end)
        return out

    monkeypatch.setattr(rescheduling, "repair_plan", counting_repair)
    model = one_worker_with_packaging()
    ci = compile_instance(model)
    for plan in (rule_plan(ci, "fifo", None), rule_plan(ci, "mwkr", "least_load")):
        for seed in range(20):
            sc = sample_scenario(model, sigma=0.4, seed=seed, q=0.5, max_early=5, max_late=5)
            assert {v.constraint for v in check_schedule(ci, execute(ci, plan, sc, REPAIR).schedule)} <= {"C2"}
    rule_cases = len(forced)
    for factor in (1.0, 1.4, 1.7, 2.0, 2.5, 3.0):  # hand plan: the polishing right before the removal, slower
        result = execute(ONE_WORKER, ROWS, scenario(ONE_WORKER, A_polish=factor), REPAIR)
        assert {v.constraint for v in check_schedule(ONE_WORKER, result.schedule)} <= {"C2"}
    assert rule_cases >= 5 and len(forced) > rule_cases
