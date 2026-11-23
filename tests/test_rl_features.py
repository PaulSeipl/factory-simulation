"""Features for a learned policy (src/simulation/planners/rl_features.py, math/16_rl.md) and the worker loads in
DispatchState they read."""

import math

import numpy as np
import pytest
from test_dispatch_choose import INSTANCES, seeded_chooser
from test_ga import late_pack

from simulation.planners.dispatching import SEQUENCING_RULES, Checkpoint, dispatch_plan, dispatch_until
from simulation.planners.rl_features import FEATURE_VERSION, NAMES, Featurizer

SPT = SEQUENCING_RULES["spt"]


def collect(ci, overtime_option=None, seed=0):
    """Feature matrices and worker loads at every decision of a seeded random run."""
    featurize, pick, seen = Featurizer(ci), seeded_chooser(seed), []

    def choose(eligible, state):
        if len(eligible) > 1:
            seen.append((eligible, featurize(eligible, state), list(state.worker_load)))
        return pick(eligible, state)

    dispatch_plan(ci, SPT, choose=choose, overtime_option=overtime_option)
    return seen


@pytest.mark.parametrize("name", list(INSTANCES))
def test_one_finite_row_per_candidate(name):
    for eligible, x, _ in collect(INSTANCES[name]):
        assert x.dtype == np.float32 and x.shape == (len(eligible), len(NAMES)) and np.isfinite(x).all()
    assert FEATURE_VERSION == 1


def test_overtime_flag_marks_exactly_the_variants():
    ci = INSTANCES["dental-carriers-workers"]
    rows = collect(ci, overtime_option=ci.calendar.max_overtime)
    flags = [(len(c) > 4, x[i, NAMES.index("overtime")]) for eligible, x, _ in rows for i, c in enumerate(eligible)]
    assert any(v for v, _ in flags) and all(f == float(v) for v, f in flags)


def test_worker_loads_grow_and_survive_a_resume():
    # the state's worker loads are the dispatcher's own list: they only grow, and a resumed run sees at each decision
    # the loads of the uninterrupted run (Checkpoint.restore keeps state and dispatcher on one list)
    ci = INSTANCES["dental-carriers-workers"]
    loads = [w for _, _, w in collect(ci)]
    assert loads[-1] and sum(loads[-1]) > 0
    assert all(all(a <= b for a, b in zip(x, y, strict=True)) for x, y in zip(loads, loads[1:]))
    pick = seeded_chooser(0)
    cp = dispatch_until(ci, SPT, None, None, pick, 30)
    assert isinstance(cp, Checkpoint)
    resumed = []

    def choose(eligible, state):
        if len(eligible) > 1:
            resumed.append(list(state.worker_load))
        return pick(eligible, state)

    dispatch_plan(ci, SPT, choose=choose, resume=cp)
    assert resumed == loads[30:]


def test_late_pack_by_hand():
    # one 90-minute pack: p̄ = 90; candidates (Tuesday 08:00 = 1440) and (Monday 16:30 = 510, in overtime): now 510
    ci = late_pack()
    (eligible, x, _), = collect(ci, overtime_option=120)
    col = {n: i for i, n in enumerate(NAMES)}
    plain, variant = (0, 1) if len(eligible[0]) == 4 else (1, 0)
    assert x[plain, col["p"]] == x[variant, col["p"]] == 1.0
    assert x[variant, col["wait"]] == 0.0
    assert x[plain, col["wait"]] == pytest.approx(math.log1p((1440 - 510) / 90))
    assert (x[plain, col["overtime"]], x[variant, col["overtime"]]) == (0.0, 1.0)
    assert x[plain, col["has_workers"]] == 1.0 and x[plain, col["has_due"]] == 0.0
    assert x[plain, col["work_done"]] == 0.0 and x[plain, col["candidates"]] == pytest.approx(math.log(3))
