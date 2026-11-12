# Order arrivals: design (revised 2026-11-11)

Status: draft for discussion. Nothing implemented. Expected orders (forecast) and the GA come after this.

## 1. Intent

The company makes to order: new orders arrive while the current plan runs. The DES must simulate arrivals, an
arrival must reach the planning tool as an event, and the tool must plan the new order into the running plan
(complete rescheduling with the snapshot). This is the **reactive baseline** ("myopic": plan only over the orders
known now). Forecast-aware planning (expected orders per weekday) is measured against it later.

## 2. Goals, non-goals, anti-goals

- **Goals:** arrival as DES event; no information leakage (the planner never sees an order before its arrival);
  every existing planner usable (CP-SAT, rules); a finite, reproducible arrival experiment with a hindsight
  comparison.
- **Non-goals (v1):** forecasts in the planner; adding an arriving order to an existing, not yet started carrier;
  order cancellation or due-date changes; arrival ≠ release (format ready, not used).
- **Anti-goals:** a planner that can read the future through the instance, the carriers or the anchor; a change that
  alters any result of today's tests (no arrivals → bit-identical behavior).

## 3. Decisions

| # | Decision | By |
|---|---|---|
| D1 | Order of work: arrivals → expected orders → GA | user |
| D2 | `Order.arrival: NonNegativeInt = 0` in the instance, schema 0.7; validation `arrival <= release`. Default 0 = known from the start (all existing instances unchanged). Generators set `release = arrival` | own, review point 4 |
| D3 | The instance is the hindsight container: all orders with their arrival times. Only the DES reads orders with `arrival > t` | own |
| D4 | Arrival = end of a nesting batch. Real process (user 2026-11-12): sales releases an order for design; designed orders are prioritized (due date, maybe more) and nested with capacity information from the MES; after nesting they reach the planning tool with their carriers. So an arrival is a **package** (one nesting batch: its orders, carriers and runs); packages never share a carrier or run (validation). The nesting cycle is a sampler parameter: daily at a fixed time (default, close to today) or on given weekdays (advisor's idea for higher volume, not decided at the company) — an experiment, not a model choice | user + own |
| D4a | Two times per order: `accepted` (released for design by sales; the due-date clock starts here) and `arrival` (nesting batch done; the planner learns the order). `accepted <= arrival <= release`. With weekly nesting a due date counted from arrival would hide the waiting time before nesting | own, user agreed |
| D4b | Due date: rule "fixed": `n` working days after `accepted` to the shipping cutoff (default 4, configurable); rule "lead time": today's `assign_due_dates` (`math/06`). Both selectable | user |
| D5 | DES: new event `ARRIVAL` (priority after COMPLETE / SHARE_END, before PLANNED_START). **Spike result (2026-11-12):** the DES needs no notion of "known", only of **planned**: an operation without an assignment in the factory's plan is inert (no PLANNED_START, not in the machine order, batches or worker order, not in `current_plan()` / `realized()`; the snapshot skips it as not started). An arrived order stays inert until the planning tool places it; `update_plan` gives a newly planned operation its PLANNED_START. Visibility ("known") lives only in the planning tool (`visible(t)`, D6). The plan check in `__init__` / `update_plan` runs against the visible instance (a callable passed to the DES). About 8 touch points in `des.py`; rebuild with state transfer not needed | own; spike |
| D6 | Visible sub-instance: `visible(instance, t)` filters orders, carriers and runs with `arrival <= t` and compiles them; cached, recompiled only at an arrival. Same name as the full instance | own |
| D7 | `execute` takes the `Instance` (or the full and a factory for visible compiled instances) instead of only `ci`; the plan for the tool and `update_plan` are checked against the visible instance | own |
| D8 | Trigger `"arrival"`: always a complete rescheduling, the anchor is reset to the new plan | own, review point 5 |
| D9 | Arrival without a planner is rejected (`ReschedulingPolicy(planner=None)` or no policy, with any `arrival > 0`): `ValueError` | own, review point 3 |
| D10 | Change budget at an arrival counts only operations planned before. A rescheduling triggered by an arrival is never rejected (the repaired plan lacks the new order, so there is nothing to fall back to); with CP-SAT the budget stays a constraint over the old operations, so the plan respects it anyway. Rules have no insertion mode today, hence no rule fallback in v1 | own, review point 2 |
| D11 | `_change`, `_reschedule`, objective deviation: computed over the operations both plans share; new operations reported as `inserted` in the REPLAN record | own, review point 1 |
| D12 | Experiment episode: arrival window $[0, H_{\mathrm{arr}}]$ of 2 weeks (10 working days; 1 week gives only 5 daily batches and 1 weekly one), then the factory runs until every order is done (drain). An initial backlog at $t = 0$ instead of a warm-up (Zhang et al. also start with a job available at $t = 0$). Arrival rate scaled to a target utilization (e.g. 80–90 %); 10–20 seeds per setting rather than longer episodes | own after Zhang et al. 2026 (preprint), user (1–2 weeks) |
| D13 | Hindsight comparison: a static CP-SAT plan over all orders with their release dates, executed in the DES with the same scenario factors (and the same rescheduling policy for deviations), so the gap isolates the cost of not knowing arrivals. A comparison point, not a lower bound (time limit) | own, review point 8 |

## 4. Steps (one at a time, tests, wait for approval)

0. **Spike (throwaway):** mask in `Simulation` on a hand instance (two orders, the second arriving at 10), one
   `update_plan` after the arrival. Decides D5 vs. rebuilding the simulation. Result reported, code not kept.
1. **Format + visibility:** `Order.accepted`, `Order.arrival` (schema 0.7, `schemas/instance-0.7.json`), package validation (D4),
   `visible(instance, t)`, name-keyed filtering of snapshot and plan. Negative test per validation rule
   (arrival > release, carrier across packages, run across packages).
2. **DES:** `ARRIVAL` event and mask (D5). Tests: zero-disturbance (no arrivals → identical log); hand instance with
   one arrival and a planner that appends the order (realized = plan after the arrival); masked operations never
   in the snapshot.
3. **Planning tool:** trigger `"arrival"`, D8–D11. Tests: CP-SAT and one rule plan the new order; budget fallback;
   no planner → error; checker on every plan; mini instance with a hand-computed result.
4. **Arrival sampler:** weekday rates (orders per day, from the MES) → arrival times, packages and their nesting
   with `carrier_generator`; episode window (D12). Tests: same seed same arrivals; rates reproduced in the mean.
5. **Metrics + documentation:** hindsight comparison (D13), arrival metrics (flow time from arrival, tardiness of
   arrived orders); `math/13` (event), `math/22` (sampler), `math/05` (trigger), `math/01` or a new component file
   for arrival and visibility, `notation.md` ($a_k$ arrival, $H_{\mathrm{arr}}$), protocol entry.

Definition of Done (CLAUDE.md) covered: format (1), checker (1: C4 with release, visibility through the sub-instance),
DES (2), rule (3), CP-SAT (3), tests (1–3), `math/` (5, each step adds its part).

## 5. Answered questions (user 2026-11-12) and what stays open

- **Nesting cycle, time of day:** D4 (one batch at the nesting time, midday or morning). Open at the company: daily
  or on given weekdays only; both become sampler settings.
- **Due date:** D4b.
- **Reaction to an arrival:** v1 complete rescheduling at every arrival (D8). Song et al. 2025 use no threshold: they
  reschedule event-driven at every arrival (PDF p. 14) and insert the new operations into the gaps after the arrival
  time (p. 15). **Kept in mind, not now (user):** CP-SAT insertion, i.e. machines and order per machine of the old
  operations fixed, only the new order free (own idea, no source); with thresholds deciding between insertion and
  complete rescheduling once forecast orders exist; useful for large instances.
- **Frozen horizon (later):** simplest form after Shiau et al. 2026 (`F5VQRD7Z`, preprint, p. 10, 17): operations
  planned to start in $[t, t+F]$ keep machine and start; $F \in \{0, 2\,\mathrm{h}, \text{rest of the shift}\}$ in
  an experiment. Physical commitment (a print set up, material ready) is the argument for $F > 0$. A started run
  already blocks its machine from setup to removal (C9, checked 2026-11-12: checker `machine_overlaps`, CP-SAT one
  interval per run, rules place the run back to back, DES by the planned order per machine; `math/03` §3–4).
- **Parameter files (user 2026-11-12):** many settings (nesting cycle, due-date rule and working days, rates, window,
  backlog, policy, seeds). Proposal: one Pydantic `ExperimentConfig` (frozen, `extra="forbid"`, as the CLAUDE.md
  architecture already plans), stored as **JSON** like instances and scenarios (no YAML dependency), one file per
  experiment, results carry its hash. Built with the sampler (step 4), not before.
- **Open:** utilization target and order volume per day (company data); whether nesting may top up an existing,
  not yet started carrier (v1: no).

## 6. Sources (checked in Zotero, collection MA, 2026-11-11)

- Yang & Geunes 2008 (`E4JW2F97`), EJOR 189(3), 1267–1283: predictive–reactive scheduling with uncertain future
  jobs on a single resource; planned idle time for uncertain jobs, disruption and wasted-idle-time costs (abstract,
  PDF p. 4–5); reactions right shift and left shift (p. 6–7); classification a priori / completely reactive /
  predictive–reactive (p. 2–3). For the later expected-orders step.
- Song et al. 2025 (`999TFMAJ`), Electronics 14(17), 3397: FJSP with workers and random job arrivals, insertion
  instead of rescheduling from scratch (abstract, PDF p. 4, 6); test: Brandimarte instances, arrival time uniform in
  $[1, C_{\max}]$ after pre-scheduling, compared with right-shift rescheduling (p. 20). For Q4.
- Zhang et al. 2026 (`UTY4Q8FP`), arXiv preprint, **not peer-reviewed**: dynamic FJSP from Brandimarte and Hurink
  with jobs released online; four non-stationary arrival distributions in an arrival window $0.6H$; unfinished jobs
  charged at the episode end; baselines Myopic (currently released jobs only), Rolling-horizon, MSA, SAA,
  expected-value optimization (EV), eight PDRs (PDF p. 6–7, Appendix A). For D12, the episode design, and the
  baselines of the expected-orders step.
- Garces et al. 2026 (`XL9MTY8L`), arXiv preprint, **not peer-reviewed**: sampled future request scenarios with
  commitments only to requests already observed (PDF p. 1–4). Robotics, not production; analogy only.
- Shabtay & Gilenson 2023 (`E3U6TI9C`), Wu et al. 2020 (`R5U9MZI5`), Jia et al. 2024 (`YQRKB6K8`), Wu et al. 2024
  (`HJXTMZMZ`): abstracts read only; relevant to the expected-orders step (multi-scenario, buffering,
  scenario predict-then-optimize), not to this one.
- Arrivals as a standard dynamic event: Li et al. 2021 (`7VCTD9GM`, p. 1, 3); Ouelhadj & Petrovic 2009
  (`DG38JM6L`, p. 3) on periodic, event-driven and hybrid rescheduling.
- Weekday Poisson rates for the sampler: **no source in the library [uncertain]**.
- Own modeling: D2–D13.
