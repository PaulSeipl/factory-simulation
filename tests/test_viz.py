from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")  # headless; must precede the pyplot import inside simulation.viz

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

from simulation.io.json_loader import read_model  # noqa: E402
from simulation.model.compiled import compile_instance  # noqa: E402
from simulation.model.instance import Instance  # noqa: E402
from simulation.model.schedule import Assignment, Break  # noqa: E402
from simulation.planners.dispatching import dispatch, least_load, spt  # noqa: E402
from simulation.viz import (  # noqa: E402
    UNATTENDED,
    plot_carriers,
    plot_days,
    plot_gantt,
    plot_orders,
    plot_shifts,
    shift_bars,
)

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


# --- worker plans on the calendar ---------------------------------------------------------------------------------
# toy-workshop: t = 0 is Monday 08:00, 17:30 is t = 570, 19:30 t = 690, Tuesday 08:00 t = 1440

WORKSHOP = compile_instance(
    read_model(Path(__file__).parents[1] / "data" / "instances" / "toy-workshop.json", Instance))
PRINT = Assignment(order_id="k4", op_id="print", machine="printer", start=420, end=1500, workers=("A",))
QM = Assignment(order_id="k7", op_id="qm", machine=None, start=450, end=600, workers=("A",))


def test_shift_bars_split_overtime_and_keep_whole_shares_off_machine_rows():
    names, bars = shift_bars(WORKSHOP, [PRINT, QM], [Break(worker="A", start=240)])
    assert names == ["printer", "A"]  # QM is worker time only: no "rest" row
    assert {(b.row, b.start, b.end, b.kind, b.inner) for b in bars} == {
        ("printer", 420, 1500, "unattended", False), ("printer", 420, 440, "attended", True),  # print, its loading
        ("A", 420, 440, "attended", False), ("A", 450, 570, "attended", False),
        ("A", 570, 600, "overtime", False), ("A", 240, 300, "break", False)}
    assert shift_bars(WORKSHOP, [PRINT, QM], rows="machines")[0] == ["printer"]
    with pytest.raises(ValueError, match="rows"):
        shift_bars(WORKSHOP, [PRINT], rows="days")


def test_plot_shifts_squeezes_the_night():
    ax = plot_shifts(WORKSHOP, [PRINT, QM], night=60)
    bar = next(p for p in ax.patches if isinstance(p, Rectangle) and p.get_y() < 0)  # the print (row 0)
    # Monday 08:00-19:30 to scale (690), the night to Tuesday 08:00 squeezed to 60: the print ends 60 later
    assert (bar.get_x(), bar.get_x() + bar.get_width()) == pytest.approx((420, 690 + 60 + 60))
    plt.close(ax.figure)


def test_plot_days_splits_a_bar_at_midnight():
    fig = plot_days(WORKSHOP, [PRINT], days=2)
    unattended = [[p for p in ax.patches if p.get_facecolor()[:3] == to_rgb(UNATTENDED)] for ax in fig.axes[:2]]
    assert [len(u) for u in unattended] == [1, 1]  # Monday until midnight, Tuesday until 09:00
    plt.close(fig)


def test_color_by_machine_uses_three_validated_hues_and_a_neutral():
    ax = plot_shifts(WORKSHOP, [PRINT, QM], rows="workers", color_by="machine")
    faces = {tuple(round(c, 3) for c in p.get_facecolor()[:3]) for p in ax.patches if isinstance(p, Rectangle)
             and p.get_y() > -1}  # worker A's bars (row 0)
    assert {tuple(round(c, 3) for c in to_rgb(c)) for c in ("#2a78d6", "#dcdbd6")} <= faces  # printer, QM
    plt.close(ax.figure)
    with pytest.raises(ValueError, match="color_by"):
        plot_shifts(WORKSHOP, [PRINT], color_by="order")
