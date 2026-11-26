"""Train the learned dispatching policy with REINFORCE (math/16_rl.md §3).

    uv run python -m simulation.rl_train --out models/rl-makespan [--iterations 300] [--samples 8] [--objective worker]

Every iteration draws one training instance from the generator (the base parameter file with seed 10000 + iteration
and a random number of orders), samples K plans from the policy and takes one gradient step. The baseline is the
mean value of the K plans (shared baseline), divided by their standard deviation: a plan's advantage is
(mean - value) / std, scale-free, the same weight for every instance, and without rule plans. With a lexicographic
objective the first level on which the K plans differ decides (math/16 §3). A fixed validation set (seeds 9000-9019,
never trained on) compares the greedy policy every `--validate-every` iterations, and before the first step, with the
best of the 15 rule plans (`validation_ratio`) and with the best heuristic, the rule plans and the 5 joint rules that
take overtime whenever their operation can use it (`validation_ratio_ot`). The returned policy is the checkpoint
with the lowest `validation_ratio_ot`, the untrained network included. The dental examples (seed 1) and the Fidentis
case stay out of training. Runs on one thread with fixed seeds, so a run repeats on the same machine.

Writes `<out>.npz` (weights), `<out>.json` (architecture, arguments, commit, log) and `<out>.csv` (log).
"""

import argparse
import copy
import random
import statistics
import time
from pathlib import Path

import torch

from simulation.carrier_generator import CarrierGeneratorParams, generate_carrier_instance
from simulation.io.json_loader import read_model, write_csv
from simulation.model.compiled import CompiledInstance, compile_instance
from simulation.objectives import MAKESPAN, worker_objective_with_slack
from simulation.planners.dispatching import SEQUENCING_RULES, dispatch_plan
from simulation.planners.ga import rule_plans
from simulation.planners.rl import Policy, overtime_option, rl_plan, save_policy

ROOT = Path(__file__).parents[2]
BASE = ROOT / "data/generator/dental-carriers-workers.json"
TRAIN_SEED0 = 10_000
VALIDATION_SEEDS = tuple(range(9_000, 9_020))
OBJECTIVES = {"makespan": MAKESPAN, "worker": worker_objective_with_slack(60)}


def instance(base: CarrierGeneratorParams, seed: int, n_orders: int) -> CompiledInstance:
    return compile_instance(generate_carrier_instance(base.model_copy(update={"seed": seed, "n_orders": n_orders})))


def overtime_rule_plans(ci: CompiledInstance):
    """The 5 joint rules with overtime candidates: each picks its operation as usual and, if overtime lets that
    operation start earlier, takes it with overtime (a heuristic yardstick for a policy that may plan overtime)."""
    option = overtime_option(ci)
    for seq in SEQUENCING_RULES.values():
        def choose(eligible, state, seq=seq):
            return min(range(len(eligible)), key=lambda i: (
                *seq(ci, state, *eligible[i][1:4]), eligible[i][1], eligible[i][2] is None, eligible[i][2] or 0,
                len(eligible[i]) == 4))
        yield dispatch_plan(ci, seq, choose=choose, overtime_option=option)


def levels(objective, ci: CompiledInstance, plan) -> tuple[int, ...]:
    """The plan's value per level of a lexicographic objective, highest first; (value,) otherwise."""
    return tuple(f.evaluate(ci, plan.assignments, plan.breaks) for f in objective.levels or (objective,))


def advantages(values: list[tuple[int, ...]]) -> list[float]:
    """(mean - value) / std on the first level on which the plans differ; all 0 if they never differ."""
    for level in zip(*values, strict=True):
        if std := statistics.pstdev(level):
            mean = statistics.fmean(level)
            return [(mean - v) / std for v in level]
    return [0.0] * len(values)


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
        rule = min(objective.evaluate(ci, p.assignments, p.breaks) for p in rule_plans(ci))
        with_ot = min(objective.evaluate(ci, p.assignments, p.breaks) for p in overtime_rule_plans(ci))
        validation.append((ci, rule, min(rule, with_ot)))

    def validate() -> tuple[float, float]:
        values = [objective.evaluate(c, (p := rl_plan(c, policy)).assignments, p.breaks) for c, _, _ in validation]
        return (statistics.fmean(v / rule for v, (_, rule, _) in zip(values, validation, strict=True)),
                statistics.fmean(v / best for v, (_, _, best) in zip(values, validation, strict=True)))

    ratio, ratio_ot = validate()
    best = ratio_ot, copy.deepcopy(policy.state_dict())
    log = [{"iteration": -1, "operations": 0, "mean_value": None, "best_value": None, "spread": None, "loss": None,
            "seconds": 0.0, "validation_ratio": ratio, "validation_ratio_ot": ratio_ot, "checkpoint": True}]
    t0 = time.perf_counter()
    for it in range(iterations):
        ci = instance(base, TRAIN_SEED0 + it, rng.randint(*orders))
        generator = torch.Generator().manual_seed(seed * 1_000_003 + it)
        values, per_level, log_probs = [], [], []
        for _ in range(samples):
            lp: list = []
            plan = rl_plan(ci, policy, generator=generator, log_probs=lp)
            values.append(objective.evaluate(ci, plan.assignments, plan.breaks))
            per_level.append(levels(objective, ci, plan))
            log_probs.append(torch.stack(lp).sum() if lp else torch.zeros(()))
        mean = sum(values) / samples
        adv = advantages(per_level)  # better than the mean: positive
        loss = -sum(a * lp for a, lp in zip(adv, log_probs, strict=True)) / samples
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        row = {"iteration": it, "operations": ci.n_ops, "mean_value": mean, "best_value": min(values),
               "spread": (max(values) - min(values)) / max(mean, 1.0), "loss": loss.item(),
               "seconds": round(time.perf_counter() - t0, 1), "validation_ratio": None,
               "validation_ratio_ot": None, "checkpoint": False}
        if (it + 1) % validate_every == 0 or it == iterations - 1:  # greedy plan over the yardsticks, mean
            row["validation_ratio"], row["validation_ratio_ot"] = validate()
            if row["validation_ratio_ot"] < best[0]:
                best, row["checkpoint"] = (row["validation_ratio_ot"], copy.deepcopy(policy.state_dict())), True
        log.append(row)
    policy.load_state_dict(best[1])
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
    best = next(r for r in reversed(log) if r["checkpoint"])
    print(f"{args.out}: {args.iterations} iterations, checkpoint of iteration {best['iteration']}: validation ratio "  # noqa: T201
          f"{best['validation_ratio']:.4f} (rules), {best['validation_ratio_ot']:.4f} (with overtime rules)")


if __name__ == "__main__":
    main()
