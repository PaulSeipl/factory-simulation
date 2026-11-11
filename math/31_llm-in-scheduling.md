# 31 LLMs in scheduling: literature note and scope decision

Files `3x` are literature notes and scope decisions that do not belong to one model component.

## 1. Decision

**2026-10-30, user:** option **A**: no LLM component in the thesis for now; LLMs appear in related work and future
work only. Option **B** (LLM as offline generator of rules or operators) and possibly **C** (LLM as bounded online
advisor) may be tried later. The thesis core stays the GA, with dispatching rules and CP-SAT as baselines.

## 2. The user's assessment of the field

Based on recent papers the user read (not all of them are in the Zotero library; to be added before they are cited):

- Many recent studies use LLMs as **assistance or guidance**: for taking decisions, for constructing models, or for
  generating rules.
- The main gaps are **domain breadth**, **feasibility under real constraints** and **end-to-end decision support**.
- The clearest gap is not whether LLMs can help with scheduling, but whether they can handle harder, more realistic
  settings with **guaranteed feasibility, transparent reasoning and real-time adaptability**.
- The field is strong on **hybrid prototypes** and weak on **generalizable, trustworthy, production-ready decision
  models**.

## 3. What the library supports

Shiau, Chen & Fan (2026, `F5VQRD7Z`, preprint, not peer-reviewed) review 43 studies from 2024–2026. Their numbers
are consistent with the user's assessment. The figures on individual studies are taken from that review; the
original papers have not been checked **[uncertain]**. Pages are the printed page numbers of the preprint.

| Gap (user) | Evidence in Shiau et al. (2026) |
|---|---|
| Hybrid prototypes dominate | LLM as offline generator of rules, heuristics or code in 44 %, as invoker of solvers in 23 %, as direct solver in 14 % (Table 1, p. 3) |
| End-to-end decision support | only 16 % close the event–decision–execution loop with measured results; 44 % only static benchmarks (Table 2, p. 3) |
| Domain breadth | injected events are mainly breakdowns (11 studies) and order arrivals (7); material delays and due-date changes in none (Table 3, p. 6) |
| Feasibility | best fine-tuned direct solver: 97 % valid schedules on small, 79 % on larger instances; prompted general models collapse (445 % makespan gap for GPT-4o-mini) (p. 4) |
| Real time | 12.95 s per decision for the fine-tuned solver, about 20 s for an online algorithm selector (pp. 4, 6) |
| Transparent reasoning | general LLMs explaining whether a perturbation needs rescheduling: 59 % correct (GPT-4), 35 % (LLaMA-3.1) (p. 4) |
| Trustworthiness | none of the event-injection studies measures schedule stability; only two compare with and without LLM (pp. 6–7) |

Most promising role in the review: LLM-evolved dispatching rules, run without the LLM on the shop floor, e.g.
makespan −21.52 % against existing rules, tardiness −18.63 % against EDD (Table 4, p. 6).

## 4. The paper itself

- **Design:** for each event a deterministic rule chooses among three verified candidates: ignore, right-shift repair,
  full rescheduling under a frozen horizon. Criteria: damage of the event, share of it recovered by rescheduling, a
  floor on a five-part stability score, and an anti-thrashing interval (pp. 7–13).
- **Role of the LLM:** a locally hosted model audits the rule's recommendation on the same verified figures, with a
  strict output schema. It cannot create schedules, falls back to the rule on any failure, and a human planner takes
  the final decision (pp. 14–15).
- **Limits of the evidence:**
  - the validation used a deterministic stub instead of a real LLM ("no production LLM was available", p. 21), so it
    shows fail-safe integration, not the quality of the LLM's judgment;
  - the gated policy is not compared with simpler policies; only a protocol for that comparison is proposed (p. 24);
  - the thresholds and stability weights are set by the authors, not calibrated.
- **Useful for this thesis without any LLM:** frozen-horizon definition and its trade-off
  ([05](05_rescheduling-frozen-part.md) §6), anti-thrashing as the counterpart of the periodic safety net
  ([05](05_rescheduling-frozen-part.md) §6), stability measures incl. Kendall concordance of machine sequences
  ([23](23_metrics.md) §6), and the proposed policy comparison (ignore / always repair / always reschedule / gated) on
  identical event streams, which the DES of this thesis can run.

## 5. Own assessment (answer to the user)

- **Feasibility is mainly an architecture question.** If an independent checker or solver has the last word
  ("LLM proposes, verifier decides"), feasibility is guaranteed by construction; Shiau et al. do this, and so does this
  thesis (every plan passes `check_schedule`). The open question is whether an LLM adds **measurable value over a
  strong non-LLM baseline** once feasibility is enforced (the "controls" gap above).
- **"Production-ready" cannot be shown in a thesis** (it needs deployment and users over time). What can be shown is a
  closed-loop evaluation in simulation: realistic disturbances, verified feasibility, stability metrics, ablation with
  and without the LLM.
- The infrastructure of the thesis (DES with disturbances, independent checker, stability metrics, rule / CP-SAT / GA
  baselines) is the kind of testbed that the reviewed studies mostly lack.

## 6. Options for later

| Option | LLM role | For | Against |
|---|---|---|---|
| A (chosen) | none; related and future work | stays on the GA plan | – |
| B | offline generator of dispatching rules or GA operators, evaluated in the DES | reproducible (generated code is fixed); feasibility via checker; the role with the best reported results (p. 6); fits next to the GA | contribution is "LLM as algorithm designer", not decision support |
| C | bounded online advisor for the rescheduling decision, ablation against the rule | addresses the end-to-end gap directly | an LLM call per decision: non-deterministic, depends on model version, slow over many simulated events, costly to reproduce |

## 7. Sources

- Shiau, J.-Y., Chen, P.-Y., & Fan, C.-Y. (2026), see [references](references.md).
- The user's further papers: not yet in the library.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-30 | 17d05a8–28ac70f | Note on LLMs in scheduling: user's assessment, evidence from Shiau et al. (2026), own assessment, options, decision A. |
