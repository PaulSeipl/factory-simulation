"""Plots for instances and schedules (matplotlib, dev dependency only).

- plot_orders: precedence graph of selected orders, operations in columns by depth
- plot_gantt: schedule per machine, bars colored by order (carrier operations light grey, runs dark grey,
  one bar per batch)
- plot_carriers: nesting: carriers grouped by run (load), parts colored by order
"""

from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

from simulation.calendar import DAY, day_index, day_start, is_working_day, minute_of_day
from simulation.check.feasibility import worker_intervals
from simulation.model.compiled import CompiledInstance
from simulation.model.instance import Instance
from simulation.model.schedule import Assignment, Break

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


# --- worker plans on the calendar (math/04_workers.md) -------------------------------------------------------------
# state colors (dataviz reference palette): attended = aqua, unattended = its light tint with an aqua edge,
# overtime = orange, break = grey; nights and non-working days hatched, the overtime window tinted
ATTENDED, UNATTENDED, OVERTIME, BREAK = "#1baf7a", "#d3efe4", "#eb6834", "#8a8984"
STEP_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
# color_by="step" fails the dataviz validator for all pairs beyond 3 steps (bars side by side in any pairing);
# color_by="machine" uses the first 3 slots (validated all-pairs) and a neutral ink for machine-less work
MACHINE_COLORS, NO_MACHINE = STEP_COLORS[:3], "#dcdbd6"  # light neutral, outlined: apart from the break grey
COLOR_BY = ("state", "step", "machine")
ROWS = ("resources", "workers", "machines", "orders")


class Bar(NamedTuple):
    row: str
    start: int
    end: int
    kind: str  # attended, unattended, overtime, break
    label: str
    op: str  # operation id: the key of the step colors
    inner: bool = False  # worker time drawn inside the bar of its operation (half height)
    machine: str = ""  # machine of the operation ("" for none): the key of the machine colors


def shift_bars(ci: CompiledInstance, schedule: Iterable[Assignment], breaks: Iterable[Break] = (),
               rows: str = "resources") -> tuple[list[str], list[Bar]]:
    """Rows and bars of a worker plan. rows: "resources" (machines, workers, then "rest" for the unattended time of
    machine-less operations), "workers" (labels name the machine), "machines" (machines and rest: attended
    machine-less operations such as QM are missing) or "orders" (labels name machine and workers).
    Worker time past the day's shift end is overtime."""
    if rows not in ROWS:
        raise ValueError(f"rows must be one of {ROWS}")
    cal = ci.calendar
    by_op = {ci.op_index[a.order_id, a.op_id]: a for a in schedule}
    shares = worker_intervals(ci, by_op)
    bars: list[Bar] = []

    def attended(row, s, e, label, op, inner=False, machine=""):  # split at the shift end of the share's day
        cut = e if cal is None else max(s, min(e, day_start(cal, day_index(cal, s)) + cal.shift_end))
        bars.extend(Bar(row, a, b, k, label if k == "attended" else "", op, inner, machine)
                    for a, b, k in ((s, cut, "attended"), (cut, e, "overtime")) if a < b)

    for o, a in by_op.items():
        # an operation with unattended time (machine, prefix or suffix share, rest) is an outlined bar with its
        # worker time inside; a whole-share operation is worker time only
        unattended = a.machine is not None or any(s.kind != "whole" for s in ci.shares[o]) or not ci.shares[o]
        if rows == "workers" or (rows != "orders" and not unattended):
            continue
        row = a.order_id if rows == "orders" else a.machine or "rest"
        label = f"{a.op_id} {'+'.join(dict.fromkeys(a.workers))}" if rows == "orders" else f"{a.order_id} {a.op_id}"
        if unattended:
            bars.append(Bar(row, a.start, a.end, "unattended", label, a.op_id, machine=a.machine or ""))
        for s, e, _ in (iv for w in shares.values() for iv in w if iv[2] == o):
            attended(row, s, e, "" if unattended else label, a.op_id, inner=unattended, machine=a.machine or "")
    if rows in ("resources", "workers"):
        for w, intervals in shares.items():
            for s, e, o in intervals:
                a = by_op[o]
                at = f"@{a.machine}" if rows == "workers" and a.machine else ""
                attended(w, s, e, f"{a.order_id} {a.op_id}{at}", a.op_id, machine=a.machine or "")
        bars += [Bar(b.worker, b.start, b.start + cal.break_length, "break", "", "") for b in breaks]
    present = {b.row for b in bars}
    if rows == "orders":
        names = list(dict.fromkeys(a.order_id for a in by_op.values()))
    else:
        names = [*(m for m in ci.machine_ids if rows != "workers"), *(w for w in ci.worker_ids if rows != "machines")]
        names = [n for n in names if n in present] + (["rest"] if "rest" in present else [])
    return names, bars


def _colors(bar: Bar, color_by: str, steps: dict[str, str]) -> dict:
    if bar.kind == "break":
        return {"color": BREAK}
    if color_by != "state":
        c = steps[_key(bar, color_by)]
        if bar.kind == "unattended":
            return {"facecolor": (*to_rgb(c), 0.18), "edgecolor": c}
        return {"facecolor": c, "hatch": "xx" if bar.kind == "overtime" else None,
                "edgecolor": "0.35" if c == NO_MACHINE else "white"}
    return {"unattended": {"facecolor": UNATTENDED, "edgecolor": ATTENDED}, "attended": {"color": ATTENDED},
            "overtime": {"color": OVERTIME}}[bar.kind]


def _windows(cal, t0: int, t1: int) -> list[tuple[int, int]]:
    """[shift start, shift end + max overtime) of every working day that meets [t0, t1)."""
    out = []
    for d in range(day_index(cal, t0), day_index(cal, max(t0, t1 - 1)) + 1):
        ds = day_start(cal, d)
        if is_working_day(cal, d) and ds + cal.shift_start < t1 and ds + cal.shift_end + cal.max_overtime > t0:
            out.append((ds + cal.shift_start, ds + cal.shift_end + cal.max_overtime))
    return out


def _compressed(points: list[tuple[float, float]]) -> Callable[[float], float]:
    """Piecewise linear time axis through (t, coordinate) breakpoints: nights and days off squeezed."""
    ts, xs = zip(*points, strict=True)
    return lambda t: float(np.interp(t, ts, xs))


def _calendar_background(ax: Axes, cal, windows: list[tuple[int, int]], t0: int, t1: int,
                         f: Callable[[float], float], vertical: bool = False) -> None:
    """The gaps between the windows (nights, days off) hatched, the overtime window tinted, cutoffs dashed; f maps
    t to the axis."""
    span = ax.axhspan if vertical else ax.axvspan
    edges = [t0, *(t for w in windows for t in w), t1]
    for a, b in zip(edges[::2], edges[1::2], strict=True):
        if a < b:
            span(f(a), f(b), facecolor="0.93", edgecolor="0.75", hatch="///", linewidth=0, zorder=0)
    line = ax.axhline if vertical else ax.axvline
    for a, b in windows:
        ds = day_start(cal, day_index(cal, a))
        span(f(ds + cal.shift_end), f(b), color=OVERTIME, alpha=0.1, linewidth=0, zorder=0)
        line(f(ds + cal.cutoff), color="#d03b3b", linestyle="--", linewidth=1, zorder=1)


def _legend(ax: Axes, color_by: str, steps: dict[str, str], **kwargs) -> None:
    handles = [Patch(facecolor=UNATTENDED, edgecolor=ATTENDED, label="unattended"),
               Patch(color=ATTENDED, label="attended"), Patch(color=OVERTIME, label="overtime"),
               Patch(color=BREAK, label="break")]
    if color_by != "state":
        handles = [Patch(facecolor=c, edgecolor="0.35" if c == NO_MACHINE else c, label=key)
                   for key, c in steps.items()] + [
            Patch(facecolor="white", edgecolor="0.3", label="unattended (light)"),
            Patch(facecolor="white", edgecolor="0.3", hatch="xx", label="overtime"), Patch(color=BREAK, label="break")]
    handles += [Patch(facecolor="0.93", edgecolor="0.75", hatch="///", label="night / day off"),
                Line2D([], [], color="#d03b3b", linestyle="--", label="cutoff")]
    ax.legend(handles=handles, **kwargs)


def _key(bar: Bar, color_by: str) -> str:
    return bar.op if color_by == "step" else bar.machine or "no machine"


def _step_colors(ci: CompiledInstance, bars: list[Bar], color_by: str) -> dict[str, str]:
    """Key (step or machine) -> color, in a fixed order: steps as they appear, machines as in the instance."""
    if color_by not in COLOR_BY:
        raise ValueError(f"color_by must be one of {COLOR_BY}")
    if color_by == "state":
        return {}
    if color_by == "step":
        keys, palette = list(dict.fromkeys(b.op for b in bars if b.op)), STEP_COLORS
    else:
        used = {b.machine for b in bars if b.kind != "break"}
        keys, palette = [m for m in ci.machine_ids if m in used], MACHINE_COLORS
    if len(keys) > len(palette):
        raise ValueError(f"{len(keys)} {color_by}s, but only {len(palette)} colors: use color_by='state'")
    out = dict(zip(keys, palette, strict=False))
    return out | ({"no machine": NO_MACHINE} if color_by == "machine" and "" in used else {})


def plot_shifts(ci: CompiledInstance, schedule: Iterable[Assignment], breaks: Iterable[Break] = (),
                rows: str = "resources", color_by: str = "state", night: int = 60, ax: Axes | None = None,
                title: str | None = None) -> Axes:
    """Horizontal Gantt of a worker plan over the calendar; rows as in shift_bars; color_by "state", "step" or
    "machine" (the machine a share serves).
    The working windows (shift start to shift end + max overtime) are to scale; each gap between them (a night,
    a weekend) is squeezed to `night` minutes, also when an operation runs through it."""
    names, bars = shift_bars(ci, schedule, breaks, rows)
    steps, cal = _step_colors(ci, bars, color_by), ci.calendar
    # CP-SAT books breaks over its whole horizon: the range follows the operations
    t0, t1 = min(b.start for b in bars), max(b.end for b in bars if b.kind != "break")
    windows: list[tuple[int, int]] = []
    f: Callable[[float], float] = float
    if cal is not None:
        windows = _windows(cal, t0, t1)
        t0, t1 = min(t0, windows[0][0]), max(t1, windows[-1][1])
        points, x = [(t0, 0.0)], float(min(night, windows[0][0] - t0))
        for a, b in windows:
            points += [(a, x), (b, x + b - a)]
            x += b - a + night
        f = _compressed([*points, (t1, x - night + min(night, t1 - windows[-1][1]))])
    if ax is None:
        _, ax = plt.subplots(figsize=(14, 0.5 * len(names) + 1.6))
    if cal is not None:
        _calendar_background(ax, cal, windows, t0, t1, f)
    y = {n: i for i, n in enumerate(names)}
    for b in bars:
        x0, x1 = f(max(b.start, t0)), f(min(b.end, t1))
        if b.row not in y or x0 >= x1:
            continue
        # worker time inside an operation bar: lower half; the operation's label: upper half
        ax.barh(y[b.row] + 0.17 * b.inner, x1 - x0, left=x0, height=0.36 if b.inner else 0.7,
                linewidth=1, zorder=2, **_colors(b, color_by, steps))
        if b.label and x1 - x0 >= 0.03 * (f(t1) - f(t0)):
            ax.text((x0 + x1) / 2, y[b.row] - 0.17 * (b.kind == "unattended"), b.label, ha="center",
                    va="center", fontsize=7, zorder=3)
    ax.set_yticks(range(len(names)), names)
    ax.set_ylim(len(names) - 0.5, -0.5)
    ax.set_xlim(f(t0), f(t1))
    if cal is not None:  # hours of every window, day names above
        ticks = [t for a, b in windows for t in range(a, b, 120)]
        ax.set_xticks([f(t) for t in ticks], [f"{minute_of_day(cal, t) // 60}" for t in ticks])
        top = ax.secondary_xaxis("top")
        top.set_xticks([f((a + b) / 2) for a, b in windows], [DAYS[day_index(cal, a) % 7] for a, _ in windows])
        top.tick_params(length=0)
        ax.set_xlabel(f"hour of the day (nights and days off squeezed to {night} min)")
    ax.grid(axis="x", alpha=0.3)
    _legend(ax, color_by, steps, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=10, fontsize=8, frameon=False)
    if title:
        ax.set_title(title, loc="left", pad=22)
    return ax


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def plot_days(ci: CompiledInstance, schedule: Iterable[Assignment], breaks: Iterable[Break] = (), days: int = 3,
              rows: str = "resources", color_by: str = "state", night: int = 30, title: str | None = None) -> Figure:
    """Calendar view: one column per day from the day of t = 0 (days off included), one lane per row, time of day
    downward. The working window is to scale; the time before and after it is squeezed to `night` minutes each.
    Bars crossing midnight are split."""
    cal = ci.calendar
    if cal is None:
        raise ValueError("plot_days needs an instance with a calendar")
    names, bars = shift_bars(ci, schedule, breaks, rows)
    steps, x = _step_colors(ci, bars, color_by), {n: i for i, n in enumerate(names)}
    a, b = cal.shift_start, cal.shift_end + cal.max_overtime  # minutes of the day
    f = _compressed([(0, 0.0), (a, night), (b, night + b - a), (DAY, 2 * night + b - a)])
    fig, axes = plt.subplots(1, days, figsize=(2.2 + 0.75 * len(names) * days, 9), sharey=True, squeeze=False)
    d0 = day_index(cal, 0)
    for ax, d in zip(axes[0], range(d0, d0 + days), strict=True):
        ds = day_start(cal, d)

        def fd(t, ds=ds):
            return f(t - ds)

        _calendar_background(ax, cal, _windows(cal, ds, ds + DAY), ds, ds + DAY, fd, vertical=True)
        for bar in bars:
            s, e = max(bar.start, ds), min(bar.end, ds + DAY)
            if bar.row not in x or s >= e:
                continue
            # worker time inside an operation bar: right half; the operation's label: left half
            ax.bar(x[bar.row] + 0.2 * bar.inner, fd(e) - fd(s), bottom=fd(s), width=0.4 if bar.inner else 0.8,
                   linewidth=1, zorder=2, **_colors(bar, color_by, steps))
            if bar.label and fd(e) - fd(s) >= 25:
                ax.text(x[bar.row] - 0.2 * (bar.kind == "unattended"), (fd(s) + fd(e)) / 2, bar.label,
                        rotation=90, ha="center", va="center", fontsize=7, zorder=3)
        ax.set_xticks(range(len(names)), names, rotation=90)
        ax.set_xlim(-0.5, len(names) - 0.5)
        ax.set_ylim(f(DAY), 0)
        ax.set_title(DAYS[d % 7], fontsize=10)
        ax.grid(axis="y", alpha=0.3)
    ticks = [0, *range(a, b, 60), b, DAY]
    axes[0][0].set_yticks([f(m) for m in ticks], [f"{m // 60}:{m % 60:02}" for m in ticks])
    _legend(fig, color_by, steps, loc="lower center", ncol=8, fontsize=8, frameon=False)
    if title:
        fig.suptitle(title, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


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
