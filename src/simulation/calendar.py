"""Work calendar arithmetic on integer minutes (math/04_workers.md, section 2).

Works on any object with the fields of `model.instance.Calendar` (the Pydantic model, or a compiled copy later).
Day d is counted from Monday 00:00 of the week that contains t = 0; `origin` is the minute of that week at t = 0.
"""

from dataclasses import dataclass

DAY = 1440
WEEK = 7 * DAY


@dataclass(frozen=True, slots=True)
class WeekCalendar:
    """Compiled copy of `model.instance.Calendar` (no Pydantic in the hot path); same fields, validated there."""

    origin: int
    shift_start: int
    shift_end: int
    break_earliest: int
    break_latest: int
    break_length: int
    max_overtime: int
    cutoff: int
    working_days: tuple[int, ...]


def minute_of_day(cal, t: int) -> int:
    return (cal.origin + t) % DAY


def day_index(cal, t: int) -> int:
    return (cal.origin + t) // DAY


def day_start(cal, day: int) -> int:
    """t of 00:00 on that day (negative for day 0 unless origin is 0)."""
    return day * DAY - cal.origin


def is_working_day(cal, day: int) -> bool:
    return day % 7 in cal.working_days


def cutoffs(cal, until: int) -> list[int]:
    """Shipping cutoffs c with 0 <= c <= until, ascending: `cutoff` minute of every working day."""
    return [
        c for d in range(day_index(cal, 0), day_index(cal, until) + 1)
        if is_working_day(cal, d) and 0 <= (c := day_start(cal, d) + cal.cutoff) <= until
    ]


def next_cutoff(cal, t: int) -> int:
    """Smallest cutoff >= t (validation guarantees a working day in every week)."""
    return next(c for c in cutoffs(cal, t + WEEK) if c >= t)


def next_start(cal, t: int, length: int, latest: int) -> int:
    """Earliest s >= t at which a share of `length` minutes lies within one working day, in [shift_start, latest]
    (minutes of the day; shift_end for no overtime) and outside the break [break_earliest, + break_length).
    The break is placed at its earliest start, as the dispatching rule does (math/11_dispatching-rules.md)."""
    parts = ((cal.shift_start, cal.break_earliest), (cal.break_earliest + cal.break_length, latest))
    if all(length > b - a for a, b in parts):
        raise ValueError(f"share of {length} minutes longer than both parts of the shift {parts}")
    for d in range(day_index(cal, t), day_index(cal, t) + 8):  # every week has a working day
        if is_working_day(cal, d):
            for a, b in parts:
                s = max(t, day_start(cal, d) + a)
                if s + length <= day_start(cal, d) + b:
                    return s
    raise AssertionError("unreachable: a working day within a week has room for the share")


def days_late(cal, due: int, end: int) -> int:
    """Missed shipping cutoffs |{c : due <= c < end}|; `due` is itself a cutoff."""
    return sum(c >= due for c in cutoffs(cal, end - 1)) if end > due else 0
