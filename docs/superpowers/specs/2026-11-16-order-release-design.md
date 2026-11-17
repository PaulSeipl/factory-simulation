# Order release: forecast and capacity reserve — design (draft)

Status 2026-11-16: draft for review, nothing implemented. Model background: `math/33_order-release-interface.md`.

## 0. Finding before any code: the current route cannot show the effect

Mean machine minutes per order in `experiments/arrivals-rate6.json` (generated instance, 67 orders, shortest
option per operation; utilization roughly = load / (10 working days × machines × 570 min), backlog ignored):

| Resource | min/order | Utilization |
|---|---|---|
| mill (3) | 59.3, of which `mill_blank` 38.2 ($\psi^{\mathrm{I}}$), `mill_carrier` 21.1 ($\psi^{\mathrm{II}}$) | ~23 % |
| oven (1) | 41.6 | ~49 % (bottleneck) |
| print (2) | 23.0 | ~14 % |
| qm (1) | 4.6 | ~5 % |

So $\psi^{\mathrm{II}} / \psi^{\mathrm{I}} \approx 0.55 < 1$, the stable case of the toy model (N2), and the mill is far
from saturation: a mill gate would never bind. QM is a separate machine with 10–15 min per carrier and no rework;
in the real process rework is milling and dominates (user 2026-11-16). **An experiment on this route would show
"no effect" as an artefact of the route.** The release code can be built and tested on a hand-made instance; the
experiment needs route data closer to the real process first (open question Q1).

## 1. Goal

Make the release rule of `math/33` executable and testable: which accepted orders nesting binds at a nesting time,
given a capacity signal and a reserve from a forecast given by Fidentis (an input, not computed here).

## 2. Design

**Orders vs. packages.** The seed fixes the orders, their acceptances and due dates (as now). The release rule
fixes arrival, carriers and runs. `nest()` is unchanged and runs on whatever is bound.

**Release rule** `release(pool, t, signal) -> orders to bind`, pool = accepted, not yet bound orders in EDD order.
Variants:

| Rule | Signal | Loop | Step |
|---|---|---|---|
| `all` | none | open | A (default, today's behaviour) |
| `quota` | at most $q_w$ orders (or mill minutes) per nesting on weekday $w$ | open | A |
| `gate` | (N1): $\mathrm{rem}_{\mathrm{mill},\nu}(t) - \mathrm{res}_{\mathrm{mill},\nu}$ from the current plan | closed | B |

Reserve (N3): $\mathrm{res}_{\mathrm{mill},\nu+1} = f(w) \cdot \hat\psi^{\mathrm{I}}$ with the forecast $f(w)$
(orders expected on weekday $w$; parameter, may differ from the true rate $\mu(w)$) and $\hat\psi^{\mathrm{I}}$
the mean primary mill time per order estimated from the route. Without a forecast: $\mathrm{res} = 0$ (greedy
gate). Mill only; printers as free gaps (`math/32` §2) and plate sets are named and skipped.

**Step A (open loop).** Release inside `arrival_generator`: each nesting time takes the pool, binds per rule, the
rest rolls to the next nesting time with its due date unchanged. Arrivals stay exogenous; all existing experiment
machinery (hindsight included) works unchanged.

**Step B (closed loop).** At each nesting time the release rule reads the current plan, so arrivals depend on the
policy. Needs:
1. a NESTING time point in `execute` (like the safety-net wake),
2. a growing instance: the DES state is indexed by the full `CompiledInstance` fixed at the start. Proposal:
   `Simulation.grow(ci')` remaps its per-operation state by `(order_id, op_id)` and re-indexes the event heap
   (machines and workers unchanged). Alternative: replay from 0 with the grown instance (no DES change, exact if
   the planner is deterministic, but ~n²/2 simulated days over n nesting times),
3. scenario factors keyed by operation identity (today they are drawn in graph order, so a different set of
   carriers would change every factor): a keyed sampler for closed-loop runs; the existing sampler stays, so the
   existing results stay reproducible,
4. `visible` from the grown instance (the pool is never visible to the planner).

**Experiment framing.** Hindsight is undefined when arrivals depend on the policy. Release experiments hold the
planner fixed (CP-SAT at arrivals) and vary the rule: `all`, greedy `gate`, `gate` with reserve, `quota`. The
planner-vs-hindsight experiments keep `all`. Metrics: lead time from acceptance (M8, covers Kanet's objection),
pool time, prints per day, mill load per day.

## 3. Tests

- `all` reproduces today's instances exactly (regression; the zero-change test of this feature).
- Hand-computed one-mill instance with $\psi^{\mathrm{II}} > \psi^{\mathrm{I}}$: greedy gate gives the toy sequence
  $7, 4, 10, 0$; with the reserve it stays at $N^{*}$.
- Quota: orders above the quota roll over, due dates unchanged, EDD order in the pool.
- No leakage: the planner never sees a pool order.
- Step B: `grow` keeps the state of the old operations (zero-disturbance run with gate = plan replayed); keyed
  scenario factors equal for an operation regardless of the other carriers.
- Negative tests: forecast or quota for an unknown weekday, negative values, `gate` without a planner.

DoD note: the release rule is not a plan constraint, so the checker and CP-SAT stay unchanged; `math/33` §5 has to
say so.

## 4. Open questions

- **Q1 (blocker for the experiment, not for the code):** route data close to the real process: how much mill time
  secondary milling, QM and rework take per order, and whether rework is on the mill. Fidentis data, or a
  stress variant of the route that we label as such?
- **Q2:** signal in orders or in mill minutes? Minutes match the MES interface (`math/32` §2), orders match the
  advisor's "default amount of orders".
- **Q3:** step B via `grow` (recommended) or replay?
