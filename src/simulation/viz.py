"""Plots for instances and schedules (matplotlib, dev dependency only).

- plot_orders: precedence graph of selected orders, operations in columns by depth
- plot_gantt: schedule per machine, bars colored by order
"""

from collections.abc import Iterable, Sequence

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from simulation.model.compiled import CompiledInstance
from simulation.model.schedule import Assignment

BOX_W, BOX_H, GAP_X, GAP_Y = 1.6, 0.8, 0.7, 0.35


def order_color(ci: CompiledInstance, k: int):
    cmap = plt.get_cmap("tab10" if len(ci.order_ids) <= 10 else "tab20")
    return cmap(k % cmap.N)


def _layout(ci: CompiledInstance, k: int) -> dict[int, tuple[float, float]]:
    """Box centers for the operations of order k: column = depth in the DAG, rows centered."""
    ops = [o for o in ci.topo_order if ci.op_order[o] == k]
    depth: dict[int, int] = {}
    for o in ops:
        depth[o] = max((depth[p] + 1 for p in ci.predecessors[o]), default=0)
    columns: dict[int, list[int]] = {}
    for o in sorted(ops):
        columns.setdefault(depth[o], []).append(o)
    pos = {}
    for d, col in columns.items():
        for i, o in enumerate(col):
            pos[o] = (d * (BOX_W + GAP_X), ((len(col) - 1) / 2 - i) * (BOX_H + GAP_Y))
    return pos


def plot_orders(ci: CompiledInstance, order_ids: Sequence[str] | None = None, ncols: int = 3) -> Figure:
    """Precedence graphs of the given orders (default: all), one panel per order, same scale."""
    order_ids = list(order_ids or ci.order_ids)
    ks = [ci.order_ids.index(k) for k in order_ids]
    layouts = {k: _layout(ci, k) for k in ks}
    width = max(x for pos in layouts.values() for x, _ in pos.values()) + BOX_W
    half_h = max(abs(y) for pos in layouts.values() for _, y in pos.values()) + BOX_H / 2

    ncols = min(ncols, len(ks))
    nrows = -(-len(ks) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * (width + 0.6), nrows * (2 * half_h + 1)), squeeze=False)
    for ax in axes.flat:
        ax.set_axis_off()
    for ax, k in zip(axes.flat, ks, strict=False):
        color, pos = order_color(ci, k), layouts[k]
        for o, (x, y) in pos.items():
            ax.add_patch(FancyBboxPatch(
                (x - BOX_W / 2, y - BOX_H / 2), BOX_W, BOX_H, boxstyle="round,pad=0,rounding_size=0.12",
                facecolor=(*color[:3], 0.18), edgecolor=color, linewidth=1.5,
            ))
            options = "  ".join(f"{ci.machine_ids[m]}·{p}" for m, p in ci.options[o])
            ax.text(x, y + 0.13, ci.op_keys[o][1], ha="center", va="center", fontsize=10, fontweight="bold")
            ax.text(x, y - 0.17, options, ha="center", va="center", fontsize=7, family="monospace")
            for q in ci.predecessors[o]:
                (xq, yq) = pos[q]
                ax.add_patch(FancyArrowPatch(
                    (xq + BOX_W / 2, yq), (x - BOX_W / 2, y), arrowstyle="-|>", mutation_scale=12, color="0.45",
                ))
        ax.set_title(f"Order {ci.order_ids[k]} · release {ci.release[min(pos)]}", loc="left", color=color, fontsize=10)
        ax.set_xlim(-BOX_W / 2 - 0.1, width - BOX_W / 2 + 0.1)
        ax.set_ylim(-half_h - 0.1, half_h + 0.1)
        ax.set_aspect("equal")
    fig.tight_layout()
    return fig


def plot_gantt(ci: CompiledInstance, assignments: Iterable[Assignment], ax: Axes | None = None,
               title: str | None = None) -> Axes:
    """One row per machine (first machine on top), one bar per assignment, colored by order."""
    assignments = list(assignments)
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 0.45 * ci.n_machines + 1.2))
    horizon = max((a.end for a in assignments), default=1)
    for a in assignments:
        k = ci.op_order[ci.op_index[a.order_id, a.op_id]]
        row = ci.machine_index[a.machine]
        ax.barh(row, a.end - a.start, left=a.start, height=0.7, color=order_color(ci, k), edgecolor="white")
        if a.end - a.start >= 0.04 * horizon:  # label only bars wide enough to hold it
            ax.text((a.start + a.end) / 2, row, f"{a.order_id}/{a.op_id}", ha="center", va="center", fontsize=7)
    ax.set_yticks(range(ci.n_machines), ci.machine_ids)
    ax.set_ylim(ci.n_machines - 0.5, -0.5)
    ax.set_xlim(0, horizon)
    ax.set_xlabel(f"time [{ci.time_unit}]")
    ax.grid(axis="x", alpha=0.3)
    if title:
        ax.set_title(title, loc="left")
    return ax
