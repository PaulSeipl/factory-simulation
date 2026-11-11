# Workers, phase 4: repair and CP-SAT with workers and calendar — plan

**Goal:** the two remaining consumers handle workers, machine-less operations and the calendar: the shift repair
(so that `execute` with rescheduling runs end to end on worker instances) and the CP-SAT model (worker
assignment, breaks, overtime, the objective levels of spec §5). Every plan passes the checker (C1–C14, C6$^b$,
C7$^b$, C7$^o$, C14$^f$); zero-disturbance test: plan replayed = plan, CP-SAT value = evaluated value.

**Spec:** `docs/superpowers/specs/2026-11-05-workers-shifts-design.md` §5 (objective), §7 (repair, CP-SAT mapping).
Decisions since then that bind this phase: worker gaps (protocol (17)); breaks travel with the plan (`Plan`,
(26)); forced overstay C7$^o$ and forced postponement C14$^f$ only from the frozen part, a planner never causes
them (user, (20)); C14 owed only for a share starting before the window (user, (29)); symbols per `notation.md`
(rule in its header). Working style: one task at a time, tests, result, approval; `math/` with the Edit tool;
symbol check after every task and at the phase end.

## Decisions for the user (my recommendation first)

1. **Order:** (a) *Recommended:* repair first (Tasks 1–2). It is small and unlocks `execute` with workers, so
   every later CP-SAT task can be tested end to end in the DES. (b) CP-SAT first.
2. **Breaks in CP-SAT:** (a) *Recommended:* one break variable per worker and working day in the horizon, start in
   $[h^{\mathrm{B}-}, h^{\mathrm{B}+}]$, always present (C14 allows a break on any day; matches "the break is
   scheduled, taking it is up to the worker"); on the snapshot's day: the started break fixed, otherwise a variable
   with start $\ge t$, and if the window has passed with no break taken, none (no share of that worker that day
   may then start before the window, which holds since everything new starts $\ge t$). (b) Optional breaks with a
   Boolean "owed" per worker and day (exactly C14, more variables).
3. **Level 0 (oven overstay):** (a) *Recommended:* not a planning objective any more. With C7$^o$ the overstay is
   fixed by the frozen part (forced, shortest), so it is a constant for every planner; it stays a metric (M7).
   This also settles the [CHECK WITH FIDENTIS] for planning (it remains open for the evaluation). (b) Keep it as a
   level (constant, no effect).
4. **Overtime weight $w_O$** (spec §5, level 1: $\sum_k T_k + w_O \sum_{z,\nu} \mathrm{ot}_{z,\nu}$): a required
   parameter of the objective with no default in code; experiments vary it (spec). Placeholder in tests only.
   Symbol: $w_O$ clashes with the worker rule ($w$ is the literature's job weight, not used by us) → propose
   $\theta_O$ (objective-weight family $\theta$, Pinedo).

## Tasks

### Task 1: Repair with workers, no calendar
- `shift_repair` gets worker blockers: per worker its planned share order (from the plan, a batch once); an
  operation's blockers are its predecessors, its machine predecessor and, per share, the worker's previous share
  (its end, shifted by the share's offset: a suffix may follow later). Machine-less operations: no machine
  blocker, fixed duration. Workers, machines and orders stay (definition of repair, `terminology.md`).
- Frozen part: shares as in the snapshot (`share_lengths`), pending removals as C7$^o$ (the repair keeps the
  planned remover if it is free at the forced end, otherwise the first free qualified worker: the checker's forced
  end is the min over all qualified workers, so this change is forced too; corrected 2026-11-09, protocol (31)).
- `repair` loses its guard; `Assignment.workers` passed through.
- Tests: zero disturbance (repair = plan) on both worker instances for all 15 rule plans; by hand: a late prefix
  pushes the same worker's next share; a worker's gap is kept (gap rule as for machines); a pending removal whose
  worker is still busy ends later (forced); `execute` with repair only on `toy-workers` (no calendar) passes the
  checker; sweep over disturbed seeds.

### Task 2: Repair with the calendar, and `execute` end to end
- A share moved by the repair into a break or outside the shift goes to the next feasible slot of its worker
  (shift without overtime; the repair creates no overtime, spec §7); breaks: the started ones stay, a due break not
  taken yet moves to $\max(\text{planned}, t)$, within the window or forced (C14$^f$) (open point of (26)).
- `execute` with repair and with the rule as planner on calendar instances; `ExecutionResult.breaks`.
- Tests: zero disturbance; by hand: a late share pushed past 12:00 resumes at 13:00; an overdue break moved to $t$;
  a share pushed past 17:30 to the next morning; sweep: `execute` with repair only and with rule rescheduling over
  the five sweep instances of `tests/test_rule_snapshot_calendar.py`, all realized schedules pass the checker
  except C2 / overruns (by design).

### Task 3: CP-SAT with workers, no calendar
- Per share $\eta$ and qualified worker $z \in W_o$ an optional interval of length $a^{\mathrm{pre}}_o$ /
  $a^{\mathrm{suf}}_o$ / the operation's duration, presence $v_{\eta,z}$, `add_exactly_one` per share (C11);
  prefix start = operation start, suffix end = operation end; per worker `add_no_overlap` over its intervals (C12).
  Machine-less operations: no machine choice, $C_o = S_o + p_o$ (C1'). Batches: the shares belong to the slot (one
  set per slot; members take the slot's workers). Runs: attended setup / removal as whole shares; gaps between run
  parts allowed (C9 as today).
- From a snapshot: started shares fixed (snapshot lengths); a pending removal's end fixed to the forced end
  computed like the checker (C7$^o$), its worker free among the qualified ones free then.
- `solve` loses the guard; returns workers per assignment; `cpsat_planner` returns `Plan`.
- Tests: hand optimum on `toy-workers` without calendar and on the carrier instance (makespan), checked against a
  brute-force or hand value; every CP-SAT plan passes the checker and replays unchanged; from DES snapshots
  (sweep) feasible against the snapshot; symmetry among identical workers: measured, breaking only if slow.

### Task 4: CP-SAT with the calendar
- Per worker and working day in the horizon: fixed intervals for the night / weekend (from $h^{\mathrm{E}} +
  \overline{\mathrm{ot}}$ to the next $h^{\mathrm{S}}$) in the worker's `add_no_overlap`; an end-of-day variable
  $e_{z,\nu} \in [h^{\mathrm{S}}, h^{\mathrm{E}} + \overline{\mathrm{ot}}]$ with every share of that day ending
  before it (one optional link per share and day); overtime $\mathrm{ot}_{z,\nu} = \max(0, e_{z,\nu} -
  h^{\mathrm{E}})$ (C13). Breaks per decision 2 (C14, C6$^b$, C7$^b$, C14$^f$ from the snapshot).
- Tardiness in days already exists (O1').
- Tests: hand optimum with a share pushed past 12:00; overtime chosen when it saves a day of tardiness and not
  when it does not; break placed in the window; every plan passes the checker with its breaks and replays
  unchanged (incl. breaks); from snapshots (the sweep instances).

### Task 5: Objective levels
- Level 1 $\sum_k T_k + \theta_O \sum_{z,\nu} \mathrm{ot}_{z,\nu}$, level 2 break postponement + spread (equal
  weights, spec), level 3 makespan (plain end time as proxy, spec); lexicographic weights $\theta_i$ with spreads
  $\operatorname{spr}$ per level ([06](../../../math/06_due-dates.md) (O3)); `Objective.cpsat` gets the worker and
  break variables (extended signature); `evaluate` computes the same values from a plan with its breaks
  (zero-disturbance check: CP-SAT value = evaluated value).
- Tests: hand trade-off on a mini instance (overtime vs. one day late, for two values of $\theta_O$); the CP-SAT
  value equals the evaluation; lexicographic order respected on enumerated schedules.

Each task: `math/04_workers.md`, `05`, `06`, `12_cp-sat.md`, `13` as affected (formulas: notation checked first);
protocol entry; full suite; ruff.

## Not in this plan
- Generator for worker instances, packaging operation, dental example, calendar Gantt, notebook (phase 5).
- Worker s-batch across orders (phase 6). Availability windows per worker from the MES (own task, data format
  first).
