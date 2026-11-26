"""Features of the dispatcher's candidates for a learned policy (math/16_rl.md §2).

One row per eligible candidate (t, o, m, p[, allowance]) of a decision (the hook `choose`, math/11 §5), all values
scale-free so that one policy serves instances of any size:
- times in units of the instance's mean shortest processing time p̄, wide ranges through log1p;
- loads relative to their mean over machines or workers;
- some values also relative to the other candidates of the same decision (the network scores each row alone);
- two global values, the same in every row: share of the work done, number of candidates.
FEATURE_VERSION changes with any change of the rows, so a stored policy can refuse features it was not trained on.
"""

import math

import numpy as np

from simulation.model.compiled import CompiledInstance
from simulation.planners.dispatching import DispatchState

FEATURE_VERSION = 1
NAMES = (
    "p", "wait", "p_rel", "work_left", "remaining_path", "path_rel", "due_slack", "has_due", "machine_load",
    "worker_load", "has_workers", "overtime", "batch_step", "s_batch_step", "run_head", "successors",
    "work_done", "candidates",
)


def _symlog(x: float) -> float:
    return math.copysign(math.log1p(abs(x)), x)


class Featurizer:
    """Static values of an instance computed once; `__call__(eligible, state)` gives the feature matrix."""

    def __init__(self, ci: CompiledInstance):
        self.ci = ci
        min_p = [min(p for _, p in opts) if opts else ci.fixed_duration[o] for o, opts in enumerate(ci.options)]
        self.p_bar = max(1.0, sum(min_p) / max(1, ci.n_ops))
        self.total_work = max(1, sum(min_p[o] for o in range(ci.n_ops) for _ in ci.op_orders[o]))
        self.due = [min((d for k in ci.op_orders[o] if (d := ci.due_date[k]) is not None), default=None)
                    for o in range(ci.n_ops)]
        self.run_heads = {g[0] for g in ci.machine_groups}

    def __call__(self, eligible, state: DispatchState) -> np.ndarray:
        ci, pb = self.ci, self.p_bar
        now = min(c[0] for c in eligible)
        p_mean = sum(c[3] for c in eligible) / len(eligible)
        path_max = max(state.remaining_path[c[1]] for c in eligible) or 1
        machine_mean = sum(state.load) / len(state.load) if state.load else 0
        worker_mean = sum(state.worker_load) / len(state.worker_load) if state.worker_load else 0
        work_done = 1 - sum(state.work_left) / self.total_work
        rows = []
        for c in eligible:
            t, o, m, p = c[:4]
            due = self.due[o]
            workers = {w for sh in ci.shares[o] for w in sh.workers}
            rows.append((
                p / pb,
                math.log1p((t - now) / pb),
                p / p_mean if p_mean else 0.0,
                math.log1p(max(state.work_left[k] for k in ci.op_orders[o]) / pb),
                math.log1p(state.remaining_path[o] / pb),
                state.remaining_path[o] / path_max,
                _symlog((due - t - state.remaining_path[o]) / pb) if due is not None else 0.0,
                float(due is not None),
                state.load[m] / machine_mean if m is not None and machine_mean else 0.0,
                min(state.worker_load[w] for w in workers) / worker_mean if workers and worker_mean else 0.0,
                float(bool(workers)),
                float(len(c) > 4),
                float(ci.batch_capacity[o] > 1),
                float(ci.s_setup[o] is not None),
                float(o in self.run_heads),
                math.log1p(len(ci.successors[o])),
                work_done,
                math.log1p(len(eligible)),
            ))
        return np.asarray(rows, dtype=np.float32)
