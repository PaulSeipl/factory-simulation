# 02 Validation of the instance

## 1. Prose description

An instance is checked **once, when it is loaded** (`Instance` and its sub-models, Pydantic v2). The rules below
restrict the **input data** (parameters such as processing times, releases, carriers), not a plan. They are not
constraints: a plan cannot violate them, and the feasibility checker (C0–C14, [01](01_basic-fjsp.md),
[03](03_carriers.md), [04](04_workers.md), [05](05_rescheduling-frozen-part.md)) assumes them. An instance that
breaks a rule is rejected before any planner, checker or DES sees it.

The catalogue serves replication: every instance used for a result in the thesis satisfies V0–V21, and every rule has
at least one negative test. The numbering is global like that of the constraints; every error message of the code
starts with its rule, e.g. `[V20] order J1: arrival 6 after release 5`, as the checker reports `[C4] …`.

**V0** groups the structural checks (well-formed file). **V1–V21** are the semantic rules, sorted by the component
they belong to. Formulas are given only where a rule is worth stating in the thesis; the others are one sentence.

## 2. Sets, parameters, variables

No new symbols; all from [notation.md](notation.md).

## 3. Rules

### V0 Well-formed (structural)

Field types and ranges (times $\ge 0$, durations $> 0$, `batch_capacity` $\ge 2$, non-empty options, carriers and
runs), schema version, no unknown fields (`extra="forbid"`); unique IDs (machines, orders, workers, parts and
operations per order, owners across orders, carriers and runs; no ID for a worker and a machine); every reference
resolves (machines in options, carrier steps of operations, runs and part times, predecessors within the same order,
qualified workers, parts on carriers, carriers in runs, scopes and carried part types); no duplicate predecessor.
Field types and ranges are Pydantic's own messages and carry no tag.

### Base model ([01](01_basic-fjsp.md))

(V1) Precedence within an order is acyclic: the graph $(O_k, P_k)$ of every order $k$ is a DAG.

(V2) The whole operation graph (orders, carrier and run operations) is acyclic: cycles can also close through carriers
and runs, e.g. two runs that each wait for the other's carrier.

(V3) Duration source: an order operation has machine options or a fixed duration, not both and not neither
($M_o \neq \emptyset$ xor $o \in O^{\emptyset}$); a carrier operation has neither, nor a worker share of its own
(both come from its carrier step).

### Workers and calendar ([04](04_workers.md))

(V4) A worker share is either the whole operation or a prefix and/or a suffix of positive length.

(V5) Prefix and suffix fit into the operation on every eligible machine:
$$a^{\mathrm{pre}}_o + a^{\mathrm{suf}}_o \le \underline{p}_o$$
(checked against the shortest option; a run whose estimated duration is shorter is caught by the checker, C11).

(V6) An operation without machine needs a worker share (otherwise nothing occupies anything while it runs).

(V7) Shares need workers: a worker share, an attended setup or an attended removal requires workers in the instance;
an attended setup (removal) requires a setup (removal).

(V8) The calendar is consistent:
$$h^{\mathrm{S}} < h^{\mathrm{B}-} \le h^{\mathrm{B}+}, \qquad h^{\mathrm{B}+} + p^{\mathrm{br}} \le h^{\mathrm{E}}, \qquad h^{\mathrm{E}} + \overline{\mathrm{ot}} \le 1440$$
the cutoff is a minute of the day, the origin $\omega$ a minute of the week, and $\mathcal{D}^{\mathrm{w}}$ is a
non-empty set of distinct weekdays.

(V9) An instance with a calendar uses minutes as `time_unit`.

### Due dates ([06](06_due-dates.md))

(V10) A due date does not lie before the release: $d_k \ge r_k$.

(V11) With a calendar, a due date is a shipping cutoff: $d_k \in \Gamma$.

### Carriers and runs ([03](03_carriers.md))

(V12) A part lies on at most one carrier.

(V13) All parts on a carrier have one type (the carrier's kind $\tau(b)$).

(V14) The carrier operations of an order form, per carried part type, one chain from a forming to a separating
operation; `role` and `carries` only on carrier operations; with several carrier kinds every carrier operation names
the part type it carries.

(V15) Parts and carrier operations match: an order has carrier operations for a part type iff it has parts of that
type on a carrier; with parts of several types on carriers every carrier operation names its type.

(V16) The member orders of a carrier have the same carrier route (the same chain of steps), so the carrier's
operations are well defined.

(V17) A carrier step is configured consistently: a batch step (planner-decided p-batch) has no setup, removal,
estimator or given runs; setup, removal and estimator need runs (given or per carrier); given runs only for a step
with run mode given.

(V18) Given runs cover their carriers exactly once: a run's carriers pass its step, and every carrier passing a step
$s$ with $\rho_s = \text{given}$ lies in exactly one run of $s$:
$$\big\lvert \{R \in \mathcal{R}^{\mathrm{given}}_s : b \in R\} \big\rvert = 1 \qquad \forall s : \rho_s = \text{given},\ \forall b \in \mathcal{B} \text{ passing } s$$

(V19) The run estimator has its input: every part of a run (or of a per-carrier run) of a step with an estimator has a
time for that step.

### Order arrivals ([07](07_order-arrivals.md))

(V20) Order of the times: an order is accepted before it arrives and arrives before it may start.
$$A^{\mathrm{acc}}_k \le A_k \le r_k \qquad \forall k \in \mathcal{K}$$

(V21) Packages: the orders on one carrier arrive together, and so do the carriers of one given run.
$$A_k = A_{k'} \quad \forall b \in \mathcal{B},\ k, k' \in \mathcal{K}_b; \qquad A_{k(b)} = A_{k(b')} \quad \forall R \in \mathcal{R}^{\mathrm{given}},\ b, b' \in R$$

## 4. Objective function

Not affected.

## 5. Implementation in code

`simulation.model.instance`: `WorkerShare.check_kind` (V4), `Calendar.check_times` (V8), `Instance.check_references`
(V0, V1–V3, V5–V7, V9–V11, V17, V20), `Instance._check_share` (V0, V5, V7), `Instance._check_carriers` (V0,
V12, V15, V16, V18, V19, V21), `carrier_kinds` (V13), `carrier_chains` and `_chain` (V14), the topological sort of
`operation_graph` (V2). Every `ValueError` message starts with `[Vn]`.

Negative tests (one per check; recorded on 2026-11-12 with a throwaway pytest plugin that collects the `[Vn]` tags
caught by `pytest.raises`; all 64 checks of `instance.py` are hit):

| Rule | Tests |
|---|---|
| V0 | `test_instance_model` (duplicates, unknown machine and predecessor; untagged Pydantic cases: unknown field, schema version, negative times), `test_carriers` (unknown references, owner ID twice), `test_carrier_kinds`, `test_worker_format` (duplicate worker, unknown qualified worker, worker named like a machine) |
| V1 | `test_instance_model::test_invalid_instance_rejected[cycle, self_loop]` |
| V2 | `test_carriers::…[m_cycle_through_runs]` |
| V3 | `test_carriers` (carrier operation with options, duration; options missing), `test_worker_format` (exclusive, worker share on a carrier operation) |
| V4 | `test_worker_format::test_invalid_share` |
| V5 | `test_worker_format` (share longer than the duration, the operation, the carrier step) |
| V6 | `test_worker_format::…[machine_less_without_worker]` |
| V7 | `test_worker_format` (attended setup / removal without one, without workers; share without workers) |
| V8 | `test_calendar::test_invalid_calendar` (9 cases) |
| V9 | `test_calendar::test_calendar_needs_minutes` |
| V10 | `test_instance_model::…[due_date_before_release]` |
| V11 | `test_calendar::test_due_date_must_be_a_cutoff` |
| V12 | `test_carriers::…[m_part_on_two_carriers]` |
| V13 | `test_carrier_kinds::…[m_mixed_carrier]` |
| V14 | `test_carrier_kinds` (carries on an order operation, named and unnamed), `test_carriers` (no forming operation, role on an order operation) |
| V15 | `test_carrier_kinds` (chain without carried parts, kind without chain, unnamed with two kinds), `test_carriers` (carried parts without carrier operations and vice versa) |
| V16 | `test_carriers::…[m_different_carrier_routes]` |
| V17 | `test_batches::test_invalid_batch_step_rejected`, `test_carrier_runs` (batch step with runs, estimator or setup without runs, given run for a per-carrier step) |
| V18 | `test_carrier_runs` (given step without runs), `test_carriers` (carrier in no run, in two runs, not passing the step) |
| V19 | `test_carrier_runs` (missing part time), `test_carriers::test_invalid_estimator_input_rejected` |
| V20 | `test_arrivals::test_invalid_times_rejected` |
| V21 | `test_arrivals::test_carrier_across_packages_rejected`, `test_run_across_packages_rejected` |

Validation that happens later, at run time, is not part of the catalogue: e.g. `calendar.py` rejects a share that fits
in no shift, the DES rejects an infeasible plan (`PlanNotExecutable`), and the scenario must match the instance
(`factors_by_index`).

## 6. Assumptions and open points

- V5 is checked against the shortest machine option, not per run (see the shortcut comment in `_check_share`).
- The grouping of V0 is a choice: structural checks are numbered as one rule because they say nothing about the
  model.

## 7. Sources

Own; the rules follow from the model components cited in §3. Format conventions (two layers, Pydantic, frozen,
`extra="forbid"`): `CLAUDE.md`.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-12 | uncommitted | Created: V0–V21 from the 64 checks of `instance.py`, `[Vn]` tags in the error messages, negative tests per rule. V20, V21 were V1, V2 in [07](07_order-arrivals.md). |
