"""Train the learned dispatching policy with REINFORCE (math/16_rl.md §3).

    uv run python -m simulation.rl_train --out models/rl-makespan [--iterations 300] [--samples 8] [--objective worker]

Every iteration draws one training instance from the generator (the base parameter file with seed 10000 + iteration
and a random number of orders), samples K plans from the policy and takes one gradient step. The baseline is the
mean value of the K plans (shared baseline), divided by their standard deviation: a plan's advantage is
(mean - value) / std, scale-free, the same weight for every instance, and without rule plans. A fixed validation set (seeds 9000-9002, never trained on) compares the greedy policy with the best of
the 15 rule plans every `--validate-every` iterations. The dental examples (seed 1) and the Fidentis case stay out of
training. Runs on one thread with fixed seeds, so a run repeats on the same machine.

Writes `<out>.npz` (weights), `<out>.json` (architecture, arguments, commit, log) and `<out>.csv` (log).
"""

import argparse
import random
import statistics
import time
from pathlib import Path

import torch

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.io.json_loader import read_model, write_csv
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.objectives import MAKESPAN, worker_objective_with_slack
from simulation.planners.ga import rule_plans
from simulation.planners.rl import Policy, rl_plan, save_policy

ROOT = Path(__file__).parents[2]
BASE = ROOT / "data/generator/dental-carriers-workers.json"
TRAIN_SEED0 = 10_000
VALIDATION_SEEDS = (9_000, 9_001, 9_002)
OBJECTIVES = {"makespan": MAKESPAN, "worker": worker_objective_with_slack(60)}


def instance(base: CarrierGeneratorParams, seed: int, n_orders: int) -> CompiledInstance:
    return compile_instance(generate_carrier_instance(base.model_copy(update={"seed": seed, "n_orders": n_orders})))


def train(base: CarrierGeneratorParams, objective, iterations: int, samples: int, lr: float,
          orders: tuple[int, int], seed: int, validate_every: int, validation_orders: int,
          hidden: tuple[int, ...] = (64, 64)) -> tuple[Policy, list[dict]]:
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    rng = random.Random(seed)
    policy = Policy(hidden=hidden)
    optimizer = torch.optim.Adam(policy.parameters(), lr=lr)
    validation = []
    for s in VALIDATION_SEEDS:
        ci = instance(base, s, validation_orders)
        validation.append((ci, min(objective.evaluate(ci, p.assignments, p.breaks) for p in rule_plans(ci))))
    log, t0 = [], time.perf_counter()
    for it in range(iterations):
        ci = instance(base, TRAIN_SEED0 + it, rng.randint(*orders))
        generator = torch.Generator().manual_seed(seed * 1_000_003 + it)
        values, log_probs = [], []
        for _ in range(samples):
            lp: list = []
            plan = rl_plan(ci, policy, generator=generator, log_probs=lp)
            values.append(objective.evaluate(ci, plan.assignments, plan.breaks))
            log_probs.append(torch.stack(lp).sum() if lp else torch.zeros(()))
        mean = sum(values) / samples
        std = statistics.pstdev(values)
        advantages = [(mean - v) / std if std else 0.0 for v in values]  # better than the mean: positive
        loss = -sum(a * lp for a, lp in zip(advantages, log_probs, strict=True)) / samples
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        row = {"iteration": it, "operations": ci.n_ops, "mean_value": mean, "best_value": min(values),
               "spread": (max(values) - min(values)) / max(mean, 1.0), "loss": loss.item(),
               "seconds": round(time.perf_counter() - t0, 1), "validation_ratio": None}
        if (it + 1) % validate_every == 0 or it == iterations - 1:  # greedy plan over the best rule plan, mean
            row["validation_ratio"] = sum(objective.evaluate(c, (p := rl_plan(c, policy)).assignments, p.breaks)
                                          / rule for c, rule in validation) / len(validation)
        log.append(row)
    return policy, log


def main(argv: list[str] | None = None) -> None:
    from simulation.experiment import _commit  # the git commit, as in the experiment rows

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="path without suffix, e.g. models/rl-makespan")
    parser.add_argument("--base", type=Path, default=BASE, help="generator parameter file of the training instances")
    parser.add_argument("--objective", choices=sorted(OBJECTIVES), default="makespan")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--samples", type=int, default=8, help="plans per instance (K)")
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--orders", type=int, nargs=2, default=(10, 40), help="orders per training instance")
    parser.add_argument("--validation-orders", type=int, default=25)
    parser.add_argument("--validate-every", type=int, default=25)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    commit = _commit()
    base = read_model(args.base, CarrierGeneratorParams)
    policy, log = train(base, OBJECTIVES[args.objective], args.iterations, args.samples, args.lr, tuple(args.orders),
                        args.seed, args.validate_every, args.validation_orders)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    record = {"commit": commit, "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "train_seed0": TRAIN_SEED0, "validation_seeds": list(VALIDATION_SEEDS), "log": log}
    save_policy(policy, args.out, record)
    write_csv(log, args.out.with_suffix(".csv"))
    last = next(r for r in reversed(log) if r["validation_ratio"] is not None)
    print(f"{args.out}: {len(log)} iterations, validation ratio {last['validation_ratio']:.4f}")  # noqa: T201


if __name__ == "__main__":
    main()
