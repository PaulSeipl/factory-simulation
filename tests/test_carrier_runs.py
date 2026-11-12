"""Runs per carrier (math/03_carriers.md, G3/G4): a carrier step with runs="per_carrier" (e.g. milling the parts of one
carrier) gives every carrier its own run of setup, main operation and removal; no nesting input."""

import pytest
from pydantic import ValidationError

from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.model.instance import Instance
from simulation.planners.cpsat import solve
from simulation.planners.dispatching import ASSIGNMENT_RULES, SEQUENCING_RULES, dispatch
from simulation.sim.des import replay


def data() -> dict:
    """A and B with one secondary part each on L1 and L2; design D, print P (one operation per carrier),
    mill M per carrier: setup 1, main = sum of the part times (A 2, B 3; the constant 9 is overridden), removal 1."""
    def order(k: str, mill: int) -> dict:
        return {"id": k, "parts": [{"id": "s", "type": "secondary", "times": {"mill": mill}}], "operations": [
            {"id": "design", "step": "design", "options": {"D": 1}},
            {"id": "print", "step": "print", "scope": "carrier", "role": "form", "predecessors": ["design"]},
            {"id": "mill", "step": "mill", "scope": "carrier", "role": "separate", "predecessors": ["print"]},
        ]}
    return {
        "schema_version": "0.7", "name": "carrier-runs", "machines": ["D", "P", "M"],
        "carrier_steps": {
            "print": {"options": {"P": 2}},
            "mill": {"options": {"M": 9}, "runs": "per_carrier", "setup": 1, "removal": 1,
                     "estimator": {"fixed": 0, "share": 1}},
        },
        "orders": [order("A", 2), order("B", 3)],
        "carriers": [{"id": "L1", "parts": [["A", "s"]]}, {"id": "L2", "parts": [["B", "s"]]}],
    }


CI = compile_instance(Instance.model_validate(data()))
RUN = ("mill/setup", "mill", "mill/removal")


def by_key(plan):
    return {(a.order_id, a.op_id): (a.machine, a.start, a.end) for a in plan}


def test_every_carrier_gets_its_own_run():
    for cid in ("L1", "L2"):
        assert tuple(CI.op_index[cid, j] for j in RUN) in CI.machine_groups
    assert dict(CI.options[CI.op_index["L1", "mill"]]) == {CI.machine_index["M"]: 2}  # estimate, not the constant
    assert dict(CI.options[CI.op_index["L2", "mill"]]) == {CI.machine_index["M"]: 3}
    assert [CI.op_keys[p] for p in CI.predecessors[CI.op_index["L1", "mill/setup"]]] == [("L1", "print")]


def test_cpsat_optimum_by_hand():
    # Lower bound 12: the mill can start at 3 at the earliest (design 1, print 2) and has 9 minutes of work
    # (two setups, two removals, mains 2 and 3). Reached e.g. by A first: L1 run [3,7), L2 run [7,12).
    result = solve(CI, time_limit=10, workers=1)
    assert (result.status, result.objective, result.bound) == ("OPTIMAL", 12, 12)
    assert check_schedule(CI, result.schedule) == []
    assert by_key(replay(CI, result.schedule).schedule) == by_key(result.schedule)  # zero-disturbance


@pytest.mark.parametrize("seq", sorted(SEQUENCING_RULES))
@pytest.mark.parametrize("assign", sorted(ASSIGNMENT_RULES))
def test_every_rule_keeps_the_run_together_and_replays_unchanged(seq, assign):
    plan = dispatch(CI, SEQUENCING_RULES[seq], ASSIGNMENT_RULES[assign])
    assert check_schedule(CI, plan) == []
    assert by_key(replay(CI, plan).schedule) == by_key(plan)
    times = by_key(plan)
    for cid in ("L1", "L2"):  # back to back: setup, main, removal
        assert times[cid, RUN[0]][2] == times[cid, RUN[1]][1] and times[cid, RUN[1]][2] == times[cid, RUN[2]][1]


def test_checker_finds_a_run_interrupted_by_another_run():
    plan = {(a.order_id, a.op_id): a for a in solve(CI, time_limit=10, workers=1).schedule}
    first, second = sorted(("L1", "L2"), key=lambda c: plan[c, "mill/setup"].start)
    removal = plan[first, "mill/removal"]
    plan[first, "mill/removal"] = removal.model_copy(update={"start": removal.start + 6, "end": removal.end + 6})
    assert "C9" in {v.constraint for v in check_schedule(CI, list(plan.values()))}


def m_setup_without_runs(d):
    d["carrier_steps"]["mill"]["runs"] = "none"


def m_estimator_without_runs(d):
    d["carrier_steps"]["print"]["estimator"] = {"fixed": 0, "share": 1}


def m_given_run_for_per_carrier_step(d):
    d["runs"] = [{"id": "R1", "step": "mill", "carriers": ["L1"]}]


def m_given_step_without_runs(d):
    d["carrier_steps"]["print"].update(runs="given", setup=1)


def m_missing_part_time(d):
    d["orders"][1]["parts"][0]["times"] = {}


def m_batch_step_with_runs(d):
    d["carrier_steps"]["print"].update(runs="per_carrier", batch_capacity=2)


@pytest.mark.parametrize(("mutate", "message"), [
    (m_setup_without_runs, r"carrier step mill: setup, removal and estimator need runs"),
    (m_estimator_without_runs, r"carrier step print: setup, removal and estimator need runs"),
    (m_given_run_for_per_carrier_step, r"carrier step mill: runs are given, but the step declares "
                                       r"runs='per_carrier'"),
    (m_given_step_without_runs, r"carrier L1 passes step print but is in no run of it"),
    (m_missing_part_time, r"carrier L2: no mill time for parts \[\('B', 's'\)\] \(needed by the estimator\)"),
    (m_batch_step_with_runs, r"carrier step print: batched by the planner, so no given runs"),
], ids=lambda v: v.__name__ if callable(v) else None)
def test_invalid_runs_rejected(mutate, message):
    d = data()
    mutate(d)
    with pytest.raises(ValidationError, match=message):
        Instance.model_validate(d)
