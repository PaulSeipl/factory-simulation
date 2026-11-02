"""Plots for instances and schedules (matplotlib, dev dependency only).

- plot_orders: precedence graph of selected orders, operations in columns by depth
- plot_gantt: schedule per machine, bars colored by order (carrier operations light grey, runs dark grey,
  one bar per batch)
- plot_carriers: nesting: carriers grouped by run (load), parts colored by order
"""

from collections.abc import Callable, Iterable, Sequence

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from simulation.model.compiled import CompiledInstance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment

BOX_W, BOX_H, GAP_X, GAP_Y = 1.6, 0.8, 0.7, 0.35


def order_color(ci: CompiledInstance, k: int):
    cmap = plt.get_cmap("tab10" if len(ci.order_ids) <= 10 else "tab20")
    return cmap(k % cmap.N)


def _layout(ci: CompiledInstance, k: int) -> dict[int, tuple[float, float]]:
    """Box centers for the operations of order k: column = depth in the DAG, rows centered."""
    ops = [o for o in ci.topo_order if ci.op_orders[o] == (k,)]  # the order's own operations
    depth: dict[int, int] = {}
    for o in ops:
        depth[o] = max((depth[p] + 1 for p in ci.predecessors[o] if p in depth), default=0)
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
    orders, in_run = set(ci.order_ids), {o for g in ci.machine_groups for o in g}
    bars: dict[tuple[str, int, int], list[Assignment]] = {}  # a batch (same machine and times) is one bar
    for a in assignments:
        batched = ci.batch_capacity[ci.op_index[a.order_id, a.op_id]] > 1
        bars.setdefault((a.machine, a.start, a.end) if batched else (a.order_id, a.op_id, -1), []).append(a)
    for members in bars.values():
        a, o = members[0], ci.op_index[members[0].order_id, members[0].op_id]
        # an operation of a carrier or run serves several orders: shared colors instead of one order's color
        color = order_color(ci, ci.op_orders[o][0]) if a.order_id in orders else "0.5" if o in in_run else "0.78"
        row = ci.machine_index[a.machine]
        ax.barh(row, a.end - a.start, left=a.start, height=0.7, color=color, edgecolor="white")
        if a.end - a.start >= 0.04 * horizon:  # label only bars wide enough to hold it
            label = "+".join(m.order_id for m in members) + f"/{a.op_id}"
            ax.text((a.start + a.end) / 2, row, label, ha="center", va="center", fontsize=7)
    ax.set_yticks(range(ci.n_machines), ci.machine_ids)
    ax.set_ylim(ci.n_machines - 0.5, -0.5)
    ax.set_xlim(0, horizon)
    ax.set_xlabel(f"time [{ci.time_unit}]")
    ax.grid(axis="x", alpha=0.3)
    if title:
        ax.set_title(title, loc="left")
    return ax


def plot_carriers(inst: Instance, size: Callable[[str, str], int] | None = None, capacity: int | None = None,
                  ax: Axes | None = None, title: str | None = None) -> Axes:
    """One row per carrier, grouped by run (the run's load); one segment per part, width size(order_id, part_id)
    (default 1), colored by order; optional capacity line."""
    size = size or (lambda _k, _p: 1)
    cmap = plt.get_cmap("tab10" if len(inst.orders) <= 10 else "tab20")
    color = {o.id: cmap(i % cmap.N) for i, o in enumerate(inst.orders)}
    run_of = {cid: r.id for r in inst.runs for cid in r.carriers}
    rows = sorted(inst.carriers, key=lambda c: list(run_of).index(c.id) if c.id in run_of else len(run_of))
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 0.4 * len(rows) + 1.2))
    for row, c in enumerate(rows):
        left = 0
        for k, part in c.parts:
            w = size(k, part)
            ax.barh(row, w, left=left, height=0.7, color=color[k], edgecolor="white")
            ax.text(left + w / 2, row, f"{k} ({w})", ha="center", va="center", fontsize=7)
            left += w
        if row and run_of.get(c.id) != run_of.get(rows[row - 1].id):
            ax.axhline(row - 0.5, color="0.3", linewidth=1)  # next run
    ax.set_yticks(range(len(rows)), [f"{run_of.get(c.id, '-')} · {c.id}" for c in rows])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    if capacity is not None:
        ax.axvline(capacity, color="0.3", linestyle="--", linewidth=1)
    ax.set_xlabel("size per carrier")
    if title:
        ax.set_title(title, loc="left")
    return ax
