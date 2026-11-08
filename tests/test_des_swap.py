"""Swap rule in the DES (spec §6, rule 7; math/13_des.md): when a share is due and its planned worker is busy, a
qualified worker who is free now and whose next planned share starts no earlier than now + the planned share
length takes it; tie-break: most room before that next share.

toy-workers (tests/test_workers_checker.py): A and B; Gegenbetten only A; k1 packaging ready at 150.
"""

from test_des_workers import by_key, polish_instance, scenario
from test_worker_compile import CARRIERS
from test_workers_checker import BREAKS, CI, carrier_plan, plan

from simulation.check.feasibility import check_schedule
from simulation.sim.des import replay


def swaps(result):
    return [(r["t"], r["order_id"], r["op_id"], r["planned"], r["actual"]) for r in result.log if r["type"] == "SWAP"]


def run(rows, **changes):
    return replay(CI, rows, scenario(CI, **changes), breaks=BREAKS)


def test_free_worker_takes_the_task_of_a_late_one():
    # A: Gegenbetten prefix [60, 90), k2 packaging [100, 120). Prefix takes 60 (factor 2): A busy until 120;
    # at 100 B is free with nothing planned afterwards -> B packs k2 [100, 120)
    result = run(plan(k2_pack=(None, 100, 120, ("A",))), k1_gb=2.0)
    assert by_key(result.schedule)["k2", "pack"] == (None, 100, 120, ("B",))
    assert swaps(result) == [(100, "k2", "pack", "A", "B")]
    assert {v.constraint for v in check_schedule(CI, result.schedule, breaks=result.breaks)} <= {"C2"}


def test_no_swap_if_the_next_task_of_the_free_worker_comes_too_early():
    # as above, but k2 packaging at [135, 155) and B packs k1 at 150: 150 < 135 + 20, so B may not take it;
    # A (prefix 105 minutes, busy until 165) packs k2 [165, 185)
    result = run(plan(k2_pack=(None, 135, 155, ("A",)), k1_pack=(None, 150, 170, ("B",))), k1_gb=3.5)
    assert by_key(result.schedule)["k2", "pack"] == (None, 165, 185, ("A",))
    assert swaps(result) == []


def test_next_task_exactly_at_the_end_still_allows_the_swap():
    # B's next share at 150 = 130 + 20: fits exactly
    result = run(plan(k2_pack=(None, 130, 150, ("A",)), k1_pack=(None, 150, 170, ("B",))), k1_gb=3.5)
    assert by_key(result.schedule)["k2", "pack"] == (None, 130, 150, ("B",))


def test_qualification_is_respected():
    # k2 packaging [40, 60) by A takes 40: A busy until 80; Gegenbetten (only A) waits instead of going to B
    result = run(plan(k2_pack=(None, 40, 60, ("A",))), k2_pack=2.0)
    assert by_key(result.schedule)["k1", "gb"] == (None, 80, 170, ("A",))
    assert swaps(result) == []


def test_swap_prevents_an_oven_overstay():
    # oven loaded by W2 [4, 5), unloaded by W1 at [8, 9); W1 polishes [4, 8), which takes 6 (until 10). W2 is free
    # and next needed at 15: W2 unloads at 8 (no overstay) and also sets up L1's mill run at 9
    ci = polish_instance()
    rows = [*carrier_plan((("W2", "W1"), ("W2", "W1"))),
            *[a.model_copy(update={"order_id": "A", "op_id": "polish", "machine": None, "start": 4, "end": 8,
                                   "workers": ("W1",)}) for a in carrier_plan()[:1]]]
    result = replay(ci, rows, scenario(ci, A_polish=1.5))
    got = by_key(result.schedule)
    assert got["L1", "oven"] == got["L2", "oven"] == ("O", 4, 9, ("W2", "W2"))
    assert got["L1", "mill/setup"] == ("M", 9, 10, ("W2",))
    assert [s[:3] for s in swaps(result)] == [(8, "L1", "oven"), (9, "L1", "mill/setup")]
    assert [r for r in result.log if r["type"] == "OVERSTAY"] == []
    assert {v.constraint for v in check_schedule(ci, result.schedule)} <= {"C2"}


def test_no_swap_without_disturbance():
    assert swaps(replay(CI, plan(), breaks=BREAKS)) == [] and swaps(replay(CARRIERS, carrier_plan())) == []


def test_current_plan_shows_the_actual_worker():
    from simulation.sim.des import Simulation

    sim = Simulation(CI, plan(k2_pack=(None, 100, 120, ("A",))), scenario(CI, k1_gb=2.0), BREAKS)
    sim.run(until=100)
    assert next(a for a in sim.current_plan() if a.op_id == "pack" and a.order_id == "k2").workers == ("B",)
