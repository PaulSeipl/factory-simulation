"""DES with the work calendar: shift window, breaks, overtime (math/13_des.md, math/04_workers.md).

toy-workers (tests/test_workers_checker.py): t = 0 is Monday 08:00; 17:30 = 570, 19:30 = 690, Tuesday 08:00 = 1440,
next Monday 08:00 = 7 * 1440. k1's packaging (20 min, A) is ready at 150 (end of Gegenbetten); a late start
offset moves its start.
"""

import pytest
from test_des_workers import TOY, by_key, scenario
from test_workers_checker import BREAKS, CI, plan

from simulation.check.feasibility import check_schedule
from simulation.model.schedule import Break
from simulation.sim.des import replay
from simulation.sim.scenario import sample_scenario

DAY = 1440


def pack_k1(**changes):
    result = replay(CI, plan(), scenario(CI, **changes), breaks=BREAKS)
    return by_key(result.schedule)["k1", "pack"][1:3], result


def test_planned_breaks_are_taken_as_planned():
    assert replay(CI, plan(), breaks=BREAKS).breaks == BREAKS


def test_late_share_that_fits_runs_into_overtime():
    # ready at 150, 410 minutes late: starts 17:20 (560), ends 17:40 (580): 10 minutes overtime, allowed
    assert pack_k1(k1_pack=(1.0, 410))[0] == (560, 580)


def test_share_that_does_not_fit_waits_for_the_next_working_day():
    # would start 19:20 (680) and end 19:40 > 19:30: waits until Tuesday 08:00
    assert pack_k1(k1_pack=(1.0, 530))[0] == (DAY, DAY + 20)


def test_friday_evening_waits_until_monday():
    friday_1920 = 4 * DAY + 680
    assert pack_k1(k1_pack=(1.0, friday_1920 - 150))[0] == (7 * DAY, 7 * DAY + 20)


def test_overrun_is_finished_not_preempted():
    # starts 19:00 (660), planned 20 minutes fit; it takes 40 and ends 19:40, past 19:30
    window, result = pack_k1(k1_pack=(2.0, 510))
    assert window == (660, 700)
    assert [v.constraint for v in check_schedule(CI, result.schedule, breaks=result.breaks)
            if v.constraint != "C2"] == ["C13"]


def test_break_is_postponed_while_the_worker_is_busy():
    # Gegenbetten work 30 -> 200 minutes: A works [60, 260), so A's break moves from 240 to 260; the rest [260, 320)
    # needs nobody; packaging [320, 340). B breaks as planned.
    result = replay(CI, plan(), scenario(CI, k1_gb=20 / 3), breaks=BREAKS)
    got = by_key(result.schedule)
    assert (got["k1", "gb"][1:3], got["k1", "pack"][1:3]) == ((60, 320), (320, 340))
    assert result.breaks == (Break(worker="A", start=260), Break(worker="B", start=240))


def test_no_share_starts_while_a_break_is_due():
    # k2's packaging 245 minutes late: ready at 0, starts at 245 during A's break [240, 300) -> waits until 300
    got = by_key(replay(CI, plan(), scenario(CI, k2_pack=(1.0, 245)), breaks=BREAKS).schedule)
    assert got["k2", "pack"][1:3] == (300, 320)


@pytest.mark.parametrize("seed", range(10))
def test_disturbed_runs_pass_the_checker(seed):
    """Only the deviations the DES records may remain: realized durations (C2), overruns past 19:30 (C13) and
    breaks postponed beyond the window (C14)."""
    result = replay(CI, plan(), sample_scenario(TOY, 0.5, seed, q=0.3, max_late=120), breaks=BREAKS)
    for v in check_schedule(CI, result.schedule, breaks=result.breaks):
        assert v.constraint == "C2" or "outside the shift window" in v.message \
            or "outside the break window" in v.message, v
