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
shift $h^{\mathrm{S}}, h^{\mathrm{E}}$, maximum overtime $\overline{\mathrm{ot}}$, break window $h^{\mathrm{B}-}, h^{\mathrm{B}+}$ and
length $p^{\mathrm{br}}$, cutoff $h^{\mathrm{C}}$ and the set of cutoffs

$$\Gamma = \{\, t \ge 0 : \operatorname{day}(t) \bmod 7 \in \mathcal{D}^{\mathrm{w}},\ \operatorname{mod}(t) = h^{\mathrm{C}} \,\}.$$

Validity of a calendar (checked when an instance is loaded):

$$0 \le h^{\mathrm{S}} < h^{\mathrm{B}-} \le h^{\mathrm{B}+}, \qquad h^{\mathrm{B}+} + p^{\mathrm{br}} \le h^{\mathrm{E}}, \qquad h^{\mathrm{E}} + \overline{\mathrm{ot}} \le 1440, \qquad h^{\mathrm{C}} < 1440, \qquad \emptyset \ne \mathcal{D}^{\mathrm{w}} \subseteq \{0, \dots, 6\}.$$

With a calendar, every due date is a cutoff: $d_k \in \Gamma$ ([06](06_due-dates.md)); the due date is the
**shipping date**, and the order has to be packed by 12:00 of that day.

**Workers and shares** (*implemented in the format*). Workers $W$ are individuals (user: qualifications will
come; today every worker may do every step). An operation $o$ has a set of worker shares $\mathcal{A}_o$, each
$\eta \in \mathcal{A}_o$ served by exactly one worker from the qualification set $W_o \subseteq W$ of the operation
(default $W$; one set for all shares of $o$, as `WorkerShare.qualified`; Berti et al. (2021) write $W_k$ per
machine, here per operation because machine-less operations have no machine and qualification follows the step);
prefix and suffix may be served by different workers. Operations without a machine $O^{\emptyset}$ have a
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

*Planned:* shift ends $e_{z,\nu}$, overtime $\mathrm{ot}_{z,\nu}$ (symbols to be added to `notation.md` with their step); break
starts $\mathrm{br}_{z,\nu}$ and $v_{\eta,z}$, $I_\eta$ are in `notation.md` since 2026-11-08.

## 3. Constraints

*Implemented in the checker* (planners follow in phases 2–4). Let $v_{\eta,z} \in \{0,1\}$ be 1 iff worker $z$
serves share $\eta$, and $I_\eta = [\underline{I}_\eta, \overline{I}_\eta)$ the worker time of the share: whole
$[S_o, C_o)$, prefix $[S_o, S_o + a^{\mathrm{pre}}_o)$, suffix $[C_o - a^{\mathrm{suf}}_o, C_o)$. Members of one
oven batch (C10) form one run and count as one share.

(C1') Machine assignment, extended: an operation without machine has none, and its duration is fixed.
$$\sum_{m \in M_o} x_{o,m} = 0,\quad C_o - S_o = p_o \qquad \forall o \in O^{\emptyset}$$

(C11) Every share is served by exactly one qualified worker; the members of a batch by the same workers.
$$\sum_{z \in W_o} v_{\eta,z} = 1,\qquad v_{\eta,z} = 0 \ \ \forall z \notin W_o \qquad \forall o \in O,\ \eta \in \mathcal{A}_o$$

(C12) A worker does one thing at a time (no preemption, half-open intervals).
$$v_{\eta,z} = v_{\eta',z} = 1 \ \Rightarrow\ \overline{I}_\eta \le \underline{I}_{\eta'} \ \lor\ \overline{I}_{\eta'} \le \underline{I}_\eta \qquad \forall z \in W,\ \eta \ne \eta'$$

(C13) With a calendar, every share lies within the shift window of one working day; machines run at any time.
$$\operatorname{day}(\underline{I}_\eta) \bmod 7 \in \mathcal{D}^{\mathrm{w}},\qquad \operatorname{mod}(\underline{I}_\eta) \ge h^{\mathrm{S}},\qquad \overline{I}_\eta - \operatorname{start}(\operatorname{day}(\underline{I}_\eta)) \le h^{\mathrm{E}} + \overline{\mathrm{ot}} \qquad \forall \eta$$
where $\operatorname{start}(\nu)$ is the time of 00:00 on day $\nu$; the window ends before midnight (calendar
validity, §2), so a share cannot cross into the next day.

(C14) With a calendar, a worker who has a share on day $\nu$ starting before the latest break start
($\underline{I}_\eta < \operatorname{start}(\nu) + h^{\mathrm{B}+}$) has exactly one break $\mathrm{br}_{z,\nu}$ that
day, in the window; at most one break a day; no share overlaps a break. A worker whose first share of the day starts
after the window owes no break (user 2026-11-09). The planner may still schedule a break on any day (the rule does
on every day with a share); whether the worker takes it is up to him. Deliberately simpler than §4 ArbZG (break owed
for more than 6 h of working time; protocol 2026-11-09 (28)); exact working times per worker are expected from the
MES.
$$\operatorname{mod}(\mathrm{br}_{z,\nu}) \in [h^{\mathrm{B}-}, h^{\mathrm{B}+}],\qquad v_{\eta,z} = 1 \Rightarrow I_\eta \cap [\mathrm{br}_{z,\nu}, \mathrm{br}_{z,\nu} + p^{\mathrm{br}}) = \emptyset$$

**Breaks in a revised plan** (against a snapshot at $t$, [05](05_rescheduling-frozen-part.md); the breaks
$\widehat{\mathrm{br}}_{z,\nu}$ started by $t$ are part of the snapshot):

(C6$^b$) A break not started is not planned before $t$: $\mathrm{br}_{z,\nu} \ge t$ for every break not in the snapshot.

(C7$^b$) Started breaks are unchanged: $\mathrm{br}_{z,\nu} = \widehat{\mathrm{br}}_{z,\nu}$ for every break of the snapshot. They are realized
history and are not checked against the window (like C2 for frozen operations).

(C14$^f$) Forced postponement: a break not started may start after the window only at the earliest time from
$\max(\operatorname{start}(\nu) + h^{\mathrm{B}-},\ t)$ at which it is clear of the worker's frozen part, i.e.
only if no break fits in the window next to it:
$$\mathrm{br}_{z,\nu} > \operatorname{start}(\nu) + h^{\mathrm{B}+} \ \Rightarrow\ \mathrm{br}_{z,\nu} = \operatorname{free}^{\mathrm{br}}_z\big(\max(\operatorname{start}(\nu) + h^{\mathrm{B}-},\ t)\big)$$
where $\operatorname{free}^{\mathrm{br}}_z(s)$ is the earliest $s' \ge s$ at which $[s', s' + p^{\mathrm{br}})$ is
clear of the frozen part of $z$: its started shares ($v_{\eta,z} = 1$ in the snapshot) and the pending removals
(C7$^o$) that the plan gives to $z$, at their forced times (no shift window: a break is no share). It arises only from disturbances (an overrun or a late
start of a share, a removal forced later; user 2026-11-08: a planner must never cause it, forced by the frozen part
it is the shortest delay). $I_\eta$ of a started share uses the snapshot's (expected) times and share lengths,
i.e. what a planner sees. Until 2026-11-09 only a started share covering $h^{\mathrm{B}+}$, with the break at its
end, was allowed; a pending removal forced into the window (e.g. 13:09 while the worker is free from 12:50, so a
60-minute break fits nowhere in between) was rejected. Extended by the user's decision (protocol (34)); the old
case is the special one where the started share covers $h^{\mathrm{B}+}$.

(C7$^o$) Forced overstay: let $O^{\mathrm{rm}}_t$ be the running operations whose suffix has not started at $t$
(one per batch: all members of a batch end together), taken in the plan's order of their removal starts
$C_o - a^{\mathrm{suf}}_o$ (ties: operation index). Each $o \in O^{\mathrm{rm}}_t$ ends at
$$C_o = \min_{z \in W_o} \operatorname{free}_{z,o}\!\big(\tilde C_o - a^{\mathrm{suf}}_o\big) + a^{\mathrm{suf}}_o$$
where $\operatorname{free}_{z,o}(s)$ is the earliest $s' \ge s$ at which $[s', s' + a^{\mathrm{suf}}_o)$ is clear
of the frozen part of $z$ (started shares and started breaks) and of the removals before $o$ in that order that the
plan gives to $z$, and lies within one day's shift window (C13). If a qualified worker is free at the expected
interval, $C_o = \tilde C_o$ (C7 as before); otherwise the delay is forced by a disturbance or by a removal before
it, and the shortest possible (user 2026-11-08: a planner must never cause an overstay). Since the removals are
booked before any new share, only the frozen part and the other removals can block them. The snapshot's expected
end of such an operation is $\tilde C_o = \max(\hat S_o + p_{o,\bar m(o)},\ t + a^{\mathrm{suf}}_o)$: the removal
cannot start before $t$ ([13](13_des.md) §6).

The order is the plan's (user 2026-11-11): any order passes, as long as each removal starts as early as the ones
before it allow. Until 2026-11-11 every removal was computed on its own, against the frozen part only; when two
pending removals needed the only free worker, the rule required both at their own earliest times, which overlap: no
plan passed C7 and C12 at once (found on an earlier draft of toy-workshop with print and mill removals; reproducible
case: `tests/test_competing_removals.py`, two oven removals at $t = 10$ with W1 the only worker free from 11).
The planners (repair, rule, CP-SAT) book one fixed order, `forced_removals`: always the removal with the earliest
possible start next, ties by the earliest due date of its orders, then by operation index, each by the plan's worker
if free then (repair), the least loaded free one (rule), otherwise the first free one. Booking only adds busy time, so the starts come out in booking
order and the checker, sorting the plan by removal start, recomputes the same times. Choosing among the orders (an
optimization over the permutations of $O^{\mathrm{rm}}_t$, usually one or two removals) is not implemented; it would
change only which removal waits, by at most one removal length.

Overtime $\mathrm{ot}_{z,\nu} = \max(0,\ \max_\eta \overline{I}_\eta - \operatorname{start}(\nu) - h^{\mathrm{E}})$ is bounded by
C13 ($\le \overline{\mathrm{ot}}$) and otherwise a cost (§4, planned), not a constraint. The common break (same start for all) is a
soft goal (spread penalty, §4), not a constraint. Rest without resource needs no constraint (C3 suffices, §2).

## 4. Objective function

*Planned* (spec §4–5): tardiness of order $k$ in missed shipping days,

$$T_k = \left|\{\, c \in \Gamma : d_k \le c < C_k \,\}\right|,$$

so a completion by the cutoff of the due date is on time, by the next working day's cutoff 1 day late, and a
missed Friday cutoff shipped on Monday 1 day late. *Implemented* as (O1') in [06](06_due-dates.md) §4 (evaluation,
CP-SAT, spread, metric `tardy_days`).

*Implemented* (phase 4, task 5; spec §5, user; level structure own): the worker objective, lexicographic by (O3)
of [06](06_due-dates.md):

(O4) Level 1, tardiness and overtime, one weighted level:
$$f_1 = \sum_{k} T_k + \theta_O \sum_{z,\nu} \mathrm{ot}_{z,\nu}, \qquad \mathrm{ot}_{z,\nu} = \max\big(0,\ e_{z,\nu} - \operatorname{start}(\nu) - h^{\mathrm{E}}\big),$$
$e_{z,\nu}$ the end of $z$'s last share starting on day $\nu$ (as metric M7, [23](23_metrics.md)). $\theta_O \ge 0$ is
days of tardiness per minute of overtime, a required parameter without a default (varied in experiments to show
the trade-off; user: a late order is worse than overtime "to a certain degree"). Weighted sums of criteria as an a
priori approach for the FJSP: Dauzère-Pérès et al. (2024), p. 416. In code $\theta_O$ is a fraction
$\mathrm{num}/\mathrm{den}$ and the level is scaled to the integer $\mathrm{den} \sum_k T_k + \mathrm{num} \sum \mathrm{ot}$ (the
same order).

(O5) Level 2, breaks: postponement plus spread, equal weights (spec §5, own),
$$f_2 = \sum_{z,\nu} \max\big(0,\ \operatorname{mod}(\mathrm{br}_{z,\nu}) - h^{\mathrm{B}-}\big) + \sum_\nu \big(\max_z \mathrm{br}_{z,\nu} - \min_z \mathrm{br}_{z,\nu}\big),$$
over the planned breaks (as M7 over the realized ones). Postponement is penalized only after the earliest break
start; a postponement past the window happens only by force (C14$^f$, a constant of the model).

(O6) Level 3: the activity clock at the end of the plan (spec §5, user: a print until 22:00 counts, 22:00–08:00
does not; user 2026-11-10: worker overtime and unattended rest count too, since that time is needed):
$$C^{\mathrm{act}}_{\max} = \sum_{\nu} \big|[\operatorname{start}(\nu) + h^{\mathrm{S}},\ \operatorname{start}(\nu) + h^{\mathrm{E}}) \cap [0, C_{\max})\big| + \sum_{\iota} \max\Big(0,\ \max_{o:\ S_o < \overline{\mathrm{gap}}_\iota} \min(C_o, \overline{\mathrm{gap}}_\iota) - \underline{\mathrm{gap}}_\iota\Big)$$
over the working days $\nu$ and the gaps $\mathrm{gap}_\iota = [\underline{\mathrm{gap}}_\iota, \overline{\mathrm{gap}}_\iota)$ between
their regular shift windows (nights, weekends): per gap, from its start to the last end of an operation that started
before the gap ends. This is the
measure of the union of the shift windows and all operation intervals up to $C_{\max}$ if the activity in each gap
runs without a pause from the gap's start (the normal case: night work continues the day's work); otherwise an
upper bound (user's choice "night = last end", 2026-11-10). One definition for the objective, the CP-SAT model and
the metric (M1 in [23](23_metrics.md)); without a calendar $C^{\mathrm{act}}_{\max} = C_{\max}$.

Level 0 (oven overstay) of the spec is not a planning objective (phase 4 plan, decision 3): with C7$^o$ it is fixed
by the frozen part and the same for every plan; it stays metric M7. Priority (user): a late order is worse than
overtime to a degree ($\theta_O$), overtime worse than a postponed break, which is worse than a later end.
`objectives.worker_objective(theta_O)`; levels `tardiness_and_overtime(theta_O)`, `BREAK_PENALTY`, `ACTIVE_MAKESPAN`;
`objectives.overtime(ci, schedule)`. CP-SAT mapping in [12](12_cp-sat.md) §7b.

(O7) Cutoff slack (2026-11-11, user; own modeling after the slack and buffer ideas below): the shortfall of a buffer
$\mathrm{buf}$ (minutes, $0 < \mathrm{buf} < 1440$) before the cutoff an order ships with,
$$f^{\mathrm{sl}} = \sum_k \mathrm{sh}_k, \qquad \mathrm{sh}_k = \max\big(0,\ \mathrm{buf} - (d^{\mathrm{ship}}_k - C_k)\big), \qquad d^{\mathrm{ship}}_k = \max\big(d_k,\ \min\{c \in \Gamma : c \ge C_k\}\big),$$
over the orders with a due date: an order ending less than $\mathrm{buf}$ before its shipping cutoff counts the missing
minutes, on time or late (then before the cutoff it actually ships with). Why: with planned durations an optimal
plan may end an order exactly at its cutoff, and the next delay costs a whole day (toy-workshop, seed 1, protocol
(42): CP-SAT moved k1 to Tuesday 11:40–12:00 to save overtime, k8's QM ran 24% longer, k1 and k8 missed the cutoff).
Sources for slack as protection against disturbances: Davenport, Gefflot & Beck (2001, `T67B96FW`, pp. 1–3: temporal
protection extends durations, time window slack requires slack per activity in the model; job shop with due dates,
sum of tardiness); time buffers before milestone deadlines: Klimek & Łebkowski (2009, `8SPWPQ6M`, pp. 3–7). The
form $\mathrm{sh}_k$ per order and shipping cutoff is our own.

Worker objective with slack (user 2026-11-11: the slack right after tardiness), five levels:
$$\mathrm{Lex}\Big(\sum_k T_k,\ f^{\mathrm{sl}},\ \sum_{z,\nu} \mathrm{ot}_{z,\nu},\ f_2,\ C^{\mathrm{act}}_{\max}\Big),$$
tardiness strictly first (no trade-off $\theta_O$), then the buffer, then overtime. `objectives.worker_objective_with_slack(buf)`;
levels `TOTAL_TARDINESS`, `cutoff_slack(buf)`, `OVERTIME`, `BREAK_PENALTY`, `ACTIVE_MAKESPAN`. CP-SAT: per due order
and cutoff $c \ge d_k$ (and the first cutoff after the horizon) a literal $[C_k > c]$ in both directions and a term
$C_k - c + \mathrm{buf}$ if not late at $c$, else 0; $\mathrm{sh}_k = \max(0, \text{terms})$ (`add_max_equality`): the
first cutoff not missed is $d^{\mathrm{ship}}_k$, later ones lie at least a day further and give negative terms
(hence $\mathrm{buf} < 1440$). Exact on every solution. `OVERTIME` uses the overtime variables of §7b, lower bounds
that are exact where this level minimizes them. Tests `tests/test_worker_objective.py` (by hand: buffer 60, order due
Tuesday 12:00 ending 10:40, 11:40, 12:00, Monday 11:55, Wednesday 11:30 → 0, 40, 60, 0, 30; one worker, A (90) from
Monday 16:30 and B (150) from Tuesday 08:00, both due Tuesday 12:00: the $\theta_O$ objective puts A Tuesday
10:30–12:00 without overtime, the slack objective Monday 16:30–18:00 with 30 minutes, levels (0, 0, 30)).

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
  $[h^{\mathrm{S}}, h^{\mathrm{B}-})$ or $[h^{\mathrm{B}-} + p^{\mathrm{br}}, \text{latest})$, i.e. with the break at
  its earliest start (the rule's fixed 12:00 break); `latest` is $h^{\mathrm{E}}$ without overtime or
  $h^{\mathrm{E}} + \overline{\mathrm{ot}}$ with it. A share longer than both parts raises `ValueError` (it cannot be planned
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
  length $p^{\mathrm{br}}$ comes from the calendar). The planner decides the break start $\mathrm{br}_{z,\nu}$, so breaks are
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
  ($\sum_{z,\nu} \max(0,\ \text{last share end on day } \nu - h^{\mathrm{E}})$), `overruns`, `break_postponement`,
  `break_spread`
  ([23](23_metrics.md) M7). Tests `tests/test_worker_snapshot_metrics.py`.
- Dispatching (phase 3, task 2, no calendar yet): `planners.dispatching.dispatch` books every share into a gap of
  a qualified worker (least worker load $V_z$, then lowest index), waits for the workers in the candidate's
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
- Breaks through rescheduling, task 2: forced overstay (C7$^o$). Checker `forced_end` (independent gap search
  `_free_from` over `_frozen_worker_time(..., with_breaks=True)`, shift window C13 with a calendar),
  `frozen_changed(..., end)`; snapshot: expected end $t + a^{\mathrm{suf}}_o$ for a pending suffix; rule: a pending
  suffix at the earliest free time of a qualified worker, the frozen operation (and its batch, its machine and its
  successors) ends with it; DES `_apply`: a running operation takes the plan's worker for a share not started yet
  (before, the plan's choice was ignored). Tests `tests/test_forced_overstay.py` (by hand: one worker, polishing
  at factor 2, snapshot at 8: removal [9, 10), oven batch ends 10, mill runs one minute later; the DES accepts it
  and realizes the removal at [11, 12), OVERSTAY 3; negative → C7: end kept although forced, longer than forced,
  moved earlier, moved without force (carrier plan at 3), moved after the removal started (at 6)).
- Breaks through rescheduling, task 3: planners return `Plan(assignments, breaks)`; `execute` runs with the start
  breaks and reports the realized ones; `Simulation.update_plan(plan, breaks)` keeps taken breaks and replaces
  pending ones ([05](05_rescheduling-frozen-part.md) §5, [13](13_des.md) §7). Tests `tests/test_break_handover.py`
  (by hand: realized breaks A 12:20, B 12:00 from `execute`; current breaks at 12:10 and 12:30; at 12:10 A's due
  break replaced by 12:20 and B's taken break kept, run to the end; a moved taken break is rejected (C7); without
  breaks the current ones stay; `dispatch_planner` returns a `Plan`).
- Dispatching from a snapshot (phase 3, task 4): started shares of frozen operations keep and occupy their workers
  (C7), a pending removal gets a worker by the rule's choice. With a calendar since breaks Task 4 (2026-11-09):
  breaks are bookings per worker and day (`break_at`: the started one, else the earliest start from 12:00, on the
  snapshot's day not before $t$, clear of the frozen part and the pending removals; C14$^f$ after the window, or no
  new share that day if the worker had none and no break is possible); pending removals booked as the checker's
  C7$^o$ (overtime, frozen part only, before breaks). `dispatch_plan` returns `Plan(assignments, breaks)`. The
  snapshot carries `FrozenOperation.share_lengths` (done: realized; running prefix: at least until $t + 1$;
  otherwise planned), used by the checker (`_frozen_worker_time`) and the rule; this closes the open point on
  overrunning prefixes (§6). Tests `tests/test_rule_snapshot_calendar.py`.
- Dispatching with the calendar (phase 3, task 3): shares only within the shift without overtime and outside the
  worker's break of that day (12:00 without a snapshot); `dispatch_plan` gives the plan's breaks (C14); machines
  run overnight, attended removals wait for the morning. See [11](11_dispatching-rules.md) §3.
- Shift repair with workers, no calendar (phase 4, task 1): workers and the share order per worker kept, worker
  blockers per share, machine-less operations, a pending removal at the C7$^o$ end with its planned worker if
  free, otherwise the first free qualified one; see [05](05_rescheduling-frozen-part.md) §3. Tests
  `tests/test_repair_workers.py`.
- Shift repair with the calendar (phase 4, task 2): shares inside the shift without new overtime (C13; per worker
  and day at most the plan's last share end) and outside the worker's break; pending breaks moved when due or
  clashing with the frozen part (C6$^b$, C14$^f$), owed breaks added (C14), the pending removal with the calendar
  as the checker (C7$^o$); `repair_plan` returns `Plan(assignments, breaks)`. See [05](05_rescheduling-frozen-part.md)
  §3. Tests `tests/test_repair_calendar.py`.
- CP-SAT with workers and machine-less operations, no calendar (phase 4, task 3): share intervals per qualified
  worker, no overlap per worker, batch shares per slot, frozen shares and the forced removal; see
  [12](12_cp-sat.md) §7a. Tests `tests/test_cpsat_workers.py`.
- CP-SAT with the calendar (phase 4, task 4): night and weekend intervals, overtime per worker and day, one break
  per worker and working day, C14$^f$; see [12](12_cp-sat.md) §7b. Tests `tests/test_cpsat_calendar.py`.
- Competing removals (2026-11-11, C7$^o$ in the plan's order): checker `forced_ends` (replaces `forced_end`) books
  the pending removals in the plan's order of removal starts with the plan's workers; `planners/repair.py`
  `forced_removals` (list scheduling: earliest possible start, then earliest due date, then index; returns share,
  start, free workers and the booked worker; callback `choose` picks among the free ones: repair its planned worker,
  the rule the least loaded) is used by repair, the rule (before: snapshot order) and CP-SAT (with more than one pending run its
  removal worker is fixed to the booked one, since each forced time assumes the others' workers). Tests
  `tests/test_competing_removals.py` (by hand: two ovens, W1 the only worker free from 11 at $t = 10$; Y, due
  earlier, removed [11, 13), X [13, 15); the other order passes the checker, both at 11 does not (C7, C12), X
  delayed on its own does not (C7); repair, rule and CP-SAT give Y first; `execute` with every policy).
- Guards: none left; `compiled.reject_workers` removed (every consumer handles workers and the calendar since
  phase 4). Tests: `tests/test_worker_compile.py` (shares of the three order kinds, of the oven batch and the
  attended mill run, intervals, instances without workers unchanged, horizon).
- Tests: `tests/test_calendar.py` (arithmetic by hand: Monday 12:00 is $t = 240$, Tuesday 00:00 is $t = 960$,
  weekend skipped, Friday 12:01 → Monday 12:00; one negative test per validation rule).

## 6. Assumptions and open points

- $t = 0$ is Monday 08:00 by default (mine); no holidays; one shift pattern for all workers (spec, non-goals).
- The cutoff is a working-day event: no courier on weekends (user: a missed Friday cutoff shipped on Monday is
  1 day late).
- Real attended shares and durations from Fidentis: placeholders for now (user).
- **19:30 is hard in the plan, soft in execution** (user, 2026-11-06): C13 forbids planned shares past
  $h^{\mathrm{E}} + \overline{\mathrm{ot}}$; in the DES a share that started in time but runs longer is finished and counted as an
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
- ~~A running prefix is visible in the snapshot only with its planned length~~ **Resolved 2026-11-09:** the Task 4
  sweep hit the reverse case (a prefix done earlier than planned, its planned interval overlapping the break taken
  right after it), so the snapshot now carries the share lengths: realized for done shares (observed, no leakage),
  at least until $t + 1$ for a running prefix (like $\tilde C_o$), planned otherwise.
- ~~A worker without a share and a break on the snapshot's day takes no new share that day~~ (fallback of
  2026-11-09, replaced the same day): C14 now owes a break only for a share starting before the window, so a worker
  idle until the afternoon takes shares without a break (user). Working times and working days per worker
  (availability windows) are expected from the MES and will refine C14; not modeled yet.

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
| 2026-11-05 | e5348b0–78e228d | Component created: design summary; work calendar implemented (`Calendar`, `simulation.calendar`, schema 0.6, due dates on cutoffs). |
| 2026-11-06 | 78e228d | DES: shares, calendar, swap rule (phase 2, tasks 1–3). |
| 2026-11-06 | 78e228d | Dispatching rule with shares and machine-less operations, no calendar (phase 3, task 2). |
| 2026-11-07 | 78e228d | Dispatching rule with the calendar and `default_breaks` (phase 3, task 3). |
| 2026-11-08 | 78e228d | Dispatching from a snapshot with workers, no calendar (phase 3, task 4); open point: breaks through rescheduling. |
| 2026-11-08 | 78e228d | Breaks in the snapshot; (C6$^b$), (C7$^b$), (C14$^f$) in the checker; symbols $v_{\eta,w}$, $I_\eta$, $\mathrm{br}_{w,d}$, $\widehat{\mathrm{br}}_{w,d}$ in `notation.md`. |
| 2026-11-09 | 7274636 | (C14) a break is owed only on a day with a share starting before the latest break start (user); fallback "no new share that day" removed. |
| 2026-11-09 | 7274636 | Breaks through rescheduling, task 4: rule from a snapshot with the calendar (breaks as bookings, removals as C7$^o$), `FrozenOperation.share_lengths`. |
| 2026-11-09 | 7274636 | Breaks through rescheduling, task 3: `Plan`, break handover in `update_plan` and `execute`. |
| 2026-11-09 | ef6f798 | (C7$^o$) forced overstay: checker, snapshot expected end, rule, DES worker takeover for a pending share. |
| 2026-11-09 | uncommitted | Shift repair with workers, no calendar (phase 4, task 1); repair guard removed. |
| 2026-11-09 | uncommitted | Shift repair with the calendar (phase 4, task 2). |
| 2026-11-09 | uncommitted | CP-SAT with workers, no calendar (phase 4, task 3); `reject_workers` removed. |
| 2026-11-09 | uncommitted | CP-SAT with the calendar (phase 4, task 4); no guard left. |
| 2026-11-09 | uncommitted | Objective (O4)–(O6) implemented (phase 4, task 5): tardiness + $\theta_O$ overtime, break penalty, makespan; level 0 a metric only. |
| 2026-11-10 | uncommitted | (O6) the activity clock $C^{\mathrm{act}}_{\max}$ instead of the plain makespan (user: overtime and unattended rest count; night = last end); $\mathrm{gap}_\iota$. |
| 2026-11-11 | uncommitted | (O7) cutoff slack $f^{\mathrm{sl}}$ (user: right after tardiness), `cutoff_slack(buf)`, `OVERTIME`, `worker_objective_with_slack(buf)`; $\mathrm{buf}$, $d^{\mathrm{ship}}_k$, $\mathrm{sh}_k$. |
| 2026-11-11 | uncommitted | (C7$^o$) pending removals in the plan's order, each also clear of the removals before it (user); $O^{\mathrm{rm}}_t$, $\operatorname{free}_{z,o}$; planners book earliest possible start first, ties by due date then index; checker `forced_ends`, `forced_removals` shared by repair, rule and CP-SAT. |
| 2026-11-09 | uncommitted | (C14$^f$) extended (user): the earliest clear start from $\max(h^{\mathrm{B}-}, t)$ next to started shares and pending removals; $\operatorname{free}^{\mathrm{br}}_z$; checker, repair, rule. |
| 2026-11-09 | ef6f798 | Symbols renamed (user, grounded in the literature, protocol 2026-11-09 (24)): worker index $w$ → $z$ (Berti et al. 2021), day index $d$ → $\nu$, qualified workers $W_\eta$ → $W_o$, overtime $O_{w,d}$, $\bar O$ → $\mathrm{ot}_{z,\nu}$, $\overline{\mathrm{ot}}$, break length $L^{\mathrm{B}}$ → $p^{\mathrm{br}}$, worker load $V_w$ → $V_z$. |
| 2026-11-08 | ef6f798 | Symbols renamed (user): break start $b_{w,d}$ → $\mathrm{br}_{w,d}$ (clash with the late offset $b$ of [22](22_scenarios.md)); worker assignment $y_{\eta,w}$ → $v_{\eta,w}$ (clash with the batch slot assignment $y_{o,j}$ of [03](03_carriers.md)). |
| 2026-11-05 | e5348b0–78e228d | Constraints (C1'), (C11)–(C14) and the checker; mini instance `toy-workers.json`. |
| 2026-11-05 | e5348b0–78e228d | Schedule format: machine optional, workers per assignment, breaks in the schedule. |
| 2026-11-05 | e5348b0–78e228d | Compilation of workers and shares (`Share`, `share_interval`, `fixed_duration`), guards in DES, rules, CP-SAT, repair; fallback options (prefix + unattended only, or fully attended operations) recorded in §6. |
| 2026-11-05 | e5348b0–78e228d | Worker shares and machine-less operations in the format; table of the kinds; symbols $W$, $\mathcal{A}_o$, $W_\eta$, $a^{\mathrm{pre}}_o$, $a^{\mathrm{suf}}_o$, $O^{\emptyset}$. |
| 2026-11-05 | e5348b0–78e228d | Tardiness in missed shipping days implemented ([06](06_due-dates.md) (O1')); `CompiledInstance.calendar` (`WeekCalendar`). |
