"""Worker shares and machine-less operations in the instance format (math/04_workers.md, section 2).

Base instance: printer P, workers A and B; order k: print on P (60 min, prefix 15), Gegenbetten without machine
(90 min, prefix 30, only A), packaging without machine (20 min, whole).
"""

import copy

import pytest
from pydantic import ValidationError

from simulation.due_dates import lead_time_bound
from simulation.model.instance import Instance, WorkerShare

BASE = {
    "schema_version": "0.6", "name": "workers", "machines": ["P"], "workers": ["A", "B"],
    "orders": [{"id": "k", "operations": [
        {"id": "print", "step": "print", "options": {"P": 60}, "worker": {"prefix": 15}},
        {"id": "gb", "step": "gegenbetten", "duration": 90, "worker": {"prefix": 30, "qualified": ["A"]},
         "predecessors": ["print"]},
        {"id": "pack", "step": "pack", "duration": 20, "worker": {"whole": True}, "predecessors": ["gb"]},
    ]}],
}


def data():
    return copy.deepcopy(BASE)


def op(d, i):
    return d["orders"][0]["operations"][i]


def test_valid_worker_instance_loads():
    inst = Instance.model_validate(BASE)
    assert inst.workers == ("A", "B")
    gb = inst.orders[0].operations[1]
    assert (gb.options, gb.duration, gb.worker) == (None, 90, WorkerShare(prefix=30, qualified=("A",)))


def test_lead_time_bound_counts_machine_less_durations():
    assert lead_time_bound(Instance.model_validate(BASE).orders[0]) == 60 + 90 + 20


def test_instances_without_workers_unchanged():
    d = data()
    del d["workers"]
    for o in d["orders"][0]["operations"]:
        o.pop("worker")
        o.pop("duration", None)
        o.setdefault("options", {"P": 5})
    assert Instance.model_validate(d).workers == ()


def test_oven_step_with_shares_and_attended_run_setup():
    d = data()
    d["carrier_steps"] = {
        "oven": {"options": {"P": 90}, "batch_capacity": 3, "worker": {"prefix": 10, "suffix": 10}},
        "mill": {"options": {"P": 40}, "runs": "per_carrier", "setup": 5, "removal": 5,
                 "setup_attended": True, "removal_attended": True},
    }
    steps = Instance.model_validate(d).carrier_steps
    assert steps["oven"].worker == WorkerShare(prefix=10, suffix=10) and steps["mill"].setup_attended


# --- one negative test per rule ---------------------------------------------------


@pytest.mark.parametrize("share", [{"whole": True, "prefix": 5}, {}, {"suffix": 0}, {"qualified": []}])
def test_invalid_share(share):
    with pytest.raises(ValidationError):
        WorkerShare(**share)


def shares_longer_than_operation(d):
    op(d, 0)["worker"] = {"prefix": 40, "suffix": 30}  # 70 > 60


def share_longer_than_duration(d):
    op(d, 1)["worker"] = {"prefix": 91}


def unknown_qualified_worker(d):
    op(d, 1)["worker"]["qualified"] = ["Z"]


def duplicate_worker(d):
    d["workers"] = ["A", "A"]


def worker_named_like_a_machine(d):
    d["workers"] = ["A", "P"]


def shares_without_workers(d):
    d["workers"] = []


def options_and_duration(d):
    op(d, 0)["duration"] = 60


def machine_less_without_worker(d):
    del op(d, 2)["worker"]


def neither_options_nor_duration(d):
    del op(d, 2)["duration"]


def carrier_operation_with_duration(d):
    d["carrier_steps"] = {"oven": {"options": {"P": 90}}}
    op(d, 2).update(scope="carrier", step="oven")


def carrier_operation_with_own_share(d):
    d["carrier_steps"] = {"oven": {"options": {"P": 90}}}
    op(d, 2).update(scope="carrier", step="oven")
    del op(d, 2)["duration"]


def attended_setup_without_setup(d):
    d["carrier_steps"] = {"mill": {"options": {"P": 40}, "runs": "per_carrier", "setup_attended": True}}


def attended_removal_without_removal(d):
    d["carrier_steps"] = {"mill": {"options": {"P": 40}, "runs": "per_carrier", "setup": 5,
                                   "removal_attended": True}}


def attended_setup_without_workers(d):
    d["workers"] = []
    for o in d["orders"][0]["operations"]:
        o.pop("worker")
        o.pop("duration", None)
        o.setdefault("options", {"P": 5})
    d["carrier_steps"] = {"mill": {"options": {"P": 40}, "runs": "per_carrier", "setup": 5, "setup_attended": True}}


def step_share_longer_than_step(d):
    d["carrier_steps"] = {"oven": {"options": {"P": 90}, "worker": {"prefix": 50, "suffix": 50}}}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (shares_longer_than_operation, r"order k, op print: prefix \+ suffix 70 longer than the operation \(60\)"),
        (share_longer_than_duration, r"order k, op gb: prefix \+ suffix 91 longer than the operation \(90\)"),
        (unknown_qualified_worker, r"order k, op gb: unknown workers \['Z'\]"),
        (duplicate_worker, r"duplicate worker IDs: \['A'\]"),
        (worker_named_like_a_machine, r"IDs used for workers and machines: \['P'\]"),
        (shares_without_workers, r"order k, op print: worker share, but the instance has no workers"),
        (options_and_duration, r"order k, op print: options and duration are exclusive"),
        (machine_less_without_worker, r"order k, op pack: an operation without machine needs a worker share"),
        (neither_options_nor_duration, r"order k, op pack: options or duration missing"),
        (carrier_operation_with_duration, r"order k, op pack: carrier operation with duration"),
        (carrier_operation_with_own_share, r"order k, op pack: carrier operation with a worker share"),
        (attended_setup_without_setup, r"carrier step mill: setup_attended without setup"),
        (attended_removal_without_removal, r"carrier step mill: removal_attended without removal"),
        (attended_setup_without_workers, r"carrier step mill: attended setup or removal, but the instance has no"),
        (step_share_longer_than_step, r"carrier step oven: prefix \+ suffix 100 longer than the operation \(90\)"),
    ],
    ids=lambda v: v.__name__ if callable(v) else None,
)
def test_invalid_worker_instance_rejected(mutate, message):
    d = data()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)
