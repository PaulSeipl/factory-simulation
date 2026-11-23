"""Experiment runner (src/simulation/experiment.py): one run, its CSV row and its plan history."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from simulation.carrier_generator import CarrierGeneratorParams
from simulation.experiment import ExperimentConfig, run_one
from simulation.io.json_loader import read_model

BASE = read_model(Path(__file__).parents[1] / "data" / "generator" / "dental-carriers-workers.json",
                  CarrierGeneratorParams).model_dump(mode="json")  # the route reference resolved


def config(**changes) -> ExperimentConfig:
    arrivals = {"seed": 0, "base": BASE | {"release_range": [0, 0], "due_date_tightness": []},
                "rates": {"0": 3.0, "1": 3.0}, "window_days": 2, "backlog": 1}
    return ExperimentConfig.model_validate({"name": "tiny", "arrivals": arrivals, "seeds": [1],
                                            "policies": {"rule": {"planner": "rule"}, "cpsat": {"planner": "cpsat"}}}
                                           | changes)


def test_one_run_writes_its_row_and_plan_history(tmp_path):
    row = run_one(config(), "cpsat", 1, tmp_path)
    assert row["policy"] == "cpsat" and row["config_hash"] == config().digest()
    assert row["arrival_reschedulings"] >= 1 and "tardy_days" in row and "overtime" in row
    assert row["start_wall_limited"] in (True, False) and 0 <= row["wall_limited_reschedulings"] <= row["reschedulings"]
    history = [json.loads(line) for line in (tmp_path / "tiny" / "plans" / "cpsat-1.jsonl").read_text().splitlines()]
    assert history[0]["type"] == "START" and any("arrival" in h["triggers"] for h in history)


def test_same_seed_same_row(tmp_path):
    a, b = (run_one(config(), "rule", 1, tmp_path) for _ in range(2))
    for key in ("wall_time", "planner_time", "commit"):
        a.pop(key), b.pop(key)
    assert a == b


def test_ga_policy_runs_and_repeats(tmp_path):
    ga = config(policies={"ga": {"planner": "ga", "generations": 1}})
    a, b = (run_one(ga, "ga", 1, tmp_path) for _ in range(2))
    assert a["reschedulings"] >= 1
    for key in ("wall_time", "planner_time", "commit"):
        a.pop(key), b.pop(key)
    assert a == b


def test_mcts_policy_runs_and_repeats(tmp_path):
    mcts = config(policies={"mcts": {"planner": "mcts", "iterations": 1}})
    a, b = (run_one(mcts, "mcts", 1, tmp_path) for _ in range(2))
    assert a["reschedulings"] >= 1
    for key in ("wall_time", "planner_time", "commit"):
        a.pop(key), b.pop(key)
    assert a == b


@pytest.mark.parametrize("policy", [{"planner": "ga"}, {"planner": "rule", "generations": 5},
                                    {"planner": "ga", "generations": 0}, {"planner": "mcts"},
                                    {"planner": "ga", "generations": 5, "iterations": 5},
                                    {"planner": "mcts", "iterations": 0}])
def test_search_limits_only_and_always_for_their_planner(policy):
    with pytest.raises(ValidationError):
        config(policies={"p": policy})


def test_cli_task_by_slurm_index_then_merge(tmp_path, monkeypatch, capsys):
    import csv

    import pytest

    from simulation.experiment import main

    path = tmp_path / "tiny.json"
    path.write_text(config().model_dump_json(), encoding="utf-8")
    out = tmp_path / "results"
    main(["list", str(path)])
    assert len(capsys.readouterr().out.splitlines()) == 2  # rule-1, cpsat-1
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "1")
    main(["task", str(path), "--out", str(out)])
    assert (out / "tiny" / "rows" / "cpsat-1.json").is_file()
    main(["merge", str(path), "--out", str(out)])
    assert "1 runs missing" in capsys.readouterr().err  # rule-1 not run yet: CSV with the run that exists
    main(["task", "--index", "0", str(path), "--out", str(out)])
    main(["merge", str(path), "--out", str(out)])
    with (out / "tiny.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["policy"] for r in rows] == ["rule", "cpsat"] and rows[0]["host"]
    # the configuration changes: its old rows are not merged
    path.write_text(config(sigma=0.3).model_dump_json(), encoding="utf-8")
    main(["merge", str(path), "--out", str(out)])
    assert "2 runs missing or from another configuration" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="outside 0..1"):
        main(["task", "--index", "2", str(path), "--out", str(out)])


def test_cli_run_continues_missing_runs_of_this_host(tmp_path, capsys):
    import pytest

    from simulation.experiment import main

    path = tmp_path / "tiny.json"
    path.write_text(config().model_dump_json(), encoding="utf-8")
    out = tmp_path / "results"
    main(["run", str(path), "--out", str(out), "--processes", "1", "--policy", "rule"])
    capsys.readouterr()
    main(["list", "--missing", str(path), "--out", str(out)])
    assert capsys.readouterr().out.split() == ["1", "tiny", "cpsat", "1"]  # the index of the full list
    rule = out / "tiny" / "rows" / "rule-1.json"
    row = json.loads(rule.read_text(encoding="utf-8"))
    rule.write_text(json.dumps(row | {"host": "other-machine"}), encoding="utf-8")
    main(["list", "--missing", "--seed", "1", str(path), "--out", str(out)])
    assert len(capsys.readouterr().out.splitlines()) == 2  # a row of another host does not count
    main(["run", str(path), "--out", str(out), "--processes", "1"])
    assert "2 runs to do" in capsys.readouterr().err
    main(["run", str(path), "--out", str(out), "--processes", "1"])
    assert "0 runs to do" in capsys.readouterr().err
    main(["run", str(path), "--out", str(out), "--processes", "1", "--restart", "--policy", "rule"])
    assert "1 runs to do" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="not in these configurations: hindsight 7"):
        main(["list", str(path), "--policy", "hindsight", "--seed", "7"])


def test_cli_unknown_configuration_rejected():
    import pytest

    from simulation.experiment import main

    with pytest.raises(SystemExit, match="no configuration"):
        main(["list", "does-not-exist"])


@pytest.mark.parametrize("policy", [
    {"planner": "rule", "start": "ga"},  # GA start without generations
    {"planner": "rule", "robust": "expected", "n_scenarios": 2},  # robust without the GA
    {"planner": "ga", "generations": 1, "robust": "buffer", "alpha": 0.8},  # buffer needs a GA start plan
    {"planner": "ga", "generations": 1, "robust": "expected"},  # expected without n_scenarios
    {"planner": "ga", "generations": 1, "n_scenarios": 2},  # n_scenarios without expected
    {"planner": "rule", "start": "ga", "generations": 1, "robust": "buffer"},  # buffer without alpha
    {"planner": "rule", "start": "ga", "generations": 1, "alpha": 0.8},  # alpha without buffer
    {"planner": "rule", "start": "ga", "generations": 1, "robust": "buffer", "alpha": 1.0},  # alpha outside (0, 1)
])
def test_robust_settings_rejected(policy):
    with pytest.raises(ValidationError):
        config(policies={"p": policy})


def test_existing_configurations_keep_their_hash():
    # the new fields are left out of the digest while unset (start "cpsat"): stored result rows stay valid
    plain = config(policies={"p": {"planner": "rule"}})
    explicit = config(policies={"p": {"planner": "rule", "start": "cpsat"}})
    assert plain.digest() == explicit.digest() != config(policies={"p": {"planner": "rule", "start": "ga",
                                                                         "generations": 1}}).digest()


def test_expected_ga_start_and_rescheduling_run_and_repeat(tmp_path):
    robust = config(policies={"exp": {"planner": "ga", "generations": 1, "start": "ga", "robust": "expected",
                                      "n_scenarios": 2}})
    a, b = (run_one(robust, "exp", 1, tmp_path) for _ in range(2))
    assert a["start_status"] == "GA" and a["reschedulings"] >= 1
    for key in ("wall_time", "planner_time", "commit"):
        a.pop(key), b.pop(key)
    assert a == b


def test_buffered_ga_start_runs(tmp_path):
    buffered = config(policies={"buf": {"planner": "rule", "start": "ga", "generations": 1, "robust": "buffer",
                                        "alpha": 0.8}})
    row = run_one(buffered, "buf", 1, tmp_path)
    assert row["start_status"] == "GA" and row["planned_makespan"] > 0
