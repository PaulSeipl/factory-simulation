"""The DES grows by packages bound during the run (math/13_des.md §3, math/33 step B2).

A run that starts on the instance known at 0 and grows at the arrival of the next package must be exactly the run
on the full instance that sees the package arrive then: same realized schedule, same log, same snapshot. Both use
keyed scenario streams (math/22), so an operation's disturbance does not depend on the instance it sits in.
"""

import pytest
from test_arrivals import two_packages

from simulation.arrival_generator import ArrivalParams, generate_arrival_instance
from simulation.carrier_generator import CarrierGeneratorParams
from simulation.io.json_loader import read_model
from simulation.model.compiled import compile_instance, compile_visible
from simulation.model.instance import Instance, visible_instance
from simulation.planners.dispatching import dispatch_plan, dispatch_planner, ect, spt
from simulation.sim.des import Simulation
from simulation.sim.scenario import sample_scenario

DISTURBED = {"sigma": 0.3, "q": 0.5, "max_early": 3, "max_late": 3}


def plain(schedule):
    return sorted((a.order_id, a.op_id, a.machine, a.start, a.end, a.workers) for a in schedule)


def run_both(inst: Instance, t: int, seed: int = 3):
    """Reference: the full instance with `visible`; grown: the instance known before t, grown at t. At t both get
    the plan a rule makes from their own snapshot (identical if the states are), then run to the end."""
    ci, at = compile_instance(inst), compile_visible(inst)
    sub = visible_instance(inst, t - 1)
    ci_sub = compile_instance(sub)
    start = dispatch_plan(at(0), spt, ect)
    planner = dispatch_planner(spt, ect)
    ref = Simulation(ci, start.assignments, sample_scenario(inst, seed=seed, keyed=True, **DISTURBED), start.breaks,
                     visible=at)
    grown = Simulation(ci_sub, start.assignments, sample_scenario(sub, seed=seed, keyed=True, **DISTURBED),
                       start.breaks)
    grown.wake_at(t)  # the nesting time is a time point of the run (execute sets it, step B3)
    for sim in (ref, grown):
        sim.run(until=t - 1)
        while sim.state.events and sim.state.events[0][0] <= t:  # the time point t itself, as execute does
            sim.process_events()
            sim.start_operations()
    grown.grow(ci, sample_scenario(inst, seed=seed, keyed=True, **DISTURBED), at)
    assert plain(grown.current_plan()) == plain(ref.current_plan())
    assert grown.snapshot() == ref.snapshot()
    running = [f for f in grown.snapshot().frozen if f.running]
    for sim in (ref, grown):
        new = planner(at(t), sim.snapshot(), sim.current_plan())
        sim.update_plan(new.assignments, new.breaks)
        sim.run()
    return ref, grown, running


def test_grown_run_equals_the_run_on_the_full_instance():
    ref, grown, _ = run_both(Instance.model_validate(two_packages(10)), 10)
    assert plain(grown.realized()) == plain(ref.realized())
    assert grown.log == ref.log
    assert grown.realized_breaks() == ref.realized_breaks()


def test_grow_keeps_a_running_operation():
    # arrival at 3: package 1 is in the middle of its first operations
    ref, grown, running = run_both(Instance.model_validate(two_packages(3)), 3)
    assert running  # grown in the middle of an operation
    assert plain(grown.realized()) == plain(ref.realized())


@pytest.mark.parametrize("seed", [2, 3, 5, 7])  # first arrival Monday 12:00, backlog still running
def test_grown_run_with_workers_and_calendar_equals_the_full_run(seed):
    # the dental example (workers, calendar, blanks, plates, runs; not the Fidentis case, user 2026-11-18), arrivals
    # at daily nesting; grow at the 2nd package
    base = read_model("data/generator/dental-carriers-workers.json", CarrierGeneratorParams).model_copy(
        update={"release_range": (0, 0), "due_date_tightness": ()})
    inst = generate_arrival_instance(ArrivalParams(seed=seed, base=base, rates=dict.fromkeys(range(5), 3.0),
                                                   window_days=3, backlog=4, backlog_earliest_cutoff=3,
                                                   due_working_days=4))
    t = sorted({o.arrival for o in inst.orders} - {0})[0]
    ref, grown, running = run_both(visible_instance(inst, t), t, seed)
    assert running  # the packages known at 0 and the one at t
    assert plain(grown.realized()) == plain(ref.realized())
    assert grown.log == ref.log
    assert grown.realized_breaks() == ref.realized_breaks()


def test_grow_rejects_other_machines_and_lost_operations():
    inst = Instance.model_validate(two_packages(10))
    ci, at, sub = compile_instance(inst), compile_visible(inst), compile_instance(visible_instance(inst, 9))
    start = dispatch_plan(at(0), spt, ect).assignments
    with pytest.raises(ValueError, match="operations missing"):
        Simulation(ci, start, visible=at).grow(sub)
    other = Instance.model_validate(two_packages(10) | {"machines": [*two_packages(10)["machines"], "X"]})
    with pytest.raises(ValueError, match="machines and workers"):
        Simulation(sub, start).grow(compile_instance(other))
