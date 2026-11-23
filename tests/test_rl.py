"""Learned dispatching policy: network, plans, storage without pickle, training (math/16_rl.md)."""

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from test_dispatch_choose import INSTANCES

from simulation.carrier_generator import CarrierGeneratorParams
from simulation.check.feasibility import check_schedule
from simulation.io.json_loader import read_model
from simulation.objectives import MAKESPAN
from simulation.planners.rl import Policy, load_policy, rl_plan, save_policy
from simulation.rl_train import BASE, train
from simulation.sim.des import replay


def policy(seed: int = 0) -> Policy:
    torch.manual_seed(seed)
    return Policy()


@pytest.mark.parametrize("name", list(INSTANCES))
def test_greedy_plan_is_feasible_repeats_and_replays(name):
    ci, p = INSTANCES[name], policy()
    plan = rl_plan(ci, p)
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
    assert rl_plan(ci, p) == plan
    # zero disturbance: the DES realizes the plan exactly
    realized = replay(ci, plan.assignments, breaks=plan.breaks).schedule
    assert sorted((a.order_id, a.op_id, a.machine, a.start, a.end) for a in realized) == sorted(
        (a.order_id, a.op_id, a.machine, a.start, a.end) for a in plan.assignments)


def test_sampled_plan_records_one_log_probability_per_decision():
    ci, p = INSTANCES["dental-carriers-workers"], policy()
    decisions = []

    def counting(eligible, _state):
        decisions.append(len(eligible) > 1)
        return 0

    log_probs: list = []
    plan = rl_plan(ci, p, generator=torch.Generator().manual_seed(1), log_probs=log_probs)
    assert check_schedule(ci, plan.assignments, breaks=plan.breaks) == []
    assert log_probs and all(lp.requires_grad and lp <= 0 for lp in log_probs)
    torch.stack(log_probs).sum().backward()  # gradients reach every layer
    assert all(w.grad is not None and torch.isfinite(w.grad).all() for w in p.parameters())


def test_save_and_load_without_pickle(tmp_path):
    p = policy(3)
    save_policy(p, tmp_path / "pol", {"note": "test"})
    with np.load(tmp_path / "pol.npz", allow_pickle=False) as weights:  # plain arrays only
        assert set(weights.files) == set(p.state_dict())
    q = load_policy(tmp_path / "pol")
    x = torch.randn(7, p.net[0].in_features)
    assert torch.equal(p(x), q(x))
    assert json.loads((tmp_path / "pol.json").read_text())["note"] == "test"


def test_load_refuses_other_features(tmp_path):
    save_policy(policy(), tmp_path / "pol", {})
    meta = json.loads((tmp_path / "pol.json").read_text())
    (tmp_path / "pol.json").write_text(json.dumps(meta | {"feature_version": 0}))
    with pytest.raises(ValueError, match="features version 0"):
        load_policy(tmp_path / "pol")


def test_training_runs_repeats_and_learns_something():
    base = read_model(BASE, CarrierGeneratorParams)
    kwargs = {"iterations": 3, "samples": 3, "lr": 1e-2, "orders": (4, 6), "seed": 5, "validate_every": 3,
              "validation_orders": 5}
    a, log = train(base, MAKESPAN, **kwargs)
    b, _ = train(base, MAKESPAN, **kwargs)
    assert all(torch.equal(x, y) for x, y in zip(a.state_dict().values(), b.state_dict().values(), strict=True))
    assert len(log) == 3 and log[-1]["validation_ratio"] > 0
    assert all(np.isfinite(r["loss"]) for r in log)
    assert not all(torch.equal(x, y) for x, y in zip(a.state_dict().values(), policy(5).state_dict().values(),
                                                    strict=True))  # the steps moved the weights


def test_cli_writes_weights_record_and_log(tmp_path):
    from simulation.rl_train import main

    main(["--out", str(tmp_path / "m"), "--iterations", "2", "--samples", "2", "--orders", "4", "5",
          "--validation-orders", "4", "--validate-every", "1"])
    record = json.loads((tmp_path / "m.json").read_text())
    assert record["feature_version"] == 1 and len(record["log"]) == 2 and record["train_seed0"] == 10_000
    assert (tmp_path / "m.npz").exists() and (tmp_path / "m.csv").read_text().startswith("iteration,")
    assert load_policy(tmp_path / "m") is not None


def test_training_and_validation_seeds_miss_the_evaluation_instances():
    from simulation.rl_train import TRAIN_SEED0, VALIDATION_SEEDS

    seeds = {json.loads(Path(f).read_text())["seed"] for f in (
        BASE, BASE.parent / "dental-carriers-example.json")}
    assert seeds.isdisjoint(VALIDATION_SEEDS) and all(s < TRAIN_SEED0 for s in seeds)


def test_training_on_one_instance_finds_the_optimum_the_rules_miss():
    # toy-dag-3x4: every rule plan ends at 12, the optimum 11 is a non-delay plan (test_mcts). Trained on this one
    # instance (one fixed training instance, as instance-by-instance training), the greedy policy reaches 11: the
    # gradient steps learn, independent of the generator
    from test_mcts import best_rule, toy

    import simulation.rl_train as rl_train

    ci = toy("toy-dag-3x4")
    assert best_rule(ci) == 12
    original = rl_train.instance
    rl_train.instance = lambda *_args: ci
    try:
        trained, _ = rl_train.train(None, MAKESPAN, iterations=150, samples=16, lr=1e-2, orders=(1, 1), seed=0,
                                    validate_every=1000, validation_orders=1)
    finally:
        rl_train.instance = original
    assert MAKESPAN.evaluate(ci, rl_plan(ci, trained).assignments) == 11
