"""Learned dispatching policy (math/16_rl.md §3, §5).

The policy scores every eligible candidate of a decision with one small network over its features (rl_features) and
takes the softmax over the candidates: greedy (the highest score) when planning, sampled when training. It decides
through the dispatcher's hook `choose`, with overtime candidates when the instance has workers and a calendar, so
every plan is feasible. Load and s-batch partners are ranked by SPT (the dispatcher's `sequencing`).

Storage without pickle: the weights as .npz (loaded with allow_pickle=False), the architecture and the training
record as JSON next to it. A policy refuses features of another FEATURE_VERSION.
"""

import json
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Plan
from simulation.planners.dispatching import dispatch_plan, spt
from simulation.planners.rl_features import FEATURE_VERSION, NAMES, Featurizer

if TYPE_CHECKING:
    from simulation.sim.snapshot import Snapshot

POLICY_FORMAT = 1


class Policy(torch.nn.Module):
    """Score of a candidate from its feature row: an MLP with ReLU layers."""

    def __init__(self, n_features: int = len(NAMES), hidden: tuple[int, ...] = (64, 64)):
        super().__init__()
        layers, width = [], n_features
        for h in hidden:
            layers += [torch.nn.Linear(width, h), torch.nn.ReLU()]
            width = h
        self.net = torch.nn.Sequential(*layers, torch.nn.Linear(width, 1))
        self.hidden = tuple(hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def save_policy(policy: Policy, path: Path, record: dict) -> None:
    """Weights to `path`.npz, architecture and `record` (training arguments, log, commit) to `path`.json."""
    path = Path(path)
    np.savez(path.with_suffix(".npz"), **{k: v.detach().cpu().numpy() for k, v in policy.state_dict().items()})
    meta = {"format": POLICY_FORMAT, "feature_version": FEATURE_VERSION, "features": list(NAMES),
            "hidden": list(policy.hidden)}
    path.with_suffix(".json").write_text(json.dumps(meta | record, indent=1), encoding="utf-8")


def load_policy(path: Path) -> Policy:
    path = Path(path)
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if meta["format"] != POLICY_FORMAT or meta["feature_version"] != FEATURE_VERSION or meta["features"] != list(NAMES):
        raise ValueError(f"{path}: trained on features version {meta['feature_version']}, these are "
                         f"{FEATURE_VERSION}")
    policy = Policy(len(NAMES), tuple(meta["hidden"]))
    with np.load(path.with_suffix(".npz"), allow_pickle=False) as weights:
        policy.load_state_dict({k: torch.from_numpy(weights[k]) for k in weights.files})
    return policy.eval()


def overtime_option(ci: CompiledInstance) -> int | None:
    """The overtime the policy may choose: the calendar's maximum, if there are workers to use it."""
    cal = ci.calendar
    return cal.max_overtime if cal is not None and cal.max_overtime > 0 and ci.worker_ids else None


def rl_plan(ci: CompiledInstance, policy: Policy, snapshot: Snapshot | None = None,
            generator: torch.Generator | None = None, log_probs: list | None = None) -> Plan:
    """The policy's plan: greedy without `generator`; sampled with it, the log-probability of every choice appended
    to `log_probs` (with gradients, for training)."""
    featurize = Featurizer(ci)

    def choose(eligible, state) -> int:
        if len(eligible) == 1:
            return 0
        scores = policy(torch.from_numpy(featurize(eligible, state)))
        if generator is None:
            return int(torch.argmax(scores))  # ties: the first candidate
        logp = torch.log_softmax(scores, dim=0)
        i = int(torch.multinomial(logp.exp(), 1, generator=generator))
        log_probs.append(logp[i])
        return i

    with torch.no_grad() if log_probs is None else nullcontext():
        return dispatch_plan(ci, spt, None, snapshot, choose=choose, overtime_option=overtime_option(ci))
