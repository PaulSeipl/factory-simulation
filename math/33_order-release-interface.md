# 33 Interface to order release (nesting, forecast, reserve)

Scope note (2026-11-16). Records where the arrival forecast and the capacity reserve of the advisor's vision belong
in the model, what the literature in the library says about it, and what is in and out of scope. **Nothing of this
is implemented.** It refines the entries "Interface to nesting by capacities" and "Arrival forecast" of
[32](32_target-data-model.md) §2.

## 1. Prose description

**Real process.** Designed orders wait in a queue until nesting binds them to carriers ([07](07_order-arrivals.md)
§1). Nesting receives the free mill time and print time (and the free plate sets, ignored here: there are enough
today, user 2026-11-16) and binds only what fits. Orders it does not bind stay in the queue and take part in the
next nesting with their due date unchanged.

**Vision of the advisor (user 2026-11-13, 2026-11-16).** A routine: one print per day, post-processing of a print
takes almost three days (a *cycle*), a new cycle starts every day. Day 1 of a cycle prints the secondary parts and
mills the primary parts; day 2 mills the secondary parts, with QM and rework; day 3 finishes. If too many orders
are bound on one day, the mill is filled by their secondary parts on the next day, nesting finds no mill time for a
new print, the next print comes a day later and is large again. To prevent this, capacity of the next day is
reserved for the orders expected then. The expected numbers are a forecast given by Fidentis (MES or elsewhere),
not computed by the planning tool.

**Where it belongs.** In the terms of workload control (WLC) the nesting queue is the pool of unreleased jobs and
nesting is the job release function: WLC "buffer[s] the shop floor against external dynamics by creating a pool of
unreleased jobs", and workload norms should make the queues on the shop floor stationary (Land & Gaalman 1996,
p. 535). For make-to-order companies the pre-shop pool is meant to make the shop floor "independent of variations
in the incoming order stream" (Stevenson et al. 2005, PDF p. 10). The forecast and the reserve are therefore
parameters of the **release rule**, one level above the planning tool of this thesis, which schedules what has
been released. The planning tool is involved in one place only: the free capacity handed to nesting is read from
its current plan.

**Decision (user 2026-11-16).** The interface is documented here and in the modeling chapter of the thesis as an
external input with its goal (level the load, daily cycle). The planning tool does not form carriers. Forms of
influence that keep the model are listed in §6.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md). All are quantities of this note, none exists in code.

| Symbol | Meaning |
|---|---|
| $\mathrm{cap}_{m,\nu}$ | capacity of resource $m$ (mill, printer) on day $\nu$, in minutes |
| $\mathrm{rem}_{m,\nu}(t)$ | remaining capacity at $t$: $\mathrm{cap}_{m,\nu}$ minus the time of the frozen and planned operations of the current plan on $m$ on day $\nu$ |
| $\mathrm{res}_{m,\nu}$ | reserve on $m$ and day $\nu$ for orders expected but not yet bound; external input (Fidentis) |
| $N^{\mathrm{nest}}_\nu$ | number of orders nesting binds on day $\nu$ (toy model, §3) |
| $\psi^{\mathrm{I}}$, $\psi^{\mathrm{II}}$ | mill time one order needs on day 1 of its cycle (primary parts) and on day 2 (secondary parts, QM, rework) (toy model) |

The forecast itself is the mean number of orders per weekday, $\mu(w)$ of [07](07_order-arrivals.md) §3a.

## 3. Rules (not plan constraints)

(N1) Capacity signal. At a nesting time $t \in \Gamma^{\mathrm{nest}}$ nesting may use on resource $m$ and day $\nu$
at most the remaining capacity minus the reserve:
$$\max\bigl(0,\ \mathrm{rem}_{m,\nu}(t) - \mathrm{res}_{m,\nu}\bigr)$$
For printers the signal has to be free gaps, not a total per day ([32](32_target-data-model.md) §2).

**Toy model of the cycle (own derivation).** One mill with capacity $\mathrm{cap}$ per day, identical orders,
deterministic times, a queue that is never empty. Day $\nu$ carries the primary parts of the orders bound that day
and the secondary parts of the orders bound the day before:

(N2) $$\psi^{\mathrm{I}} N^{\mathrm{nest}}_\nu + \psi^{\mathrm{II}} N^{\mathrm{nest}}_{\nu-1} \le \mathrm{cap}$$

If nesting binds greedily, (N2) holds with equality, with the balance point
$N^{*} = \mathrm{cap} / (\psi^{\mathrm{I}} + \psi^{\mathrm{II}})$, and a deviation from it is multiplied by
$-\psi^{\mathrm{II}} / \psi^{\mathrm{I}}$ from one day to the next. For $\psi^{\mathrm{II}} > \psi^{\mathrm{I}}$
(the case at the company: secondary milling includes QM and rework, user 2026-11-16) the deviation alternates in
sign and grows: a large day, a small day, a larger day, a day without a print. Example $\mathrm{cap} = 18$,
$\psi^{\mathrm{I}} = 1$, $\psi^{\mathrm{II}} = 2$, start at 7: $7, 4, 10, 0, 18$. With $\psi^{\mathrm{I}} = 2$,
$\psi^{\mathrm{II}} = 1$: $7, 5.5, 6.25, 5.875 \to 6$.

(N3) Reserve for the next day. Binding on day $\nu$ must leave the primary milling of the $\mu$ orders expected on
day $\nu + 1$:
$$\psi^{\mathrm{II}} N^{\mathrm{nest}}_\nu + \psi^{\mathrm{I}} \mu \le \mathrm{cap}$$
With $\mu = N^{*}$ this gives $N^{\mathrm{nest}}_\nu \le N^{*}$: the reserve from a forecast and a fixed daily quota
are the same rule in the stationary case; the forecast version adapts when $\mu$ differs by weekday. (N3) is (N1)
with $\mathrm{res} = \psi^{\mathrm{I}} \mu$ on the mill of the next day.

The toy model shows the mechanism, not the size of the effect: one mill, two days, no workers, no rework rounds,
no disturbances.

## 4. Objective function

Not affected.

## 5. Implementation in code

None. State of the code against this note:

- Nesting is emulated in the arrival generator before the run ([07](07_order-arrivals.md) §3a,
  [21](21_instance-generator.md) §4a): every accepted order is bound at the first nesting time, without a look at
  the plan. Arrivals are exogenous and equal for all policies; the comparison with hindsight rests on this.
- Consequence: the pattern of §1 (no print on a day) cannot occur in the current experiments. A large package is
  printed and waits before the mill instead. The experiments neither confirm nor refute the vision.
- (N1) with $\mathrm{rem}$ from the plan makes the arrivals depend on the policy (closed loop): nesting would have
  to run inside the DES loop and the common instance of the hindsight comparison would be lost.
- A fixed quota per day (orders above it roll to the next nesting time) needs no plan and stays in the generator.

## 6. Assumptions and open points

- **Out of scope:** forming carriers by the planning tool (integrated nesting and scheduling); the closed loop of
  (N1) in the DES. The title's "persistent batch dependency" covers scheduling given carriers; it does not exclude
  forming them, but that exceeds scope and time budget (user 2026-11-16).
- **Influence that keeps the model:** the planning tool reports the capacity signal (N1) (recommended, the
  interface of this note); outlook: it decides which carriers share a print run, or holds a package back.
- **Possible experiment (not decided):** fixed quota on/off in the generator, once the routes match the real
  process (the current routes are shorter, user). Lead times must then be measured from the acceptance
  ($\bar F^{\mathrm{acc}}$, [23](23_metrics.md)), not from the arrival: a pool can shorten the time on the shop
  floor without shortening the total time (Kanet, as reported by Stevenson et al. 2005, PDF p. 13).
- **Risk of the release rule:** release rules with limited balancing "often show a deteriorated lead time
  performance" in simulations (Land & Gaalman 1996, p. 538).
- **To clarify with the advisor:** the size of $\psi^{\mathrm{II}} / \psi^{\mathrm{I}}$ with real times; whether the
  failure rate rises with the packing density of a plate (unknown, user), which would make $\psi^{\mathrm{II}}$
  grow with $N^{\mathrm{nest}}$; who computes the signal (MES or planning tool).
- Rework rounds are not in the routes ([32](32_target-data-model.md) §2), so the model's secondary milling is
  lighter than the real one.

## 7. Sources

Checked in Zotero (collection MA), 2026-11-16; full references in [references.md](references.md).

- Workload control, pool and release: Land & Gaalman 1996 (`ZNV6S3HF`), pp. 535, 538.
- Pre-shop pool in make-to-order; Kanet's objection: Stevenson et al. 2005 (`KGNSGYS8`), PDF pp. 10, 13 (printed
  pages not verified **[uncertain]**).
- Batch decisions from forecast data on near-future arrivals ("look-ahead strategies"): Van der Zee 2003
  (`CWYKJI6K`), p. 1480. The closest source for a forecast in a batching decision; it concerns the start of a
  batch machine, not a capacity reserve.
- Nesting and scheduling in AM: "few studies simultaneously dealing with both" (Oh et al. 2020, `V72H58FM`, PDF
  p. 2); decisions "traditionally kept separate or loosely integrated" (Pinto et al. 2024, `UWF679PX`, PDF p. 2).
- Pinto et al. 2024 (PDF p. 5) report that Thürer et al. (2021) proposed workload control for the post-processing
  shop of AM. **Not in the library, not read**; likely the closest related work.
- Not found in the library **[uncertain]**: a source for a capacity reserve derived from an arrival forecast; a
  source for the instability of capacity-gated release. Kingsman 2000 (`5ENPAG8F`, input–output control) is in the
  library but was not read.
- Own: the placement of the forecast at the release level, (N1), the toy model (N2), (N3).

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-11-16 | uncommitted | Created: placement of forecast and reserve, capacity signal (N1), toy model (N2), (N3), sources, scope. |
