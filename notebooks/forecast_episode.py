"""One episode of release during the run (math/33) for notebook 08: in a module of its own so that a process pool
can run the episodes in parallel (a function defined in the notebook cannot be sent to another process)."""

from simulation.arrival_generator import ArrivalParams
from simulation.carrier_generator import CarrierGeneratorParams
from simulation.control.nesting import Nesting
from simulation.control.rescheduling import ReschedulingPolicy, execute
from simulation.metrics import run_metrics
from simulation.model.compiled import compile_instance
from simulation.planners.dispatching import dispatch_plan, dispatch_planner, ect, spt
from simulation.sim.scenario import sample_scenario


def episode(base: CarrierGeneratorParams, seed: int, rate: float, norm: dict | None) -> dict:
    """Rule start plan, rule at every nesting time, repair otherwise, keyed disturbances; metrics and pool times."""
    p = ArrivalParams(seed=seed, base=base, rates=dict.fromkeys(range(5), rate), window_days=10, backlog=2,
                      due_working_days=10, norm=norm)
    nesting = Nesting(p)
    first = nesting.instance()
    ci0 = compile_instance(first)
    start = dispatch_plan(ci0, spt, ect)

    def scenario(inst):
        return sample_scenario(inst, seed=seed, keyed=True, sigma=0.2, q=0.5, max_early=5, max_late=5)

    result = execute(ci0, start.assignments, scenario(first), ReschedulingPolicy(planner=dispatch_planner(spt, ect)),
                     start.breaks, nesting=nesting, scenario_for=scenario)
    final = nesting.instance()
    m = run_metrics(compile_instance(final), start.assignments, result)
    return {"rate": rate, "release": f"norm {norm['window_days']} d" if norm else "bind all", "seed": seed,
            "metrics": {k: m[k] for k in ("makespan", "tardy_orders", "tardy_days", "overtime")},
            "pool": [(o.accepted, o.arrival) for o in final.orders]}
