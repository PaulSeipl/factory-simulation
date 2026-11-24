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
        {"solver": {"kind": "tabu"}},  # unknown solver
        {"solver": {"kind": "cpsat", "time_limit": 0}},  # not positive
        {"solver": {"kind": "cpsat", "objective": "profit"}},  # unknown objective
        {"solver": {"kind": "ga", "buffer": 1440}},  # the cutoff slack needs a buffer under a day
        {"solver": {"kind": "ga", "seed": -1}},
        {"horizon": 60},  # unknown key: fails loudly
        {"thorough": {"kind": "cpsat", "time_limit": 0}},  # the thorough profile is checked like the fast one
        {"thorough": {"sequencing": "fastest"}},
    ],
)
def test_an_invalid_configuration_is_rejected(body):
    with pytest.raises(ValidationError):
        SchedulerConfig.model_validate(body)


def test_two_profiles_fast_for_the_automatic_path_thorough_on_request():
    """Task 7.2: `solver` is the automatic path, `thorough` only the requested one; without it, `solver` does both."""
    c = SchedulerConfig.model_validate(
        {"solver": {"kind": "rule", "sequencing": "edd"}, "thorough": {"kind": "cpsat", "time_limit": 60}}
    )
    assert c.rescheduling_policy().planner.__qualname__ != "cpsat_planner"
    assert c.thorough_planner().__qualname__ == "cpsat_planner"
    alone = SchedulerConfig.model_validate({"solver": {"kind": "ga", "time_limit": 5}})
    assert alone.thorough is None and alone.thorough_planner().__qualname__ == "ga_planner"


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


def _solve_recording(name: str, solver: dict, edit=None):
    from pathlib import Path
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from mes_bridge.api import ProblemOut
    from mes_bridge.instance import epoch_of
    from mes_bridge.once import solve

    raw = json.loads((Path(__file__).parent / "data" / name).read_text(encoding="utf-8"))
    if edit:
        edit(raw)
    p = ProblemOut.model_validate(raw)
    return solve(
        p,
        epoch=epoch_of(p.as_of, ZoneInfo("Europe/Berlin")),
        solved_at=datetime.fromisoformat(p.as_of.isoformat()),
        config=SchedulerConfig.model_validate({"solver": solver}),
    )


@pytest.mark.parametrize("kind", ["cpsat", "ga"])
@pytest.mark.parametrize("objective", ["worker", "makespan"])
@pytest.mark.parametrize("name", ["problem_printing.json", "problem_blank.json"])
def test_cpsat_and_the_ga_plan_a_recording_feasibly(kind, objective, name):
    """Task 5.1: both solvers from the config, on recordings with workers and a calendar (no due dates)."""
    out = _solve_recording(name, {"kind": kind, "objective": objective, "time_limit": 3})
    assert out.violations == [] and out.schedule is not None and out.schedule.steps
    assert out.schedule.breaks  # one per worker and day, placed by the solver


@pytest.mark.parametrize("kind", ["cpsat", "ga"])
def test_the_worker_objective_takes_the_due_dates_when_there_are_some(kind):
    def due(raw):
        for o in raw["instance"]["orders"]:
            o["due_date"] = "2026-12-04"

    out = _solve_recording("problem_blank.json", {"kind": kind, "time_limit": 3}, due)
    assert out.violations == [] and out.schedule is not None


def test_the_objective_drops_the_due_date_levels_without_due_dates():
    from types import SimpleNamespace

    from simulation.objectives import MAKESPAN

    c = SchedulerConfig.model_validate({"solver": {"kind": "cpsat"}}).solver
    none, some = SimpleNamespace(due_date=(None, None)), SimpleNamespace(due_date=(None, 3000))
    assert [lv.name for lv in c.objective_for(none).levels] == ["overtime", "break_penalty", "active_makespan"]
    assert c.objective_for(some).levels[0].name == "total_tardiness"
    m = SchedulerConfig.model_validate({"solver": {"kind": "cpsat", "objective": "makespan"}}).solver
    assert m.objective_for(none) is MAKESPAN


def test_cpsat_without_a_plan_falls_back_to_the_rule():
    """The recorded data prep runs from 10:00 to past the day's end (left open), over the whole break window: the
    thesis model postpones the owed break into the night (C14^f) and is infeasible; the rule plans instead."""
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from simulation.check.feasibility import check_schedule
    from simulation.model.compiled import compile_instance

    from mes_bridge.api import ProblemOut
    from mes_bridge.instance import build_instance, epoch_of
    from mes_bridge.state import build_snapshot, id_map

    p = ProblemOut.model_validate_json(
        (Path(__file__).parent / "data" / "problem_mill_prep.json").read_text(encoding="utf-8")
    )
    epoch = epoch_of(p.as_of, ZoneInfo("Europe/Berlin"))
    ci = compile_instance(build_instance(p, epoch=epoch))
    snap = build_snapshot(p, ci, id_map(p, ci), epoch=epoch)
    planner = SchedulerConfig.model_validate({"solver": {"kind": "cpsat", "time_limit": 3}}).solver.planner()
    plan = planner(ci, snap, [])
    assert len(plan.assignments) == ci.n_ops
    assert check_schedule(ci, plan.assignments, snapshot=snap, breaks=plan.breaks) == []
    assert "INFEASIBLE" in planner.last["fallback"]


def test_the_policy_runs_the_configured_solver():
    c = SchedulerConfig.model_validate({"solver": {"kind": "cpsat", "time_limit": 2}})
    assert c.rescheduling_policy().planner.__qualname__ == "cpsat_planner"


@pytest.mark.parametrize(
    ("solver", "minutes"),
    [
        ({"kind": "rule"}, 0),
        ({"kind": "cpsat", "time_limit": 10}, 1),
        ({"kind": "ga", "time_limit": 60}, 1),
        ({"kind": "cpsat", "time_limit": 61}, 2),
    ],
)
def test_the_frozen_horizon_is_the_time_limit_in_whole_minutes(solver, minutes):
    assert SchedulerConfig.model_validate({"solver": solver}).solver.horizon_minutes == minutes
