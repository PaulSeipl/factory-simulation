# 07 Order arrivals

Status (2026-11-12): steps 1–4 of the design `docs/superpowers/specs/2026-11-11-order-arrivals-design.md` — instance
format, visibility, DES event, arrival trigger, sampler. Metrics and the hindsight comparison follow (step 5).

## 1. Prose description

The company makes to order: new orders reach the planning tool while the current plan runs. In the real process
(user 2026-11-12) sales releases an order for design; designed orders are prioritized (due date, maybe more) and
nested, with capacity information from the MES; after nesting they reach the planning tool, already bound to their
carriers. An order therefore has three times:

- **acceptance** $A^{\mathrm{acc}}_k$: sales releases the order for design; the due-date clock starts here (a fixed
  number of working days to the shipping cutoff, `math/06`, step 4),
- **arrival** $A_k$: its nesting batch is done; from now on the planning tool knows the order,
- **release** $r_k$: earliest start of its operations (C4, [01](01_basic-fjsp.md)).

The instance is the **hindsight container**: it holds every order of an experiment, including those that arrive
later. The planning tool never sees an order before its arrival; at time $t$ it works on the **visible
sub-instance**, the orders with $A_k \le t$ together with their carriers and runs.

**Packages.** An arrival is a nesting batch: its orders, their carriers and runs. A carrier and a run never mix
orders of different arrivals, so the visible sub-instance is always complete (no carrier with an order the planner
does not know) and the planner cannot learn of a future order through a shared carrier. Own modeling; it simplifies
the nesting interface of [32](32_target-data-model.md) §2, where nesting runs late against free printer gaps, and it
excludes topping up an existing, not yet started carrier with a later order (lower carrier utilization, to be named
as a limitation).

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

| Symbol | Meaning |
|---|---|
| $A_k$ | arrival of order $k$: the planning tool knows $k$ from $A_k$ on (Li et al. 2026 use $A_i$ for the arrival of a job, [06](06_due-dates.md) §1) |
| $A^{\mathrm{acc}}_k$ | acceptance of order $k$ (released for design); start of the due-date clock |
| $\mathcal{K}(t)$ | orders known at $t$: $\{k \in \mathcal{K} : A_k \le t\}$ |
| $\mu(w)$ | mean number of orders accepted on weekday $w$ (sampler) |
| $H^{\mathrm{arr}}$ | arrival window: acceptances in $[0, H^{\mathrm{arr}})$ (a horizon like $H_0$, $H^{\mathrm{cal}}$) |
| $\Gamma^{\mathrm{nest}}$ | nesting times (a set of times like the cutoffs $\Gamma$) |
| $n^{\mathrm{due}}$ | due-date offset in shipping cutoffs after the acceptance |
| $n^{\mathrm{bl}}$ | earliest cutoff for the due dates of the backlog |

**Visible sub-instance at $t$** (definition): the orders $\mathcal{K}(t)$, the carriers $\{b : \mathcal{K}_b \subseteq
\mathcal{K}(t)\}$ and their runs. The planning tool at $t$ plans over it. By (V21) it is a valid instance on its own.

## 3. Constraints

No new plan constraint. Two new validation rules of the instance ([02](02_instance-validation.md)): (V20) the order
of the times $A^{\mathrm{acc}}_k \le A_k \le r_k$, and (V21) packages (the orders of a carrier and the carriers of a
given run arrive together).

C4 is unchanged: with $A_k \le r_k$ a plan of the full instance never starts an operation before its arrival.

## 3a. Arrival process (step 4, own modeling)

Used to generate experiment instances; no source in the library for any of the three choices **[uncertain]**.

- **Acceptances:** on every working day $\nu$ of the window $[0, H^{\mathrm{arr}})$ the number of accepted orders is
  Poisson with the mean $\mu(\nu \bmod 7)$ of its weekday (the MES gives expected numbers per weekday); each one is
  accepted at a uniform minute of that day's regular shift $[h^{\mathrm{S}}, h^{\mathrm{E}})$, cut to the window.
- **Arrival:** at the first nesting batch at or after the acceptance,
  $$A_k = \min\{\gamma \in \Gamma^{\mathrm{nest}} : \gamma \ge A^{\mathrm{acc}}_k\}, \qquad r_k = A_k$$
  with $\Gamma^{\mathrm{nest}}$ the nesting times (given working weekdays at a fixed minute: daily, or e.g. weekly as
  the advisor proposes for higher volume). Orders with the same $A_k$ form one package and are nested together
  (next fit in due-date order, [21](21_instance-generator.md) §4a). Acceptances inside the window may arrive after
  it (a weekly batch after its end).
- **Due dates:** either the $n^{\mathrm{due}}$-th shipping cutoff strictly after the acceptance (company rule, about 4
  working days to shipping), or the lead-time bound with a tightness factor from the arrival ([06](06_due-dates.md)),
  moved to the next cutoff. The offset must leave a shipping day after the latest possible arrival: for every two
  consecutive batches $\gamma < \gamma'$ the $n^{\mathrm{due}}$-th cutoff after $\gamma$ lies at or after the first
  cutoff after $\gamma'$ (otherwise the parameters are rejected; daily nesting needs $n^{\mathrm{due}} \ge 2$, weekly
  nesting on Fridays $\ge 6$). This keeps (V10) and rules out combinations without sense (user).
- **Backlog:** orders known at $t = 0$ ($A^{\mathrm{acc}}_k = A_k = 0$); with the fixed rule its due date is the
  cutoff drawn uniformly among the $n^{\mathrm{bl}}$-th to $n^{\mathrm{due}}$-th after 0, as if it had been
  accepted over the working days before (user agreed), instead of one burst on the same day. The spread starts at
  $n^{\mathrm{bl}} = 3$ (user 2026-11-12, `backlog_earliest_cutoff`): the first cutoff lies 4 h after $t = 0$, and a
  backlog order starts from scratch at 0 (its route begins with design), so it would be late by construction; in
  the end-to-end run of 2026-11-12 (spread from 1) the start plan already had tardiness 2.

## 4. Objective function

Not affected.

## 5. Implementation in code

- `simulation.model.instance.Order`: `accepted`, `arrival` (both `NonNegativeInt`, default 0: known from the start,
  so every existing instance keeps its meaning). Schema version 0.7 (`schemas/instance-0.7.json`); all instances in
  `data/instances`, the generators and the Brandimarte loader write 0.7.
- `Instance.check_references`: (V20) per order; `_check_carriers`: (V21) per carrier and per given run (runs per
  carrier inherit the carrier's arrival).
- `simulation.model.instance.visible_instance(inst, t)`: the visible sub-instance (§2), same name as the full instance (scenarios and
  snapshots match by name). A carrier is filtered by its first order, a run by its first carrier, which (V21) makes
  sufficient. Not re-validated (`model_copy`); the tests re-validate it.
- Tests `tests/test_arrivals.py`: defaults; valid times; two packages (toy-carriers twice, the second arriving at
  10); a negative test per rule (arrival after release, accepted after arrival, negative times, carrier across
  packages, run across packages); visible sub-instance at $t = 0, 9, 10$ (valid, compiles, same name), equal to the
  instance after the last arrival.

**Step 2, DES** ([13](13_des.md) §3): `CompiledInstance.arrival` (per order), `compile_visible(inst)` (t → compiled
visible sub-instance, one object per set of known orders, so a planning tool can detect an arrival by identity);
`Simulation(..., visible=)`: ARRIVAL events, the set `planned` ($O^{\mathrm{pl}}$), plan checks against `visible(t)`;
`planned_batches(..., planned)`. Tests in `tests/test_arrivals.py`: zero disturbance (a hindsight plan with arrivals
replays unchanged); an unplanned package stays idle and the run ends with "operations never completed"; a plan
holding an unknown order is rejected (C0, no leakage); carriers: two packages with their own carriers and runs,
replanned at the arrival with CP-SAT; an arrival during a print run (the started run R1 unchanged, C8/C9 hold); an
arrival at a planned start. Since step 3 these tests run through `execute`.

**Step 3, planning tool** ([05](05_rescheduling-frozen-part.md) §3): `execute(..., visible=compile_visible(inst))`;
when the visible instance grows, `adapt_plan(..., arrived=True)` skips the repair and reschedules completely (trigger
`arrival`), accepted regardless of the change budget, new anchor; the budget counts only operations planned before
(`_reschedule`, CP-SAT `machine_before.get`), arrived ones are recorded as `inserted`. Arrivals without a planner
(no policy, or repair only): `ValueError`. Tests in `tests/test_arrivals.py`: CP-SAT (REPLAN at 10, `inserted` =
the 20 operations of package 2: 8 order, 6 carrier, 6 run operations), dispatching rule SPT + ECT, change budget 0 (no old operation
changes its machine, the new orders are placed), no planner rejected, four disturbed runs ($\sigma = 0.3$, start
offsets, shift threshold 1, period 20: repairs, threshold reschedulings and the arrival rescheduling mixed; realized
schedules violate only C2), and a hand-computed mini instance: $a_1$ on $M_1$ (4) known at 0, $b_1$ ($M_1$: 2,
$M_2$: 5) arriving at 2; at 2 $a_1$ runs on $M_1$ until 4, so $b_1$ on $M_1$ ends at 6, on $M_2$ at 7; CP-SAT puts
$b_1$ on $M_1$ at $[4, 6)$, makespan 6, equal to the hindsight optimum.

**Step 4, sampler** (§3a): `simulation.arrival_generator`: `ArrivalParams` (Pydantic, frozen, JSON: seed, `base`
carrier-generator parameters with calendar and workers, `rates` per weekday, `window_days`, `nesting_days`,
`nesting_minute`, `due_working_days` or `due_tightness`, `backlog`), `sample_arrivals` (own stream `arrival-{seed}`),
`nth_cutoff`, `nesting_times`, `generate_arrival_instance` (one carrier-generator call for all orders, then times,
due dates, nesting per batch with IDs `P<batch>C…`, `P<batch>R…`, `P<batch>B…`). Tests
`tests/test_arrival_generator.py` (25): cutoffs by hand (Monday 10:00 + 4 → Thursday 12:00, Monday 13:00 + 4 →
Friday), weekly nesting times, determinism, acceptances in the shift on working days, arrival at the next batch,
weekly batches, the rate in the mean (300 seeds), instance times and due dates, backlog due dates, one nesting
batch per arrival, lead-time due dates, a small episode with CP-SAT rescheduling at every later batch, eleven
negative tests (incl. the shortest offsets: daily 2, weekly 6).

**Step 5, experiments** (2026-11-13): `simulation.experiment`: `ExperimentConfig` (JSON in `experiments/`: the
`ArrivalParams`, seeds, scenario, cutoff buffer, CP-SAT limits, named policies `PolicyConfig(planner, hindsight,
thresholds)`), `run_one` (one episode: instance and scenario per seed, start plan, `execute` with the plan history,
CSV row with configuration hash and commit), `run` (all configurations, policies and seeds in a process pool; one CSV
per configuration in `experiments/results/`, plan histories in `experiments/results/<config>/plans/`, not in git).
CP-SAT: worker objective with cutoff slack, one thread, fixed seed, deterministic limit (`cpsat_planner(...,
deterministic_time=)`), so runs are reproducible. `execute(..., keep_history=True)` records the start plan and every
plan the factory receives as a change set (time, cause, changed assignments, breaks), the basis for an animation of
the plan over time later. Metrics (M7), (M8) in [23](23_metrics.md). Configurations: load levels 4, 6, 8 orders per
working day and 8 with doubled machines and workers; 6 undisturbed (the gap to hindsight is pure information); daily
against weekly nesting (due 6 cutoffs after the acceptance). Policies: rule at arrivals, CP-SAT at arrivals,
CP-SAT with thresholds and period, hindsight with the same thresholds. Notebook `notebooks/07_arrivals.ipynb` reads
the results. Tests `tests/test_experiment.py` (row and history, reproducibility), `tests/test_arrivals.py` (history,
metrics with arrivals).

**Command line** (2026-11-13, user): `uv run experiment list | run | task | merge [names]` (names of files in
`experiments/` or paths, no name: all). Every run has an index (configurations sorted by name, then policies, then
seeds) and writes its row to its own file (`<config>/rows/<policy>-<seed>.json`, with the host), so runs can go to
separate machines (`task --index i`, default `SLURM_ARRAY_TASK_ID`: one Slurm array task per run); `merge` (also at
the end of `run`) writes the CSV of a configuration from the rows whose configuration hash matches and reports
missing or stale runs. Tests in `tests/test_experiment.py` (task by Slurm index, merge with a missing run, stale rows
after a configuration change, index out of range, unknown configuration).

## 6. Assumptions and open points

- Arrival = end of a nesting batch; when nesting runs (daily, on given weekdays) is a sampler setting (step 4), not
  decided at the company.
- No top-up of a not yet started carrier by a later order (V21).
- $A_k < r_k$ is allowed by the format (an order known before its material is ready); the generators set
  $r_k = A_k$.
- Without `visible` the DES and `execute` treat every order as known (a hindsight run: the plan must hold all of
  them).
- An arrival always triggers a complete rescheduling; insertion with the old operations fixed (CP-SAT) is kept for
  later (user, large instances).

## 7. Sources

- Arrival notation $A_i$: Li et al. 2026 (`6GGUPZNL`), as used in [06](06_due-dates.md) §1.
- New job arrival as a dynamic event in FJSP: Li et al. 2021 (`7VCTD9GM`, p. 1, 3); Song et al. 2025 (`999TFMAJ`,
  p. 14–15).
- Own modeling: three times per order, packages (V21), visible sub-instance.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-12 | a48812c | Created: acceptance, arrival, packages, visible sub-instance (step 1); schema 0.7. |
| 2026-11-12 | uncommitted | V1, V2 renamed V20, V21 (catalogue [02](02_instance-validation.md)); V3 became the definition of the visible sub-instance (§2). |
| 2026-11-12 | uncommitted | Step 2: ARRIVAL event, unplanned operations inert, plan check against the visible instance. |
| 2026-11-13 | uncommitted | Step 5: experiment runner, plan history, metrics with arrivals. |
| 2026-11-13 | uncommitted | Command line `experiment` (list, run, task, merge); one row file per run; host column. |
| 2026-11-12 | c72a018 | Step 4: arrival process (§3a) and `arrival_generator`. |
| 2026-11-12 | uncommitted | Step 3: arrival trigger in `execute` / `adapt_plan`, budget over old operations, `inserted`; hand-computed mini instance. |
