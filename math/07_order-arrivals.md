# 07 Order arrivals

Status (2026-11-12): step 1 of the design `docs/superpowers/specs/2026-11-11-order-arrivals-design.md` — instance
format and visibility. DES event, trigger, sampler and metrics follow (steps 2–5) and are added here.

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

## 3. Constraints

These are validation rules of the instance, not constraints of a plan.

(V1) Order of the times: an order is accepted before it arrives and arrives before it may start.
$$A^{\mathrm{acc}}_k \le A_k \le r_k \qquad \forall k \in \mathcal{K}$$

(V2) Packages: the orders on one carrier arrive together, and so do the carriers of one run.
$$A_k = A_{k'} \quad \forall b \in \mathcal{B},\ k, k' \in \mathcal{K}_b; \qquad A_{k(b)} = A_{k(b')} \quad \forall R \in \mathcal{R}^{\mathrm{given}},\ b, b' \in R$$
with $k(b)$ any order of carrier $b$.

(V3) Visibility: the planning tool at $t$ plans over $\mathcal{K}(t)$, its carriers $\{b : \mathcal{K}_b \subseteq
\mathcal{K}(t)\}$ and their runs. By (V2) this is a valid instance on its own.

C4 is unchanged: with $A_k \le r_k$ a plan of the full instance never starts an operation before its arrival.

## 4. Objective function

Not affected in step 1.

## 5. Implementation in code

- `simulation.model.instance.Order`: `accepted`, `arrival` (both `NonNegativeInt`, default 0: known from the start,
  so every existing instance keeps its meaning). Schema version 0.7 (`schemas/instance-0.7.json`); all instances in
  `data/instances`, the generators and the Brandimarte loader write 0.7.
- `Instance.check_references`: (V1) per order; `_check_carriers`: (V2) per carrier and per given run (runs per
  carrier inherit the carrier's arrival).
- `simulation.model.instance.visible_instance(inst, t)`: (V3), same name as the full instance (scenarios and
  snapshots match by name). A carrier is filtered by its first order, a run by its first carrier, which (V2) makes
  sufficient. Not re-validated (`model_copy`); the tests re-validate it.
- Tests `tests/test_arrivals.py`: defaults; valid times; two packages (toy-carriers twice, the second arriving at
  10); a negative test per rule (arrival after release, accepted after arrival, negative times, carrier across
  packages, run across packages); visible sub-instance at $t = 0, 9, 10$ (valid, compiles, same name), equal to the
  instance after the last arrival.

## 6. Assumptions and open points

- Arrival = end of a nesting batch; when nesting runs (daily, on given weekdays) is a sampler setting (step 4), not
  decided at the company.
- No top-up of a not yet started carrier by a later order (V2).
- $A_k < r_k$ is allowed by the format (an order known before its material is ready); the generators set
  $r_k = A_k$.
- The DES does not read $A_k$ yet; until step 2 an instance with arrivals is executed as if every order were known
  at 0.

## 7. Sources

- Arrival notation $A_i$: Li et al. 2026 (`6GGUPZNL`), as used in [06](06_due-dates.md) §1.
- New job arrival as a dynamic event in FJSP: Li et al. 2021 (`7VCTD9GM`, p. 1, 3); Song et al. 2025 (`999TFMAJ`,
  p. 14–15).
- Own modeling: three times per order, packages (V2), visible sub-instance (V3).

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-12 | uncommitted | Created: acceptance, arrival, packages, visible sub-instance (step 1); schema 0.7. |
