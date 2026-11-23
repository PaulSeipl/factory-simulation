# 22 Disturbance scenarios

Files `2x` describe data generation and experiments.

## 1. Prose description

A **scenario** holds the sampled disturbances for one seed (terminology in `CLAUDE.md`). Version 1 covers processing-time deviations only: every operation runs faster or slower than planned by a random factor. Scenarios are sampled separately from the instance, so that one instance can be evaluated under many disturbance draws, and they are seen only by the DES, never by a planner.

## 2. Sets, parameters, variables

New symbols, registered in [notation.md](notation.md):

- $\varepsilon_o > 0$: disturbance factor of operation $o$ (realized / planned processing time before rounding)
- $\sigma \ge 0$: standard deviation of $\ln \varepsilon_o$

## 3. Distribution and realized durations

$$\ln \varepsilon_o \sim \mathcal{N}\!\left(-\tfrac{\sigma^2}{2},\ \sigma^2\right) \quad \text{i.i.d.}, \qquad \text{so } E[\varepsilon_o] = e^{-\sigma^2/2 + \sigma^2/2} = 1$$

The mean factor is 1: on average there is no systematic delay, only variability. The log-normal distribution keeps factors positive and right-skewed (long delays are more likely than equally large speed-ups). Its use for processing times is **[source needed]**.

The factor belongs to the operation, not to an (operation, machine) pair: whichever machine the plan chooses, the realized processing time is

$$\hat p_o = \max\!\big(1,\ \lfloor p_{o,\bar m(o)}\, \varepsilon_o + \tfrac12 \rfloor\big)$$

i.e. rounded half up to an integer (time is integer, [01](01_basic-fjsp.md) §6) and at least 1. Half up instead of Python's `round`, which rounds halves to even (2.5 → 2). Because of the rounding, $E[\hat p_o]$ is not exactly $p_{o,m}$, and small processing times are affected most (e.g. $p = 1$ can only become longer).

$\sigma = 0$ gives $\varepsilon_o = 1$ for all operations and reproduces the plan exactly (zero-disturbance test, [13](13_des.md)).

**Start offsets.** Independently of the processing time, an operation may start earlier or later than planned (a worker pulls a job forward or starts it late). Per operation:

$$\Delta_o = \begin{cases} 0 & \text{with probability } q \\ U\{-\Delta^{-}_{\max}, \dots, \Delta^{+}_{\max}\} & \text{with probability } 1 - q \end{cases}$$

in minutes ($\Delta^{-}_{\max}$ = `max_early`, $\Delta^{+}_{\max}$ = `max_late`, uniform integer). An early start happens only if it is feasible (predecessors finished, machine idle, next in the planned machine order, order released); a late start delays the operation by $\Delta_o$ minutes after the moment it could actually start (released and ready), counted once ([13](13_des.md) §3). The offsets are drawn from a separate random stream (seeded with `"start-{seed}"`), so switching them on does not change the processing-time factors of a seed. Defaults $q = 1$, $a = b = 0$: no start deviation.

The scenario covers every compiled operation, incl. the operations of carriers and runs ([03](03_carriers.md)), keyed by owner and operation; for instances without carriers the operations and the random draws of a seed are the same as before. All operations use the same distribution (an assumption to revisit for the oven, whose program has a fixed duration).

**Operations with workers** ([04](04_workers.md), user and own, 2026-11-05): everything scales with $\varepsilon_o$ except the rest of a machine-less operation and fixed programs. Machine operation: $\hat p_o = \mathrm{round}(p\,\varepsilon_o)$ as above, its prefix and suffix $\hat a_o = \min(\mathrm{round}(a\,\varepsilon_o), \hat p_o)$ (suffix shortened if both together exceed $\hat p_o$); machine-less operation with prefix (Gegenbetten): $\hat a^{\mathrm{pre}}_o = \mathrm{round}(a^{\mathrm{pre}}_o\,\varepsilon_o)$, $\hat p_o = \hat a^{\mathrm{pre}}_o + (p_o - a^{\mathrm{pre}}_o)$, so the rest stays fixed (user); whole share: the operation's $\hat p_o$; oven batch: $\varepsilon_o = 1$ (program fixed); s-batch ([08](08_serial-batches.md)): the setup scales with the factor of the member with the smallest index, every member's duration without the setup with its own factor, $\hat p_j = \mathrm{round}(p^{\mathrm{su}}_s\,\varepsilon_{o_1}) + \sum_{o \in O_j} \mathrm{round}((p_{o,m} - p^{\mathrm{su}}_s)\,\varepsilon_o)$ (spec §4 (b); no extra stream; own). Unattended main runs of print and mill vary (user: the run-duration estimate is inaccurate).

**Keyed streams** (2026-11-18, for the release during a run, [33](33_order-release-interface.md) (N5)): by default one stream draws the factors in graph order, so an operation's $\varepsilon_o$ depends on which operations come before it. When nesting creates carriers and runs during the run, the set of operations depends on the release, and every factor would change. With `keyed=True` each operation draws its factor and its offset from its own streams, seeded by (seed, owner, operation): the same operation gets the same disturbance whatever else exists. Common random numbers across release policies then hold for the order operations; carrier and run operations carry the package number in their owner ID ($P$-prefix, [07](07_order-arrivals.md)), and packages differ between policies, so their disturbances are drawn afresh (own assessment: a limit of the comparison, to be named). The default stays, so earlier results stay reproducible.

The processing-time deviation is proportional to the planned duration ($\hat p_o - p = p(\varepsilon_o - 1)$ before rounding); the start offset is absolute. Both are own modeling choices without data yet; the offset distribution may be replaced once data from the company is available.

## 4. Implementation in code

`simulation.sim.scenario`: `Scenario` (Pydantic, frozen, `extra="forbid"`; instance name, seed, $\sigma$, $q$, $\Delta^{-}_{\max}$, $\Delta^{+}_{\max}$, one factor and one start offset per `(order_id, op_id)`; stored as JSON), `sample_scenario(instance, sigma, seed, q=1, max_early=0, max_late=0, keyed=False)` (`random.Random(seed).lognormvariate` for the factors, `random.Random(f"start-{seed}")` for the offsets; keyed: `random.Random(f"{seed}/{owner}/{op_id}")` and `random.Random(f"start-{seed}/{owner}/{op_id}")` per operation), `realized_duration(planned, factor)`, `factors_by_index(ci, scenario)` (checks that the scenario belongs to the instance and covers every operation exactly once).

Tests (`tests/test_scenario.py`): same seed same factors, other seed other factors; one factor per operation; $\sigma = 0$ gives exactly 1; mean of 2400 factors with $\sigma = 0.3$ within $1 \pm 0.03$; rounding half up and minimum 1; scenario/instance mismatch, missing and duplicate factors rejected; JSON round trip. Keyed: the shared operations of a Fidentis instance with 3 and with 9 orders (orders, carriers, runs) get the same factor and offset (the default stream does not); mean one, seed dependence, $\sigma = 0$ gives exactly 1.

## 5. Assumptions and open points

- Factors are independent across operations; no machine- or order-specific bias, no correlation (e.g. a slow printer slowing all its jobs).
- Only processing-time deviations and start offsets; machine breakdowns, order arrivals and QM rework loops follow (new scenario fields and DES events).
- Start offsets are independent of the operation, the worker and the time of day; without data this is the simplest assumption.
- The factor is sampled for every operation, including those that will never be started in a replanning setting; this keeps a scenario independent of the plan.
- **To clarify:** realistic values of $\sigma$ for the dental production process (data from the company?).
- **First look at company data (2026-11-20, MES backup of 2026-11-10, own query, protocol (98)):** worker-step times are
  not usable per step (214 of 672 done tasks under 30 s, half of them booked within 2 minutes of the previous one;
  tasks left open overnight). Machine runs, realized / estimated duration, filtered to 0.33 to 3: milling 58 runs,
  median 1.14, sd of the log ratio 0.45; printing 7 runs, 1.25 and 0.65; one machine each. So the mean-one
  assumption does not hold for milling (estimates too low on average), and $\sigma \approx 0.45$ is a candidate
  for machine runs. The cutoff is arbitrary and $\sigma$ depends on it; the log-normal shape is untested.

## 6. Sources

- Log-normal processing times: **[source needed]**.
- Own: mean-one parametrization, per-operation factor, rounding.

## 7. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-22 | 2b20b69 | Scenario with log-normal processing-time factor per operation, realized duration with half-up rounding. |
| 2026-10-29 | 17d05a8–28ac70f | Start offsets: 0 with probability q, otherwise uniform in [-a, b] minutes, separate random stream. |
| 2026-10-30 | 17d05a8–28ac70f | Late start offset relative to actual readiness (see 13). |
| 2026-11-02 | ee3b2b1–cd7ca2b | Scenarios over all compiled operations (carriers, runs). |
| 2026-11-05 | e5348b0–78e228d | Realized durations of operations with worker shares (rest and programs fixed). |
| 2026-11-18 | uncommitted | Keyed streams per operation (`keyed=True`), default unchanged. |
| 2026-11-18 | uncommitted | s-batch: setup with the factor of the first member, members without setup with their own. |
| 2026-11-09 | ef6f798 | Symbols renamed (protocol 2026-11-09 (24)): maximum early / late offset $a$, $b$ → $\Delta^{-}_{\max}$, $\Delta^{+}_{\max}$ ($b$ is the carrier, $a$ the prefix/suffix length). |
