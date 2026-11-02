from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless; must precede the pyplot import inside simulation.viz

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

from simulation.io.json_loader import read_model  # noqa: E402
from simulation.model.compiled import compile_instance  # noqa: E402
from simulation.model.instance import Instance  # noqa: E402
from simulation.planners.dispatching import dispatch, least_load, spt  # noqa: E402
from simulation.viz import plot_carriers, plot_gantt, plot_orders  # noqa: E402

TOY = compile_instance(read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-dag-3x4.json", Instance))


def test_plot_orders_draws_one_box_per_operation_and_one_arrow_per_arc():
    fig = plot_orders(TOY, ["B"])
    patches = [p for ax in fig.axes for p in ax.patches]
    assert sum(isinstance(p, FancyBboxPatch) for p in patches) == 4  # b1..b4
    assert sum(isinstance(p, FancyArrowPatch) for p in patches) == 4  # b1->b2, b1->b3, b2->b4, b3->b4
    plt.close(fig)


def test_plot_gantt_draws_one_bar_per_assignment():
    schedule = dispatch(TOY, spt, least_load)
    ax = plot_gantt(TOY, schedule)
    assert sum(isinstance(p, Rectangle) for p in ax.patches) == len(schedule)
    assert [t.get_text() for t in ax.get_yticklabels()] == list(TOY.machine_ids)
    plt.close(ax.figure)


def test_plot_carriers_draws_one_segment_per_carried_part():
    inst = read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-carriers.json", Instance)
    ax = plot_carriers(inst, capacity=3)
    assert sum(isinstance(p, Rectangle) for p in ax.patches) == sum(len(c.parts) for c in inst.carriers)
    assert [t.get_text() for t in ax.get_yticklabels()] == ["R1 · L1", "R2 · L2"]
    plt.close(ax.figure)


def test_plot_gantt_draws_one_bar_per_batch():
    import json

    d = json.loads((Path(__file__).parents[1] / "data" / "instances" / "toy-carriers.json").read_text(encoding="utf-8"))
    d["carrier_steps"]["oven"]["batch_capacity"] = 3
    d["runs"] = [{"id": "R1", "step": "print", "carriers": ["L1", "L2"]}]
    ci = compile_instance(Instance.model_validate(d))
    schedule = dispatch(ci, spt, least_load)  # L1 and L2 share one oven run
    ax = plot_gantt(ci, schedule)
    assert sum(isinstance(p, Rectangle) for p in ax.patches) == len(schedule) - 1
    assert "L1+L2/oven" in [t.get_text() for t in ax.texts]
    plt.close(ax.figure)
