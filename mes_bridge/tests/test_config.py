"""The scheduler's configuration (task 3.3b, decision 9)."""

import json

import pytest
from pydantic import ValidationError

from mes_bridge.config import SchedulerConfig


def test_without_a_file_the_defaults_apply():
    c = SchedulerConfig.load(None)
    assert (c.solver.sequencing, c.safety_poll_minutes) == ("spt", 5)
    p = c.rescheduling_policy()
    assert p.planner is not None and p.period is None and p.change_budget is None


def test_a_file_sets_the_solver_and_the_policy(tmp_path):
    f = tmp_path / "scheduler.json"
    f.write_text(
        json.dumps(
            {
                "solver": {"sequencing": "edd", "assignment": "least_load"},
                "policy": {"max_shift": 60, "period": 480, "change_budget": 3},
                "safety_poll_minutes": 2,
            }
        ),
        encoding="utf-8",
    )
    c = SchedulerConfig.load(f)
    p = c.rescheduling_policy()
    assert (p.max_shift, p.period, p.change_budget) == (60, 480, 3)
    assert c.safety_poll_minutes == 2 and c.solver.sequencing == "edd"


@pytest.mark.parametrize(
    "body",
    [
        {"solver": {"sequencing": "fastest"}},  # unknown rule
        {"solver": {"assignment": "nearest"}},  # unknown assignment rule
        {"policy": {"period": 0}},  # not positive
        {"policy": {"change_budget": -1}},
        {"safety_poll_minutes": 0},
        {"horizon": 60},  # unknown key: fails loudly
    ],
)
def test_an_invalid_configuration_is_rejected(body):
    with pytest.raises(ValidationError):
        SchedulerConfig.model_validate(body)


def test_the_configured_rule_plans_the_one_shot(tmp_path):
    from pathlib import Path
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from mes_bridge.api import ProblemOut
    from mes_bridge.instance import epoch_of
    from mes_bridge.once import solve

    raw = (Path(__file__).parent / "data" / "problem_printing.json").read_text(encoding="utf-8")
    p = ProblemOut.model_validate_json(raw)
    epoch = epoch_of(p.as_of, ZoneInfo("Europe/Berlin"))
    for rule in ("spt", "fifo", "edd"):
        out = solve(
            p,
            epoch=epoch,
            solved_at=datetime.fromisoformat(p.as_of.isoformat()),
            config=SchedulerConfig.model_validate({"solver": {"sequencing": rule}}),
        )
        assert out.violations == [] and out.schedule is not None, rule
