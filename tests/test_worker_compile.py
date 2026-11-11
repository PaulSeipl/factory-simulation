"""Compilation of workers and shares (math/04_workers.md, section 5); every consumer handles them since plan phase 4."""

from simulation.model.compiled import Share, compile_instance, share_interval
from simulation.model.instance import Instance
from simulation.objectives import static_horizon

ORDER = {
    "schema_version": "0.6", "name": "workers", "machines": ["P"], "workers": ["W1", "W2"],
    "orders": [{"id": "k", "operations": [
        {"id": "print", "step": "print", "options": {"P": 60}, "worker": {"prefix": 15}},
        {"id": "gb", "step": "gegenbetten", "duration": 90, "worker": {"prefix": 30, "qualified": ["W2"]},
         "predecessors": ["print"]},
        {"id": "pack", "step": "pack", "duration": 20, "worker": {"whole": True}, "predecessors": ["gb"]},
    ]}],
}


def carriers() -> dict:
    """Two plates L1, L2: print P (no worker), oven O batch of 2 (prefix 1, suffix 1), mill M per carrier with
    attended setup and removal."""
    def order(k: str) -> dict:
        return {"id": k, "parts": [{"id": "s", "type": "secondary"}], "operations": [
            {"id": "print", "step": "print", "scope": "carrier", "role": "form"},
            {"id": "oven", "step": "oven", "scope": "carrier", "predecessors": ["print"]},
            {"id": "mill", "step": "mill", "scope": "carrier", "role": "separate", "predecessors": ["oven"]},
        ]}
    return {
        "schema_version": "0.6", "name": "carrier-workers", "machines": ["P", "O", "M"], "workers": ["W1", "W2"],
        "carrier_steps": {
            "print": {"options": {"P": 2}},
            "oven": {"options": {"O": 5}, "batch_capacity": 2, "worker": {"prefix": 1, "suffix": 1}},
            "mill": {"options": {"M": 4}, "runs": "per_carrier", "setup": 1, "removal": 1,
                     "setup_attended": True, "removal_attended": True},
        },
        "orders": [order("A"), order("B")],
        "carriers": [{"id": "L1", "parts": [["A", "s"]]}, {"id": "L2", "parts": [["B", "s"]]}],
    }


CI = compile_instance(Instance.model_validate(ORDER))
CARRIERS = compile_instance(Instance.model_validate(carriers()))


def shares(ci, owner, op):
    return ci.shares[ci.op_index[owner, op]]


def test_compiled_shares_and_fixed_duration():
    assert CI.worker_ids == ("W1", "W2")
    assert CI.fixed_duration == (None, 90, 20)
    assert CI.options[1] == () and CI.options[2] == ()
    assert CI.shares == ((Share("prefix", 15, (0, 1)),), (Share("prefix", 30, (1,)),), (Share("whole", 0, (0, 1)),))


def test_carrier_step_shares():
    both = (0, 1)
    for cid in ("L1", "L2"):
        assert shares(CARRIERS, cid, "print") == ()
        assert shares(CARRIERS, cid, "oven") == (Share("prefix", 1, both), Share("suffix", 1, both))
        assert shares(CARRIERS, cid, "mill/setup") == (Share("whole", 0, both),)
        assert shares(CARRIERS, cid, "mill") == ()
        assert shares(CARRIERS, cid, "mill/removal") == (Share("whole", 0, both),)
    assert CARRIERS.fixed_duration == (None,) * CARRIERS.n_ops


def test_share_interval():
    assert share_interval(Share("whole", 0, (0,)), 10, 25) == (10, 25)
    assert share_interval(Share("prefix", 3, (0,)), 10, 25) == (10, 13)
    assert share_interval(Share("suffix", 4, (0,)), 10, 25) == (21, 25)


def test_instances_without_workers_compile_as_before():
    plain = compile_instance(Instance.model_validate(
        carriers() | {"workers": [], "carrier_steps": {"print": {"options": {"P": 2}}, "oven": {"options": {"O": 5}},
                                                       "mill": {"options": {"M": 4}}}}))
    assert plain.worker_ids == () and plain.shares == ((),) * plain.n_ops


def test_static_horizon_counts_fixed_durations():
    assert static_horizon(CI) == 60 + 90 + 20


