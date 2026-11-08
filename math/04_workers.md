# 04 Workers and work calendar

Status: design agreed with the user on 2026-11-05 (spec `docs/superpowers/specs/2026-11-05-workers-shifts-design.md`,
protocol 2026-11-05). Implemented so far (phase 1): the work calendar, tardiness in days, the format of workers
and shares, their compilation, the schedule format and the checker C11–C14 (§2–§5). DES, rules, CP-SAT and
rescheduling follow in phases 2–4. Worker shares, constraints C11–C14 and the
objective follow step by step; until then, sections marked *planned* describe the agreed design, not code.

## 1. Prose description

In the dental factory, machines run unattended for long stretches (printing, oven, milling), while workers are
needed only for parts of an operation (setup, loading, removal) or for manual steps (separation, polishing, QM,
Gegenbetten, packaging). Workers work in shifts; machines keep running at night. Without workers the model
overstates capacity: every setup and removal would be served at once and at any time of day. This component adds

- a **work calendar**: shifts 08:00–17:30 on Monday to Friday, a common lunch break of 60 minutes starting between
  12:00 and 13:00, up to 2 hours of overtime per worker and day, and a daily shipping cutoff at 12:00 (courier
  pickup); *implemented*;
- **individual workers** with qualification sets, and **worker shares** of an operation (whole, prefix, suffix);
  operations without a machine (manual steps, rest); *planned*;
- **tardiness in missed shipping days** and an objective that trades overtime against tardiness; *planned*.

## 2. Sets, parameters, variables

New symbols (central definitions in [notation.md](notation.md), section Calendar): origin $\omega$, day index
$\operatorname{day}(t)$ and minute of the day $\operatorname{mod}(t)$, working weekdays $\mathcal{D}^{\mathrm{w}}$,
shift $h^{\mathrm{S}}, h^{\mathrm{E}}$, maximum overtime $\bar O$, break window $h^{\mathrm{B}-}, h^{\mathrm{B}+}$ and
length $L^{\mathrm{B}}$, cutoff $h^{\mathrm{C}}$ and the set of cutoffs

$$\Gamma = \{\, t \ge 0 : \operatorname{day}(t) \bmod 7 \in \mathcal{D}^{\mathrm{w}},\ \operatorname{mod}(t) = h^{\mathrm{C}} \,\}.$$

Validity of a calendar (checked when an instance is loaded):

$$0 \le h^{\mathrm{S}} < h^{\mathrm{B}-} \le h^{\mathrm{B}+}, \qquad h^{\mathrm{B}+} + L^{\mathrm{B}} \le h^{\mathrm{E}}, \qquad h^{\mathrm{E}} + \bar O \le 1440, \qquad h^{\mathrm{C}} < 1440, \qquad \emptyset \ne \mathcal{D}^{\mathrm{w}} \subseteq \{0, \dots, 6\}.$$

With a calendar, every due date is a cutoff: $d_k \in \Gamma$ ([06](06_due-dates.md)); the due date is the
**shipping date**, and the order has to be packed by 12:00 of that day.

**Workers and shares** (*implemented in the format*). Workers $W$ are individuals (user: qualifications will
come; today every worker may do every step). An operation $o$ has a set of worker shares $\mathcal{A}_o$, each
$\eta \in \mathcal{A}_o$ served by exactly one worker from its qualification set $W_\eta \subseteq W$ (default
$W$); prefix and suffix may be served by different workers. Operations without a machine $O^{\emptyset}$ have a
fixed duration $p_o$ and need a share. Kinds (spec §3.2):

| Kind | Machine | Worker | Example | Format |
|---|---|---|---|---|
| manual | none | whole $[S_o, C_o)$ | polishing, separation, QM, packaging | `duration`, `worker: {whole}` |
| attended on a machine | whole | whole | setup and removal operations of print and mill runs | `CarrierStep.setup_attended`, `removal_attended` |
| attended start, machine continues | whole | prefix $[S_o, S_o + a^{\mathrm{pre}}_o)$ | (no dental step yet) | `options`, `worker: {prefix}` |
| attended start, then rest | none | prefix | Gegenbetten: work, then rest | `duration`, `worker: {prefix}` |
| attended start and end, no gap | whole | prefix and suffix $[C_o - a^{\mathrm{suf}}_o, C_o)$ | oven: loading and removal inside the fixed program, one share per run | `CarrierStep.worker: {prefix, suffix}` |

Rest without any resource is the unattended remainder $p_o - a^{\mathrm{pre}}_o$ of a machine-less operation; it
may last longer than needed (minimum), so successors only need $S_{o'} \ge C_o$ as before (C3): no time lag on
edges (revises protocol 2026-11-04 (2), block 2).

*Planned:* shift ends $e_{w,d}$, overtime $O_{w,d}$ (symbols to be added to `notation.md` with their step); break
starts $b_{w,d}$ and $y_{\eta,w}$, $I_\eta$ are in `notation.md` since 2026-11-08.

## 3. Constraints

*Implemented in the checker* (planners follow in phases 2–4). Let $y_{\eta,w} \in \{0,1\}$ be 1 iff worker $w$
serves share $\eta$, and $I_\eta = [\underline{I}_\eta, \overline{I}_\eta)$ the worker time of the share: whole
$[S_o, C_o)$, prefix $[S_o, S_o + a^{\mathrm{pre}}_o)$, suffix $[C_o - a^{\mathrm{suf}}_o, C_o)$. Members of one
oven batch (C10) form one run and count as one share.

(C1') Machine assignment, extended: an operation without machine has none, and its duration is fixed.
$$\sum_{m \in M_o} x_{o,m} = 0,\quad C_o - S_o = p_o \qquad \forall o \in O^{\emptyset}$$

(C11) Every share is served by exactly one qualified worker; the members of a batch by the same workers.
$$\sum_{w \in W_\eta} y_{\eta,w} = 1,\qquad y_{\eta,w} = 0 \ \ \forall w \notin W_\eta \qquad \forall o \in O,\ \eta \in \mathcal{A}_o$$

(C12) A worker does one thing at a time (no preemption, half-open intervals).
$$y_{\eta,w} = y_{\eta',w} = 1 \ \Rightarrow\ \overline{I}_\eta \le \underline{I}_{\eta'} \ \lor\ \overline{I}_{\eta'} \le \underline{I}_\eta \qquad \forall w \in W,\ \eta \ne \eta'$$

(C13) With a calendar, every share lies within the shift window of one working day; machines run at any time.
$$\operatorname{day}(\underline{I}_\eta) \bmod 7 \in \mathcal{D}^{\mathrm{w}},\qquad \operatorname{mod}(\underline{I}_\eta) \ge h^{\mathrm{S}},\qquad \overline{I}_\eta - \operatorname{start}(\operatorname{day}(\underline{I}_\eta)) \le h^{\mathrm{E}} + \bar O \qquad \forall \eta$$
where $\operatorname{start}(d)$ is the time of 00:00 on day $d$; the window ends before midnight (calendar
validity, §2), so a share cannot cross into the next day.

(C14) With a calendar, a worker who has a share on day $d$ has exactly one break $b_{w,d}$ that day, in the
window, and no share overlaps it.
$$\operatorname{mod}(b_{w,d}) \in [h^{\mathrm{B}-}, h^{\mathrm{B}+}],\qquad y_{\eta,w} = 1 \Rightarrow I_\eta \cap [b_{w,d}, b_{w,d} + L^{\mathrm{B}}) = \emptyset$$

**Breaks in a revised plan** (against a snapshot at $t$, [05](05_rescheduling-frozen-part.md); the breaks
$\hat b_{w,d}$ started by $t$ are part of the snapshot):

(C6$^b$) A break not started is not planned before $t$: $b_{w,d} \ge t$ for every break not in the snapshot.

(C7$^b$) Started breaks are unchanged: $b_{w,d} = \hat b_{w,d}$ for every break of the snapshot. They are realized
history and are not checked against the window (like C2 for frozen operations).

(C14$^f$) Forced postponement: a break not started may start after the window only if a started share of the
worker covers the latest break start and the break starts exactly at that share's expected end:
$$b_{w,d} > \operatorname{start}(d) + h^{\mathrm{B}+} \ \Rightarrow\ \exists \eta \text{ frozen}: y_{\eta,w} = 1,\ \underline{I}_\eta < \operatorname{start}(d) + h^{\mathrm{B}+} < \overline{I}_\eta = b_{w,d}$$
It arises only from disturbances (an overrun or a late start of that share; user 2026-11-08: a planner must never
cause it, forced by the frozen part it is the shortest delay). $I_\eta$ of a frozen share uses the snapshot's
(expected) times and the planned share length, i.e. what a planner sees.

Overtime $O_{w,d} = \max(0,\ \max_\eta \overline{I}_\eta - \operatorname{start}(d) - h^{\mathrm{E}})$ is bounded by
C13 ($\le \bar O$) and otherwise a cost (§4, planned), not a constraint. The common break (same start for all) is a
soft goal (spread penalty, §4), not a constraint. Rest without resource needs no constraint (C3 suffices, §2).

## 4. Objective function

*Planned* (spec §4–5): tardiness of order $k$ in missed shipping days,

$$T_k = \left|\{\, c \in \Gamma : d_k \le c < C_k \,\}\right|,$$

so a completion by the cutoff of the due date is on time, by the next working day's cutoff 1 day late, and a
missed Friday cutoff shipped on Monday 1 day late. *Implemented* as (O1') in [06](06_due-dates.md) §4 (evaluation,
CP-SAT, spread, metric `tardy_days`). The weighted overtime term and the further levels (spec §5) are *planned*.

## 5. Implementation in code

- `simulation.model.instance.Calendar` (Pydantic, `frozen`, `extra="forbid"`), field `Instance.calendar`
  (default `None`: no calendar, behavior as before); schema 0.6 (`schemas/instance-0.6.json`). Validation as in
  §2; a calendar requires `time_unit == "min"`; with a calendar every due date must be a cutoff.
- `simulation.calendar`: `minute_of_day`, `day_index`, `day_start`, `is_working_day`, `cutoffs(cal, until)`,
  `next_cutoff(cal, t)`, `days_late(cal, due, end)`. Plain functions on any object with the calendar's fields,
  so the compiled form can use them without Pydantic in the hot path: `CompiledInstance.calendar` is a
  `calendar.WeekCalendar` (frozen slots dataclass, same fields), `None` without a calendar.
- `calendar.next_start(cal, t, length, latest)` (phase 3, task 1, for the dispatching rule): the earliest
  $s \ge t$ such that $[s, s + \text{length})$ lies in one of the two parts of a working day's shift,
  $[h^{\mathrm{S}}, h^{\mathrm{B}-})$ or $[h^{\mathrm{B}-} + L^{\mathrm{B}}, \text{latest})$, i.e. with the break at
  its earliest start (the rule's fixed 12:00 break); `latest` is $h^{\mathrm{E}}$ without overtime or
  $h^{\mathrm{E}} + \bar O$ with it. A share longer than both parts raises `ValueError` (it cannot be planned
  without overtime, or at all). Tests in `tests/test_calendar.py` (by hand: morning, ending exactly at 12:00,
  pushed past the break, starting in the break, next day, with overtime, Friday → Monday, weekend, before shift
  start, a 5-hour share only in the long afternoon; the too-long case).
- Format of workers (schema 0.6, still unpublished): `Instance.workers`; `WorkerShare(whole, prefix, suffix,
  qualified)` with exactly one of whole / prefix + suffix > 0; `Operation.duration` (exclusive with `options`,
  needs `Operation.worker`); `Operation.worker` only on order operations; `CarrierStep.worker` for the main
  operation of a carrier step (a batch step: one share per run), `setup_attended` / `removal_attended` (need
  `setup` / `removal`). Validation: duplicate worker IDs, worker IDs equal to machine IDs, unknown qualified
  workers, shares without workers, $a^{\mathrm{pre}}_o + a^{\mathrm{suf}}_o$ longer than the shortest machine
  option (shortcut: a shorter run estimate is left to the checker), machine-less carrier operations (not
  supported). `operation_graph` gives machine-less operations no machine options; `lead_time_bound` counts their
  duration. Tests: `tests/test_worker_format.py` (one negative test per rule).
- Compilation: `operation_graph` attaches the shares to each node (order operations: `Operation.worker`; carrier
  operations: the step's `worker`; run setup / removal: a whole share if `setup_attended` / `removal_attended`;
  run main operation: the step's `worker`; every member of an oven batch carries the share, the checker counts it
  once per run). `CompiledInstance` gets `worker_ids`, `fixed_duration` (op idx → $p_o$ for $o \in O^{\emptyset}$,
  whose `options` are empty) and `shares` (op idx → tuple of `Share(kind, length, workers)` with kind whole,
  prefix or suffix, qualified worker idxs). `share_interval(share, start, end)` gives the worker time: whole
  $[S_o, C_o)$, prefix $[S_o, S_o + a^{\mathrm{pre}}_o)$, suffix $[C_o - a^{\mathrm{suf}}_o, C_o)$; stored
  independent of the duration, so it holds on every machine. `static_horizon` counts fixed durations.
- Schedule format: `Assignment.machine` may be `None` (operation without machine; still required, so it is
  never omitted by accident), `Assignment.workers` (one worker ID per share, in the order of
  `CompiledInstance.shares`; default empty), `Break(worker, start)` and `Schedule.breaks` (planned breaks; the
  length $L^{\mathrm{B}}$ comes from the calendar). The planner decides the break start $b_{w,d}$, so breaks are
  part of the plan. Old schedules stay valid (defaults). Tests: `tests/test_worker_schedule.py`.
- Checker (`simulation.check.feasibility`, independent of the planners): `check_schedule(ci, assignments,
  snapshot=None, breaks=())`; machine-less operations: machine `None` required (C11), duration $p_o$ (C2), not in
  the machine sweep (C5/C9/C10); `worker_shares_wrong` (C11 count, known, qualified), `worker_overlaps` (C12 sweep
  per worker; C11 for a batch with different workers per member), `outside_shift` (C13), `break_violations`
  (C14: unknown worker, window, two breaks a day, missing break on a day with shares, share during a break). Share
  intervals via `share_interval`; a batch's shares count once (first member). Mini instance
  `data/instances/toy-workers.json` with the hand plan in `tests/test_workers_checker.py` (feasible, on time;
  one test per constraint with a single change; a share ending at the break start is allowed; the worker is free
  during the Gegenbetten rest; oven batch shares count once; without a calendar C13/C14 are not checked).
- DES (phase 2, task 1): shares executed in the planned order per worker, soft suffix with OVERSTAY, machine-less
  operations; realized durations per [22](22_scenarios.md); details in [13](13_des.md) §3. Tests
  `tests/test_des_workers.py`: zero-disturbance on `toy-workers.json` and on the oven batch with attended mill
  runs; late worker on a prefix; prefix scaling with the machine time; fixed rest; oven removal delayed by a busy
  worker (overstay 2, by hand); disturbed runs pass the checker (C13/C14 excluded until the calendar task).
- DES (phase 2, task 2): shift window, breaks (planned, postponed individually), overruns finished; see
  [13](13_des.md) §3. `Assignment.share_lengths` (realized share lengths, set by the DES; empty in plans) is used
  by the checker for the worker intervals, since realized shares scale with the disturbance; a wrong count is C11.
  Tests `tests/test_des_calendar.py` (by hand: late share with 10 minutes of overtime; share not fitting → next
  working day, Friday → Monday; overrun finished; break postponed from 12:00 to 12:20 while busy; no share starts
  during a break; 10 disturbed seeds leave only C2, overruns and postponed breaks).
- DES (phase 2, task 3): swap rule ([13](13_des.md) §3). Tests `tests/test_des_swap.py` (by hand: B packs k2 while A
  is still on Gegenbetten; no swap when B's next share starts 5 minutes too early, swap when it fits exactly;
  Gegenbetten (only A) is not swapped to B; W2 unloads the oven for a busy W1 (no overstay) and sets up the mill
  run; no swap without disturbance; the current plan shows the actual worker). The one-worker overstay case
  stays in `tests/test_des_workers.py`.
- Snapshot and metrics (phase 2, task 4): `FrozenOperation.workers` (started shares; `None` for a pending oven
  removal), C7 compares them; metrics `overstay`, `swaps` and with a calendar `overtime`
  ($\sum_{w,d} \max(0,\ \text{last share end on day } d - h^{\mathrm{E}})$), `overruns`, `break_postponement`,
  `break_spread`
  ([23](23_metrics.md) M7). Tests `tests/test_worker_snapshot_metrics.py`.
- Dispatching (phase 3, task 2, no calendar yet): `planners.dispatching.dispatch` books every share into a gap of
  a qualified worker (least worker load $V_w$, then lowest index), waits for the workers in the candidate's
  earliest start, books a batch's shares once, places run parts one after the other, and schedules machine-less
  operations; details and hand examples in [11](11_dispatching-rules.md) §3, §5. Tests
  `tests/test_dispatching_workers.py`.
- Breaks through rescheduling, task 1 (plan `docs/superpowers/plans/2026-11-08-breaks-rescheduling.md`):
  `Snapshot.breaks` (breaks started by $t$ with their realized start, filled by `snapshot(ci, plan, state, breaks)`
  from the DES break state; `Simulation.snapshot()` passes its planned breaks). Checker with a snapshot:
  `breaks_changed` (C7$^b$ started break missing or moved, C6$^b$ a new break before $t$); `break_violations` skips
  the window check for the snapshot's breaks and accepts a forced postponement (C14$^f$, via the frozen share
  intervals `_frozen_worker_time`). Tests `tests/test_snapshot_breaks.py` (by hand: A's break realized at 12:20
  after a slow Gegenbetten prefix, snapshot at 12:30; a forced postponement at the expected end 311 of a
  packaging overrunning past 13:00, snapshot at 13:10; a realized break at 13:45 kept as history; negative: moved
  started break → C7, new break before $t$ → C6, forced break later than the share end → C14, no frozen share
  covering 13:00 → C14, late break without snapshot → C14).
- Dispatching from a snapshot (phase 3, task 4): started shares of frozen operations keep and occupy their workers
  (C7), a pending removal gets a worker by the rule's choice. With a calendar it raises `NotImplementedError`:
  breaks do not travel through rescheduling yet (`Snapshot` has no breaks, the planner interface returns only
  assignments, `control.rescheduling.execute` starts the `Simulation` without breaks, so on a calendar instance
  its checks would report missing breaks, C14).
- Dispatching with the calendar (phase 3, task 3): shares only within the shift without overtime and outside the
  fixed 12:00 break (`calendar.next_start` with latest $= h^{\mathrm{E}}$); `default_breaks(ci, plan)` gives the
  plan's breaks (C14); machines run overnight, attended removals wait for the morning. See
  [11](11_dispatching-rules.md) §3.
- Guards (until their phase): CP-SAT (`solve`) and repair (`repair`) raise `NotImplementedError` for instances with workers or machine-less operations
  (`compiled.reject_workers`). Tests: `tests/test_worker_compile.py` (shares of the three order kinds, of the
  oven batch and the attended mill run, intervals, instances without workers unchanged, horizon, 4 guard cases).
- Tests: `tests/test_calendar.py` (arithmetic by hand: Monday 12:00 is $t = 240$, Tuesday 00:00 is $t = 960$,
  weekend skipped, Friday 12:01 → Monday 12:00; one negative test per validation rule).

## 6. Assumptions and open points

- $t = 0$ is Monday 08:00 by default (mine); no holidays; one shift pattern for all workers (spec, non-goals).
- The cutoff is a working-day event: no courier on weekends (user: a missed Friday cutoff shipped on Monday is
  1 day late).
- Real attended shares and durations from Fidentis: placeholders for now (user).
- **19:30 is hard in the plan, soft in execution** (user, 2026-11-06): C13 forbids planned shares past
  $h^{\mathrm{E}} + \bar O$; in the DES a share that started in time but runs longer is finished and counted as an
  overrun (metric `overruns`, [23](23_metrics.md) M7), not interrupted. Interrupting it would create a preempted
  operation, which no planner handles; out of scope.
- **Fallback if the operation model is too complex for the planners (user, 2026-11-05):** the five kinds
  (machine and/or worker, whole / prefix / suffix, unattended rest) may be too much for CP-SAT or the GA. Two
  downgrades are kept open: (a) **prefix and unattended only** (no suffix; the oven removal then becomes its own
  operation, waiting allowed); (b) **every operation fully attended by its resources**: machine and worker, worker
  only, or machine only, with no attended/unattended split inside an operation (setups, loading and removal as
  own operations). Decide after the CP-SAT step (phase 4) by solve times on the dental example; the format keeps
  the general form, so a downgrade is a restriction in the generator, not a format change.
- **[CHECK WITH FIDENTIS]** oven overstay as the highest objective level, oven blocked while parts wait (spec §5).
- A running **prefix** is visible in the snapshot only with its planned length: if it overruns past 13:00, its
  interval $I_\eta$ ends before 13:00, so C14$^f$ does not accept the forced break (mine, 2026-11-08). Whole shares
  carry the expected end of their operation and work. Upgrade: realized or expected share ends in
  `FrozenOperation`, if a disturbed run hits it (Task 4 sweep will show).

## 7. Sources

- Machine unavailability periods arising from shift patterns; setups that cannot be interrupted and are
  immediately followed by processing: Lunardi, W. T., Birgin, E. G., Laborie, P., Ronconi, D. P., & Voos, H.
  (2020). Mixed integer linear programming and constraint programming models for the online printing shop
  scheduling problem. *Computers & Operations Research*, 123, 105020. https://doi.org/10.1016/j.cor.2020.105020
  (Zotero `8Z7BQGIF`, PDF p. 2; metadata checked in Zotero).
- Multiple necessary resources per operation, each chosen from its own set, all occupied for the whole duration:
  Kasapidis, G. A., Dauzère-Pérès, S., Paraskevopoulos, D. C., Repoussis, P. P., & Tarantilis, C. D. (2023). On the
  multiresource flexible job-shop scheduling problem with arbitrary precedence graphs. *Production and Operations
  Management*, 32(7), 2322–2330. https://doi.org/10.1111/poms.13977 (Zotero `E58NU6WE`, PDF p. 2 = p. 2323;
  metadata checked in Zotero). The partial occupation planned here (prefix/suffix) is **own modeling**.
- Calendar, break and overtime formulation: **own modeling**.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-05 | uncommitted | Component created: design summary; work calendar implemented (`Calendar`, `simulation.calendar`, schema 0.6, due dates on cutoffs). |
| 2026-11-06 | uncommitted | DES: shares, calendar, swap rule (phase 2, tasks 1–3). |
| 2026-11-06 | uncommitted | Dispatching rule with shares and machine-less operations, no calendar (phase 3, task 2). |
| 2026-11-07 | uncommitted | Dispatching rule with the calendar and `default_breaks` (phase 3, task 3). |
| 2026-11-08 | uncommitted | Dispatching from a snapshot with workers, no calendar (phase 3, task 4); open point: breaks through rescheduling. |
| 2026-11-08 | uncommitted | Breaks in the snapshot; (C6$^b$), (C7$^b$), (C14$^f$) in the checker; symbols $y_{\eta,w}$, $I_\eta$, $b_{w,d}$, $\hat b_{w,d}$ in `notation.md`. |
| 2026-11-05 | uncommitted | Constraints (C1'), (C11)–(C14) and the checker; mini instance `toy-workers.json`. |
| 2026-11-05 | uncommitted | Schedule format: machine optional, workers per assignment, breaks in the schedule. |
| 2026-11-05 | uncommitted | Compilation of workers and shares (`Share`, `share_interval`, `fixed_duration`), guards in DES, rules, CP-SAT, repair; fallback options (prefix + unattended only, or fully attended operations) recorded in §6. |
| 2026-11-05 | uncommitted | Worker shares and machine-less operations in the format; table of the kinds; symbols $W$, $\mathcal{A}_o$, $W_\eta$, $a^{\mathrm{pre}}_o$, $a^{\mathrm{suf}}_o$, $O^{\emptyset}$. |
| 2026-11-05 | uncommitted | Tardiness in missed shipping days implemented ([06](06_due-dates.md) (O1')); `CompiledInstance.calendar` (`WeekCalendar`). |
