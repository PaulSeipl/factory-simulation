"""Experiment runner (src/simulation/experiment.py): one run, its CSV row and its plan history."""

import json
from pathlib import Path

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
    history = [json.loads(line) for line in (tmp_path / "tiny" / "plans" / "cpsat-1.jsonl").read_text().splitlines()]
    assert history[0]["type"] == "START" and any("arrival" in h["triggers"] for h in history)


def test_same_seed_same_row(tmp_path):
    a, b = (run_one(config(), "rule", 1, tmp_path) for _ in range(2))
    for key in ("wall_time", "planner_time", "commit"):
        a.pop(key), b.pop(key)
    assert a == b
