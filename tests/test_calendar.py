"""Work calendar: time arithmetic and validation (math/04_workers.md, section 2).

t = 0 is Monday 08:00 (origin 480); Monday 12:00 is t = 240, Tuesday 00:00 is t = 960.
"""

import pytest
from pydantic import ValidationError

from simulation.calendar import (
    cutoffs,
    day_index,
    day_start,
    days_late,
    is_working_day,
    minute_of_day,
    next_cutoff,
    next_start,
)
from simulation.model.instance import Calendar, Instance

DAY = 1440
CAL = Calendar()


def test_origin_monday_0800():
    assert minute_of_day(CAL, 0) == 480
    assert day_index(CAL, 0) == 0
    assert day_index(CAL, 959) == 0
    assert day_index(CAL, 960) == 1
    assert day_start(CAL, 1) == 960


def test_weekend_is_not_a_working_day():
    assert [is_working_day(CAL, d) for d in range(8)] == [True] * 5 + [False, False, True]


def test_cutoffs_skip_weekend():
    assert cutoffs(CAL, 8 * DAY) == [240 + d * DAY for d in (0, 1, 2, 3, 4, 7)]


def test_cutoffs_include_the_limit():
    assert cutoffs(CAL, 240) == [240]
    assert cutoffs(CAL, 239) == []


def test_next_cutoff():
    assert next_cutoff(CAL, 0) == 240
    assert next_cutoff(CAL, 240) == 240
    assert next_cutoff(CAL, 241) == 240 + DAY
    assert next_cutoff(CAL, 4 * DAY + 241) == 7 * DAY + 240  # Friday 12:01 -> Monday 12:00


def test_days_late():
    assert [days_late(CAL, 240, end) for end in (100, 240, 241, 240 + DAY, 241 + DAY)] == [0, 0, 1, 1, 2]


def test_weekend_counts_one_day():
    friday = 4 * DAY + 240
    assert days_late(CAL, friday, 7 * DAY + 120) == 1  # shipped Monday 10:00


def test_other_origin_and_working_days():
    cal = Calendar(origin=0, working_days=(0, 2))  # t = 0 is Monday 00:00; Monday and Wednesday only
    assert cutoffs(cal, 3 * DAY) == [720, 2 * DAY + 720]


# --- next_start: earliest start of a share inside the shift, outside the break (no overtime: latest = 17:30) ----

SHIFT_END, WITH_OVERTIME = 1050, 1170  # minutes of the day: 17:30, 19:30


@pytest.mark.parametrize(("t", "length", "latest", "expected"), [
    (10, 60, SHIFT_END, 10),  # inside the morning
    (180, 60, SHIFT_END, 180),  # ends exactly at the break start 12:00 (240)
    (200, 60, SHIFT_END, 300),  # would cross 12:00-13:00: after the break
    (250, 30, SHIFT_END, 300),  # starts during the break: after it
    (540, 60, SHIFT_END, DAY),  # 17:00 + 60 > 17:30: Tuesday 08:00
    (540, 60, WITH_OVERTIME, 540),  # with overtime it fits before 19:30
    (4 * DAY + 540, 60, SHIFT_END, 7 * DAY),  # Friday 17:00 -> Monday 08:00
    (5 * DAY + 120, 10, SHIFT_END, 7 * DAY),  # Saturday 10:00 -> Monday 08:00
    (DAY - 40, 10, SHIFT_END, DAY),  # Tuesday 07:20 -> 08:00
    (0, 300, WITH_OVERTIME, 300),  # 5 hours: only the afternoon until 19:30 is long enough
], ids=["morning", "touching-break", "past-break", "in-break", "next-day", "overtime", "friday", "weekend",
        "before-shift", "long-afternoon"])
def test_next_start(t, length, latest, expected):
    assert next_start(CAL, t, length, latest) == expected


def test_next_start_rejects_a_share_longer_than_both_shift_parts():
    # morning 08:00-12:00 (240), afternoon 13:00-17:30 (270): 300 minutes fit nowhere without overtime
    with pytest.raises(ValueError, match="longer than"):
        next_start(CAL, 0, 300, SHIFT_END)


# --- validation: one negative test per rule -------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"shift_start": 730},  # shift start after the break window starts
        {"break_earliest": 790},  # break window inverted (earliest > latest)
        {"break_latest": 1000},  # break does not end inside the shift
        {"shift_end": 1400},  # shift end plus overtime beyond midnight
        {"cutoff": 1440},
        {"working_days": ()},
        {"working_days": (0, 0)},
        {"working_days": (7,)},
        {"origin": 7 * DAY},
        {"shift_start": -1},
    ],
)
def test_invalid_calendar(fields):
    with pytest.raises(ValidationError):
        Calendar(**fields)


def _instance(**extra):
    return {
        "schema_version": "0.6", "name": "cal", "machines": ["M"],
        "orders": [{"id": "k", "due_date": 240, "operations": [{"id": "1", "step": "s", "options": {"M": 5}}]}],
        "calendar": {}, **extra,
    }


def test_calendar_instance_loads():
    assert Instance.model_validate(_instance()).calendar == CAL


def test_calendar_needs_minutes():
    with pytest.raises(ValidationError, match="minutes"):
        Instance.model_validate(_instance(time_unit="h"))


def test_due_date_must_be_a_cutoff():
    data = _instance()
    data["orders"][0]["due_date"] = 241
    with pytest.raises(ValidationError, match="cutoff"):
        Instance.model_validate(data)
