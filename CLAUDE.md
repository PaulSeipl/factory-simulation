# CLAUDE.md

Master's thesis (LMU, Computer Science): adaptive, event-driven scheduling for a Flexible Job Shop Scheduling Problem (FJSP) in additive manufacturing (dental prostheses), with extensions: precedence constraints within an order (incl. two-path reconvergence at QM), batches/loads, workers as a resource, and dynamic events (deviations, arrivals, breakdowns). The primary solver will most likely be a GA; dispatching rules and CP-SAT serve as baselines and as an oracle. Language: Python.

## Working style

- **Be critical.** Push back when a suggestion does not hold up technically or methodologically. No agreement for its own sake.
- **Work step by step.** For larger tasks: state the plan, implement one step, run the tests, show the result, wait for approval.
- **Read before writing.** Look at existing modules and models; adapt rather than overwrite. Ask when something conflicts with existing code.
- **Back scientific claims with sources.** Every claim about methods, modeling or results from the literature needs a source (authors, year, title, venue, DOI/URL). If you are unsure whether a source exists or actually contains the claim, mark it **[uncertain]**. **Never invent sources, DOIs or best-known values**, and never reconstruct benchmark instances from memory.
  - **Look up sources in the local Zotero library first**, using the `zotero` skill (collection MA). Check the claim against the paper's text (`text --grep`), not only the title or abstract, and give the Zotero item key.
  - If the library has no source for a claim, mark the claim **[uncertain]** and say it was not found in the library, even when the source is known from memory.
- **Stay in scope.** Only implement what was asked. MES integration is not part of the thesis.
- **Maintain the protocol `math/protocol.md`.** At the end of every pass that changes code, tests, data, notebooks or `math/`, add an entry at the top: date and topic, what was **decided** (and by whom), what was **done**, what was **found**, what stays **open**, each with references (`math/` files, modules, notebooks, commit hash once committed).

## Terminology (binding)

@math/terminology.md

## Architecture

- **Two layers:**
  1. File-format models with **Pydantic v2** (`frozen=True`, `extra="forbid"`), validated once at load time: `Instance`, `Schedule`, later scenario and experiment config.
  2. Internal index-based form `CompiledInstance` (dataclass, `frozen=True`, `slots=True`, tuples/NumPy). Simulator, rules, CP-SAT and GA work **only** with this. No Pydantic in the hot path.
- **Time** is always an integer in the unit `time_unit` (default: minutes). No floats for time points or durations.
- **Predecessors** reference only operations of the same order. Coupling between orders arises exclusively through loads, not through `predecessors`.
- **One feasibility checker** validates every plan, whether it comes from a rule, CP-SAT, the GA, or is a realized schedule from the DES. It is written **independently** of the CP-SAT model and returns a list of concrete violations.
- **DES:** custom event loop (heapq), no SimPy. State must be copyable. The planner only sees the snapshot, never the sampled disturbances (no information leakage).
- **Data storage:** instances and scenarios as JSON, Brandimarte benchmarks as original `.fjs` files, results as CSV, event logs as JSON Lines. **No pickle.**

## Thesis (`../seipl27`)

- The LaTeX thesis lives in `../seipl27` (own Git repo, own `CLAUDE.md` and skills). It takes the modeling chapter from `math/` and all numbers, tables and figures from this project.
- When a `math/` change affects a section already written in the thesis, name the section under **open** in the protocol entry.
- Thesis figures are produced by code here (notebooks or scripts) and exported as PDF to `../seipl27/Bilder/`. The generating code stays here so every figure can be reproduced.
- Thesis writing passes are logged in `math/protocol.md` as well, title prefixed `[thesis]`.

## Definition of Done for a model feature

A feature (e.g. loads, workers, JPC) is only done when it is included in:
1. The instance format (Pydantic model, validation, schema version bumped)
2. The feasibility checker
3. The DES
4. At least one dispatching rule
5. The CP-SAT model
6. Tests: zero-disturbance test (factor 1, no events → realized schedule = plan, makespan = CP-SAT value), checker on all plans, one mini instance with a hand-computed result
7. **Documentation in the `math/` folder** (see below)

## Tests

- pytest; run before completing each step.
- One negative test per validation rule.
- The zero-disturbance test and negative tests are never skipped, not even under time pressure.

## Mathematical documentation (`math/`)

`math/` documents the formal model and is the basis for the modeling chapter of the thesis. The folder is tracked in the Git repository (since commit `6463434`), so change-log entries and protocol entries carry commit hashes.

**Mandatory:** After every implementation or change of the model, a constraint, an objective function or a rescheduling rule, `math/` is updated **in the same step**. A step that changes the model is not complete without this documentation. If code and `math/` contradict each other, report it; do not silently adjust one of them.

**Structure:**
- `math/README.md`: overview and index of all files, one sentence per file
- `math/notation.md`: central notation (sets, indices, parameters, variables). Add new symbols **here first**; never assign a symbol twice or inconsistently.
- One file per model component, numbered: e.g. `01_basic-fjsp.md`, `02_precedence-jpc.md`, `03_carriers.md`, `04_workers.md`, `05_rescheduling-frozen-part.md`
- `math/references.md`: all sources in one place
- `math/protocol.md`: working protocol, one entry per pass (decisions, work, findings, open points), newest first

**Structure of each component file:**
1. **Prose description:** what is modeled and why (link to the real process)
2. **Sets, parameters, variables:** only the newly introduced ones, with a reference to `notation.md`
3. **Constraints:** numbered (C1), (C2), … in LaTeX, each with a one-sentence explanation
4. **Objective function**, if affected
5. **Implementation in code:** module/function; for CP-SAT the mapping (e.g. optional intervals, `AddNoOverlap`, `AddCumulative`); justify any deviation between formula and code explicitly
6. **Assumptions and open points:** what was simplified, what still needs to be clarified with the supervisor
7. **Sources:** where the formulation or idea comes from; mark own modeling as such
8. **Change log:** date, Git commit hash of the code, what changed

**Formulas** in LaTeX with `$...$` inline and `$$...$$` for display. Example of the style:

> (C2) Precedence within an order: an operation $o'$ starts at the earliest when its predecessor $o$ has finished.
> $$S_{o'} \ge S_o + \sum_{m \in M_o} p_{o,m}\, x_{o,m} \qquad \forall (o, o') \in P$$

**Citations:** complete with author(s), year, title, venue, pages, DOI. Only cite sources that were actually used. Mark uncertain details as **[uncertain]**. Already verified:
- Brandimarte, P. (1993). Routing and scheduling in a flexible job shop by tabu search. *Annals of Operations Research*, 41, 157–183. https://doi.org/10.1007/BF02023073 (origin of the MK benchmarks and the `.fjs` format)