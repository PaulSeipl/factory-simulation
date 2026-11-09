# Protocol

Working protocol of the thesis implementation: one entry per working pass, newest first. Each entry records what
was **decided** (and by whom), what was **done**, what was **found**, and what stays **open**, with references to
the component files of `math/`, to code and notebooks, and to the commit. The formal details live in the component
files; this protocol is the chronological index to them. Earlier passes (before 2026-10-29) are reconstructed from
the commits and the change logs of the component files and are therefore shorter.

---

## 2026-11-09 (25) — Symbol renames applied; literature correspondence; rule in notation.md — uncommitted

- **Decided (user):** apply all renames of entry (24) with worker index $z$ and $W_o$.
- **Done (Edit tool only, change log per file):**
  - [notation](notation.md): the rule (one base letter = one quantity; subscripts for index or subset; accents for
    variants of the same quantity; follow the literature; check before writing) in the header; all rows; new rows
    $\nu$, $\mathrm{ot}_{z,\nu}$, $e_{z,\nu}$; second correspondence table (workers, objectives, batching,
    carriers) against Berti et al. (2021), Wang et al. (2025), Dauzère-Pérès et al. (2024), Fowler & Mönch (2022),
    Potts & Kovalyov (2000), Pinedo (2022), Li et al. (2026), Lee et al. (2020), Liu et al. (2024).
  - [04](04_workers.md): $w \to z$, $d \to \nu$, $W_\eta \to W_o$ (prose: one qualified set per operation, Berti's
    $W_k$ per machine), $O_{w,d}, \bar O \to \mathrm{ot}_{z,\nu}, \overline{\mathrm{ot}}$, $L^{\mathrm{B}} \to
    p^{\mathrm{br}}$, $V_w \to V_z$; [13](13_des.md), [23](23_metrics.md) ($z$, $\nu$; $D_M \to N_M$);
    [11](11_dispatching-rules.md) ($\rho_o \to \underline{S}_o$, $f_m \to \phi_m$, $W_m \to V_m$, $B_m \to
    V^{\mathrm{q}}_m$, $w_k \to \mathrm{wr}_k$, successor $s \to o'$); [05](05_rescheduling-frozen-part.md)
    ($\tau \to \delta_t$, $B(o) \to \operatorname{bl}(o)$); [06](06_due-dates.md) ($\theta_k \to \mathrm{DDT}_k$,
    $w_i \to \theta_i$ with Pinedo, $s(f) \to \operatorname{spr}(f)$); [21](21_instance-generator.md)
    ($\mathrm{DDT}$); [22](22_scenarios.md) ($a, b \to \Delta^{-}_{\max}, \Delta^{+}_{\max}$);
    [03](03_carriers.md), [12](12_cp-sat.md) ($S^B_j \to S^{\mathrm{slot}}_j$, $z_{j,m} \to g_{j,m}$).
  - [references](references.md): Lee et al. (2020) `AUGM8B83`, Liu et al. (2024) `5YDNRDES`, Wang et al. (2025)
    `QJHCEX6V` added; notation uses added to Berti, Dauzère-Pérès, Fowler & Mönch, Pinedo, Potts & Kovalyov.
- **Found:**
  - The extracted text of Dauzère-Pérès et al. (2024) shows the printed page 422 at the end of the batching
    passage: capacity $b$ on p. 422 (the **[uncertain]** of entry (24) resolved).
  - Mine, by the new rule: $D_M$ (a count) next to $D_S$ (a deviation) → $N_M$.
  - Still open by the rule: $Q$ (carrier capacity in size units) and $Q_R$ (maximum carriers per run, generator)
    in [21](21_instance-generator.md) / [03](03_carriers.md).
  - Old symbols left only in change logs and the protocol (history), checked by search.
- **Open:** $Q$ / $Q_R$; code comments and notebooks use names, not symbols (unchanged); commit.
- **Decided (user, afterwards):** $Q$ / $Q_R$ stay (both carrier capacities). Mine, as the reason in
  [notation](notation.md): one quantity "capacity" on two containers (a carrier in size units, a run in carriers),
  the allowed pattern like $V_m$, $V_z$. Clash check of `math/` complete.

## 2026-11-09 (24) — Symbol-clash renames proposed; notation check made a standing rule — uncommitted

- **Decided (user):** when writing a new formula or adding a variable, always check `notation.md` first. Added to
  `CLAUDE.md` (section "Mathematical documentation", `notation.md` bullet), together with the clash check after
  every task, phase and at the end.
- **Proposed (mine, awaiting the user):** keep the core model and the standard scheduling letters ($O$, $W$, $w$,
  $b$, $\tau(b)$, $d_k$, $L_k$, $T_k$, $U_k$, the objective $f$, the carrier step $s$); rename the local helper
  symbols of the rule (11), the policy (05), the scenarios (22), the objectives (06) and the calendar durations:
  - late / early offset $b$, $a$ (22) → $\Delta^{+}_{\max}$, $\Delta^{-}_{\max}$ (offset family $\Delta_o$);
  - period $\tau$ (05) → $\delta_t$ (threshold family $\delta_C$, $\delta_S$, $\delta_f$);
  - overtime $O_{w,d}$, $\bar O$ (04) → $\mathrm{ot}_{w,d}$, $\overline{\mathrm{ot}}$ (upright like $\mathrm{br}$);
  - break length $L^{\mathrm{B}}$ → $p^{\mathrm{br}}$ (duration family $p$);
  - machine load $W_m$ (11) → $V_m$ (load family with $V_w$); backlog $B_m$ (11) → $V^{\mathrm{q}}_m$;
  - remaining work $w_k$ (11) → $\mathrm{wr}_k$; weights $w_i$ (06) → $\alpha_i$;
  - ready time $\rho_o$ (11) → $\underline{S}_o$ (earliest start, lower bound like $\underline{p}_o$);
  - machine free time $f_m$ (11) → $\phi_m$;
  - blockers $B(o)$ (05) → $\operatorname{bl}(o)$ (upright like $\operatorname{prev}(o)$);
  - successor $s$ in the LRP formula (11) → $o'$; spread $s(f)$ (06) → $\operatorname{spr}(f)$;
  - batch slot start $S^B_j$ (03, 12) → $S^{\mathrm{slot}}_j$ (frees the superscript B for the break);
  - day index $d$ vs. due date $d_k$: open, options in the user message.
  - Left: $\lambda$ (03) vs. $\Lambda_k$ (06) (case differs, both local).
- **Found:** thesis `seipl27/notation.tex` is a 3-line stub; no thesis text uses any of these symbols.
- **Decided (user, afterwards):** renames accepted in principle; ground the notation in the literature where
  possible. **Checked in Zotero** (full text, PDF pages):
  - Objectives: Dauzère-Pérès et al. (2024) `ZSNHKWD6`, PDF p. 4, Table 1: $d_j$ due date, $w_j$ job weight,
    $C_j$, $L_j, E_j, T_j, U_j$. Fowler & Mönch (2022) `H6SPCTKI`, PDF p. 4: $r_j$ release (or ready time),
    $p_j$, $d_j$, $w_j$. Pinedo (2022) `5Y6PACF8`, PDF p. 95: weights of objectives $\theta_1, \theta_2$ for
    objectives $\gamma_1, \gamma_2$, $\mathrm{Lex}(\gamma_1, \gamma_2)$. → our $d_k, L_k, T_k, U_k$ match; level
    weights $w_i$ → $\theta_i$ (Pinedo) instead of $\alpha_i$.
  - Due-date tightness: Li et al. (2026) `6GGUPZNL`, PDF p. 11: $D_i = A_i + (\sum_j t_{i,j}) \cdot DDT$, a factor
    named DDT, not $\theta$. → our $\theta_k$ is own; rename to $\mathrm{DDT}_k$ (frees $\theta$ for the weights).
  - Workers (DRC): Berti et al. (2021) `8F7AYGYK`, PDF p. 5: $W$ set of workers, $z$ worker index, $W_k$ candidate
    workers for machine $k$. Wang et al. (2025) `QJHCEX6V`, PDF p. 7, Table 2: $W = \{1, \dots, w\}$, worker index
    $s$, $F_s$ / $F_k$ total working time of worker / machine. → $W$ and $W_\eta$ match; worker index: literature
    uses $z$ or $s$, our $w$ clashes with the standard job weight $w_j$ (open, user message). Load $V_w$, $V_m$
    kept: Wang's $F$ would clash with the flow time $\bar F$ ([23](23_metrics.md)).
  - Batching: Potts & Kovalyov (2000) `26Z9YF55`, PDF p. 3 and Dauzère-Pérès et al. (2024) PDF p. 14
    **[uncertain: printed page]**: batch capacity $b$; Fowler & Mönch (2022) PDF p. 4: $B$. → our capacity $c_s$
    deviates but clashes with nothing; carrier $b$ is our own concept and uses the literature's capacity letter
    (kept, deviation to be noted in the correspondence table).
  - Carriers / pallets: Lee et al. (2020) `AUGM8B83`, PDF p. 4: pallet index $l$; Liu et al. (2024) `5YDNRDES`,
    PDF p. 4: fixture set $F$, index $f$. No standard for a carrier.
  - Calendar: Lunardi et al. (2020) `8Z7BQGIF`, PDF p. 5: unavailability periods per machine as intervals
    **[uncertain: formula garbled in the extracted text]**. No literature symbol for breaks or overtime:
    $\mathrm{br}$, $\mathrm{ot}$ own.
  - Rule state ($\phi_m$, $V_m$, $V^{\mathrm{q}}_m$, $\mathrm{wr}_k$, $\underline{S}_o$), policy ($\delta_t$,
    $\operatorname{bl}(o)$), offsets ($\Delta^\pm_{\max}$): no symbols in the papers read (prose or own); own.
  - The DRC review Xu et al. (2011) `K82ZAAIS` has no formal notation; Kasapidis et al. (2025) `VV6ZWRPB` model
    tools and non-renewable resources, not workers.
- **Open:** worker index ($w$ kept vs. $z$ as in Berti et al.); correspondence table in `notation.md` extended by
  workers, batching and objectives; then rename file by file with the Edit tool; commit.
- **Decided (user, afterwards):** worker index $z$ (Berti et al. 2021); the CP-SAT slot machine choice
  $z_{j,m}$ → $g_{j,m}$ (mine). User question "why not $W_k$": Berti's $W_k$ is per machine; ours must be per
  operation (machine-less operations; qualification depends on the step), and one operation has one qualified set
  for all its shares (`WorkerShare.qualified`), so $W_\eta$ → $W_o$ (mine, proposed). User: a base letter told
  apart only by its subscript is hard to read (example $\theta_k$ tightness vs. $\theta_i$ weights; already
  resolved by $\mathrm{DDT}_k$). **Rule stated (mine, matches the papers read):** one base letter means one
  quantity; subscripts only name the index or a subset; accents mark variants of the same quantity (planned,
  realized, expected). Same pattern in Wang et al. (2025) `QJHCEX6V` ($F_s$, $F_k$: one quantity, two resources),
  Berti et al. (2021) `8F7AYGYK` ($W$, $W_k$); counterexample avoided: Berti et al. use $M$ for the machine set and
  the number of machines (PDF p. 5).

## 2026-11-09 (23) — Breaks through rescheduling, task 2: forced overstay; symbol-clash check — uncommitted

- **Decided (user):** Task 2; decision 3 (a) with the principle of entry (20). Mine: the checker computes the forced
  end itself (`forced_end`, independent of the rule): earliest time a qualified worker is free of the frozen part
  (started shares and started breaks) within the shift window C13; the plan's end must equal it (so "forced" and
  "shortest" are one check; without a disturbance it is the expected end).
- **Done:** checker `forced_end`, `_free_from`, `frozen_changed(..., end)`, `_frozen_worker_time(...,
  with_breaks)`; snapshot: expected end $\max(\hat S_o + p,\ t + a^{\mathrm{suf}}_o)$ for a pending suffix (was
  $t + 1$); rule books a pending suffix at the earliest free time and moves the frozen operation's end (batch,
  machine, successors); DES `_apply` takes the plan's worker for a share not started of a running operation.
  `tests/test_forced_overstay.py` (8 tests, by hand; see [04](04_workers.md) §5); the raising test in
  `tests/test_dispatching_workers.py` replaced. [04](04_workers.md) §3 (C7$^o$), §5;
  [05](05_rescheduling-frozen-part.md) §3; [11](11_dispatching-rules.md) §3; [13](13_des.md) §6;
  [notation](notation.md) ($\tilde C_o$, $\operatorname{free}_w$). Worker-free plans still identical (195). Full
  suite 1124 passed, ruff clean.
- **Found:**
  - Before, `update_plan` ignored the plan's worker for a share not started of a running operation, so the
    rule's choice for a pending removal (phase 3 task 4) never reached the factory. Fixed.
  - The snapshot expected a waiting removal at $t + 1$, i.e. starting before $t$ for $a^{\mathrm{suf}}_o > 1$.
    Fixed.
  - A test run of 9:27 h was the computer sleeping overnight, not a hang (rerun 7.6 s).
- **Found (symbol-clash check of [notation](notation.md), user todo; all older than this task):**
  - $b$: carrier index ($\mathcal{B}$, [03](03_carriers.md)) and the maximum late offset ([22](22_scenarios.md)).
  - $\tau$: carrier kind $\tau(b)$ ([03](03_carriers.md)) and the rescheduling period ([05](05_rescheduling-frozen-part.md)).
  - $O$: operations, $\bar O$ max overtime and $O_{w,d}$ overtime ([04](04_workers.md)).
  - $W$: worker set, $W_\eta$ qualified workers and $W_m$ machine load ([11](11_dispatching-rules.md)).
  - $w$: worker index, $w_k$ remaining work ([11](11_dispatching-rules.md)) and $w_i$ weights ([23](23_metrics.md)/objectives).
  - $\rho$: $\rho_s$ ([03](03_carriers.md)) and the ready time $\rho_o$ ([11](11_dispatching-rules.md)).
  - $B$: backlog $B_m$ ([11](11_dispatching-rules.md)) and blockers $B(o)$ ([05](05_rescheduling-frozen-part.md)).
  - $L$: break length $L^{\mathrm{B}}$ and lateness $L_k$ ([06](06_due-dates.md)).
  - $f$: machine free time $f_m$ and the objective $f$ ($\Delta f$, $\delta_f$, $s(f)$).
  - $d$: due date $d_k$ and the day index $d$ ([04](04_workers.md); the day index is not in the table).
  - Milder: $a$ (early offset) vs. $a^{\mathrm{pre/suf}}_o$; the superscript B for the break ($h^{\mathrm{B}\pm}$,
    $L^{\mathrm{B}}$) and the batch slot ($S^B_j$).
- **Open:** renaming the clashes (user decision; the thesis does not use any yet); Task 3; commit.

## 2026-11-08 (22) — Symbol clashes: break start and worker assignment renamed — uncommitted

- **Decided (user):** rename the break symbol; the user's proposal `br`, taken upright as one name
  $\mathrm{br}_{w,d}$ (italic $br$ would read as $b \cdot r$, $r$ is the release; upright multi-letter names are
  house style in [04](04_workers.md): $\operatorname{day}$, $\operatorname{mod}$, $\operatorname{start}$). Realized:
  $\widehat{\mathrm{br}}_{w,d}$. Mine: worker assignment $y_{\eta,w}$ → $v_{\eta,w}$ (fits the worker load $V_w$).
  **Todo (user):** check all symbols for clashes after every task, after every phase, and at the end.
- **Done:** [04](04_workers.md) (12 places), [13](13_des.md), [23](23_metrics.md), [notation](notation.md)
  renamed with the Edit tool, change logs. Thesis: neither symbol used yet.
- **Found:** a second clash, found while searching for a free name: $y_{o,j}$ (CP-SAT batch slot,
  [03](03_carriers.md)) and $y_{\eta,w}$ (worker share). $S^{B}_j$ (batch slot start) ruled out $S^{\mathrm{B}}$ for
  the break.
- **Open:** symbol-clash check as a standing step (in the plan files' task checklists); commit.

## 2026-11-08 (21) — Breaks through rescheduling, task 1: breaks in the snapshot and the checker — uncommitted

- **Decided (user):** decisions 1–3 of `docs/superpowers/plans/2026-11-08-breaks-rescheduling.md` all (a): planners
  return breaks with the assignments; forced postponement; forced overstay. Start Task 1. Mine: the snapshot's
  breaks are realized history and not checked against the window (like C2 for frozen operations); the forced
  condition uses the frozen share intervals as a planner sees them (snapshot times, planned share lengths).
- **Done:** `Snapshot.breaks`, `snapshot(..., breaks)`, `Simulation.snapshot()` passes its breaks; checker
  `breaks_changed` (C6$^b$, C7$^b$), `break_violations(..., snapshot)` (history, C14$^f$), `_frozen_worker_time`.
  `tests/test_snapshot_breaks.py`, 11 tests by hand (see [04](04_workers.md) §5). Symbols $y_{\eta,w}$, $I_\eta$,
  $b_{w,d}$ (pending since phase 1) and $\hat b_{w,d}$ added to [notation](notation.md); [04](04_workers.md) §3,
  §5, §6; [05](05_rescheduling-frozen-part.md) §3; [13](13_des.md) §6. Full suite 1117 passed (also under load,
  4.3 min: the patched CP-SAT tests held), ruff clean.
- **Found:** my first hand plan put B's packaging at 12:31 inside B's break [12:00, 13:00); the checker caught it
  (test corrected to 13:00). A running prefix appears in the snapshot only with its planned length, so a break
  forced by an overrunning prefix would be rejected (C14$^f$); whole shares work. Recorded as an open point in
  [04](04_workers.md) §6. $b_{w,d}$ shares its letter with the maximum late offset $b$ of [22](22_scenarios.md);
  distinguished by the subscript, noted in the notation table.
- **Open:** Task 2 (forced overstay); the prefix limitation; whether to rename $b$ in [22](22_scenarios.md); commit.

## 2026-11-08 (20) — Test for a pending removal without a free worker; plan: breaks through rescheduling — uncommitted

- **Decided (user):** plan the breaks task; write a test for the pending-removal case. Answered: the "195 plans"
  are 13 worker-free instances (Mk01–Mk10, `toy-3x3`, `toy-dag-3x4`, `toy-carriers`) × 15 rule combinations,
  compared with a scratch script (not a repo test).
- **Done:** `tests/test_dispatching_workers.py::test_pending_removal_without_a_free_worker_raises` (one worker,
  polishing at factor 2, snapshot at 8: polishing expected until 9, oven removal [8, 9) pending, `dispatch`
  raises; passes). Plan `docs/superpowers/plans/2026-11-08-breaks-rescheduling.md` (3 decisions for the user,
  4 tasks).
- **Found:** the pending-removal case is reachable in an ordinary DES run, not only constructed: one overrunning
  share of the only qualified worker would crash a rescheduling run. Taken into the plan (decision 3, Task 2;
  recommendation: planned overstay, C7 relaxed for a running operation with a pending suffix). Thesis: no affected
  section written yet (`seipl27/Text/kapitel1.tex` empty).
- **Open:** the user's decisions 1–3 of the plan; commit.
- **Decided (user, afterwards):** a planner must never cause a postponed break past the window or an oven
  overstay; forced by the frozen part (disturbance), the shortest delay is accepted. Decisions 2 and 3 settled
  accordingly (forced postponement, forced overstay, both checked as forced and shortest); decision 1 (breaks in
  the planner interface) still open. Answered: a break pending after 13:00 arises only from disturbances (overrun
  or late start of the worker's share), since the rule keeps shares out of 12:00–13:00 and the DES takes a due break
  as soon as the worker is free.
- **Found (user question on instances):** every feature got its own mini instance and tests (`toy-dag-3x4`,
  `toy-carriers`, `toy-workers`, dict instances in the tests); older JSON instances changed only their
  `schema_version` at each increment (new fields optional with "off" defaults), Brandimarte stays `.fjs`. No
  instance combines all features yet; the dental example of the generator (phase 5) will be the first.

## 2026-11-08 (19) — Flaky CP-SAT replay test; workers, phase 3 task 4: rule plans from a snapshot — uncommitted

- **Decided (user):** patch the second flaky Mk10 test, then Task 4. User question: does the day-0 break shortcut
  of `default_breaks` matter for rescheduling? Answer (mine): the shortcut does not (times count from the
  instance's $t = 0$, snapshots have $t \ge 0$), but breaks do not travel through rescheduling at all (see
  Found). Mine: Task 4 without calendar; `dispatch` from a snapshot with workers **and** calendar raises
  `NotImplementedError`; breaks through rescheduling become their own task.
- **Done:** `tests/test_des.py::test_replay_of_cpsat_plan_equals_plan_and_keeps_its_makespan` with
  `deterministic_time=0.05` (12 passed, 27.6 s). `planners/dispatching.py`: worker helpers before the frozen part;
  started shares of frozen operations booked with their workers (a batch once); pending shares (removal of a
  running oven) get a worker by `pick` (least $V_w$, then index), the same list for all batch members; frozen
  machine-less operations; parts of a partly started run wait for their workers. 12 new tests in
  `tests/test_dispatching_workers.py` (by hand: pending oven removal and the continued run at $t = 9$; frozen
  Gegenbetten at factor 2 keeps A; 10 snapshots × 5 disturbed seeds × 15 rules × 2 instances pass the checker
  against the snapshot; calendar guard). Worker-free plans still identical (195). Full suite 1106 passed, ruff
  clean. [11](11_dispatching-rules.md)
  §3, §5; [04](04_workers.md) §5; plan file Task 4.
- **Found:** breaks do not travel through rescheduling: `Snapshot` has no breaks, the planner interface returns
  only assignments, `control.rescheduling.execute` starts the `Simulation` without breaks, so on a calendar
  instance `Simulation(...)` and `update_plan` would report C14 (missing breaks). After a snapshot the rule's fixed
  12:00 break would also ignore a break the DES postponed (e.g. to 12:20), so a share at 13:00 could overlap it.
  `execute` with workers is blocked anyway, since repair still rejects workers (phase 4).
- **Open:** breaks through rescheduling (snapshot breaks, rule breaks after a snapshot, planner interface,
  `execute`); a pending removal with no free qualified worker raises `ValueError` (not observed, no test);
  commit.

## 2026-11-07 (18) — Workers, phase 3 task 3: calendar in the dispatching rule — uncommitted

- **Decided (user):** keep the gap booking of Task 2, start Task 3. Mine: the worker gap search and
  `calendar.next_start` (latest $= h^{\mathrm{E}}$, no overtime, break fixed at 12:00) are applied alternately
  until both hold; `default_breaks(ci, plan)` returns one break at $h^{\mathrm{B}-}$ per worker and working day with
  one of its shares, `dispatch` keeps its return type (how breaks travel through the planner interface stays a
  phase 4 question); an operation whose shares never fit the shifts together raises `ValueError` (no fit within
  two weeks after the last booking; without this guard the fixpoint would not terminate, e.g. a 14-hour oven
  program).
- **Done:** `planners/dispatching.py` (`free_from` with the calendar, termination guard in `worker_start`,
  `default_breaks`); 27 new tests in `tests/test_dispatching_workers.py` (by hand: share pushed past 12:00 and 1 day
  late, Friday 17:00 → Monday 08:00 on time, a 300-minute share raises, a 14-hour oven raises, a 600-minute mill run
  with removal at 08:00 the next morning and the machine blocked; all 15 rule combinations on `toy-workers` with
  calendar and on the night carrier instance pass the checker with `default_breaks` and replay unchanged incl.
  breaks; no breaks without a calendar). Worker-free plans still identical to before (195). Full suite 1093
  passed, 1 failed (`tests/test_des.py::test_replay_of_cpsat_plan_equals_plan_and_keeps_its_makespan[BrandimarteMk10]`,
  no CP-SAT solution within the 1 s wall-clock limit while the suite ran 4.6 min under load; alone 12 passed in
  15.6 s; unrelated to the rule); ruff clean.
  [11](11_dispatching-rules.md) §3, §5; [04](04_workers.md) §5.
- **Found:** with these hand cases the rule needed no special code for night runs: the attended removal's whole
  share is simply not free before 08:00.
- **Open:** Task 4 (rule plans from a snapshot with workers); a day-0 break before $t = 0$ (origin after the break
  window) is left out by `default_breaks` (shortcut, C14 reports it); the Mk10 CP-SAT replay test has the same
  wall-clock flakiness as the test patched in (15), same fix possible (`deterministic_time`); commit.

## 2026-11-06 (17) — Workers, phase 3 task 2: shares and machine-less operations in the dispatching rule — uncommitted

- **Decided (user):** start Task 2. Mine: **workers are booked into gaps of their busy intervals, not
  append-only** (deviation from item 3 of the approved phase 3 plan, plan file edited): a suffix share (oven
  removal) is booked when the oven run is planned, so append-only would block its worker for the whole oven
  program. Machines stay append-only. Candidate start includes the workers (fixpoint over the shares); per share
  least worker load $V_w$ (new symbol, [notation](notation.md)), then lowest index; batch shares booked once; run
  parts placed one after the other, each when its workers are free (machine blocked meanwhile, C9); `dispatch` from
  a snapshot with workers raises until Task 4.
- **Done:** `planners/dispatching.py` (guard removed, `free_from`, `worker_start`, `take_workers`, `_spans`;
  machine `None` kept as `None`, never as a negative index); `tests/test_dispatching_workers.py` (hand plans on
  `toy-workers` without calendar and on the carrier instance, batch with a second printer, all 15 rule
  combinations × 2 instances pass the checker and the zero-disturbance replay, snapshot guard); guard test in
  `tests/test_worker_compile.py` reduced to CP-SAT and repair. Full suite 1058 passed, ruff clean. [11](11_dispatching-rules.md) §3, §5, §6;
  [04](04_workers.md) §5.
- **Found:** a first version moved the `f_m` update after the placement; ECT reads $f_m$ in `make_ready` of the
  successors, and 53 of 195 worker-free plans changed. Restored the old order (update before placement, a run's
  end afterwards); then all 195 worker-free plans (Mk01–Mk10, three toys, 15 combinations) are identical to the
  previous version.
- **Open:** Task 3 (calendar in the rule, `default_breaks`); no hand test yet for a run removal that waits for a
  worker (covered only by the checker/replay sweep); commit.

## 2026-11-06 (16) — Workers, phase 3 task 1: calendar availability helper — uncommitted

- **Decided (user):** phase 3 plan approved, start Task 1; `math/` and `CLAUDE.md` are tracked in Git (user
  commit `6463434`; phase 1 in `e5348b0`). Mine: `CLAUDE.md` sentence "math/ is not in the Git repository"
  corrected accordingly; `next_start` places the break at its earliest start (the rule's fixed 12:00 break) and
  raises for a share longer than both shift parts.
- **Done:** `calendar.next_start`; 11 tests in `tests/test_calendar.py` (by hand); full suite 1026 passed (incl.
  the patched Mk10 test under full load), ruff clean. [04](04_workers.md) §5.
- **Found:** phase 2 and the later passes (2026-11-05 (9) to (15)) are not committed yet.
- **Open:** Task 2 (shares and machine-less operations in the rule); commit hashes for the change logs from now on.

## 2026-11-06 (15) — Deterministic CP-SAT limit in a test; phase 3 plan — uncommitted

- **Decided (user):** patch the flaky Mk10 test; 19:30 is a hard limit; plan phase 3. Mine: `solve(...,
  deterministic_time=None)` as an optional work-based limit (OR-Tools `max_deterministic_time`, checked in the
  OR-Tools docs via Context7: counted from operation counters, independent of machine speed and load); the test
  uses `deterministic_time=0.05` (1 took 138 s for the 12 instances, 0.05 takes 18.5 s).
- **Done:** `planners/cpsat.py` parameter; `tests/test_rescheduling.py::test_zero_disturbance_with_repair_for_cpsat_plans`
  with the deterministic limit and an assertion that a plan was found (12 passed); plan
  `docs/superpowers/plans/2026-11-06-workers-phase3-dispatching.md` (4 tasks).
- **Found:** the user's question about "LaTeX": the formulas in `math/*.md` are LaTeX inside Markdown (`$...$`,
  as `CLAUDE.md` asks); the tab came from applying edits to `math/04_workers.md` with an ad-hoc Python script, where
  `\t` in `\text` is an escape. From now on `math/` files are edited with the Edit tool only.
- **Decided (user, afterwards):** 19:30 stays hard in the plan (C13); in execution a share that runs past 19:30 is
  finished and counted as an overrun (metric `overruns`), not interrupted: an interrupted operation cannot be
  handled by the planners and is out of scope. No code change (current DES behavior).
- **Open:** the CP-SAT reproducibility todo of 2026-11-04 (4) can now use `deterministic_time`;
  phase 3 plan approval; commit.

## 2026-11-06 (14) — Workers, phase 2 task 4: snapshot with workers, metrics — uncommitted (phase 2 complete)

- **Decided (user):** start Task 4. Mine: `FrozenOperation.workers` with `None` for a share not started yet (the
  pending removal of a running oven may still change); C7 compares only the workers of started shares; worker
  metrics as own definitions from the realized share intervals (reusing the checker's `worker_intervals`) and the
  realized breaks; `ExecutionResult.breaks`.
- **Done:** `sim/snapshot.py` (machine optional, expected end with fixed durations, workers of started shares,
  batch members via their first operation); `check.feasibility.frozen_changed` with workers, `worker_intervals`
  public; `control.rescheduling.ExecutionResult.breaks`; `metrics._worker_metrics` (`overstay`, `swaps`,
  `overtime`, `overruns`, `break_postponement`, `break_spread`); `tests/test_worker_snapshot_metrics.py` (8 tests,
  hand values); [13](13_des.md) §6, [23](23_metrics.md) M7, [04](04_workers.md) §5.
- **Found:** full suite 1014 passed, 1 failed:
  `test_rescheduling.py::test_zero_disturbance_with_repair_for_cpsat_plans[BrandimarteMk10]`. CP-SAT with
  `time_limit=1` found no solution under the load of the full run, so the plan was empty and the DES rejected
  it; the test passes alone (12/12). Not caused by this change; same root cause as the reproducibility todo of
  2026-11-04 (4) (wall-clock time limit). A `\t` in LaTeX written via a script became a tab in 04 (fixed).
- **Open:** that test's time limit (todo, with the CP-SAT reproducibility item); phase 2 is complete (DES with
  workers, calendar, swap rule, snapshot, metrics); next phase 3 (dispatching rule with workers and calendar);
  commit.

## 2026-11-06 (13) — [thesis] Bibliography: biblatex + biber — uncommitted

- **Decided (user):** switch from BibTeX `ieeetr` to biblatex + biber with `style=ieee`, because `ieeetr.bst` prints
  neither URL nor DOI.
- **Done:** `seipl27/main.tex`: `csquotes`, `biblatex` (`backend=biber,style=ieee`), `\addbibresource{Bib/stud77.bib}`,
  `\printbibliography[heading=bibintoc]`; `seipl27/CLAUDE.md` citation style and export format (Better BibLaTeX)
  updated. Clean build (stale `main.bbl` from BibTeX removed); scratch test with two entries from
  [references.md](references.md) prints DOIs and handles accents.
- **Done (later the same day):** user added the Better BibLaTeX export (73 entries); `.latexmkrc` comment updated to
  biber, `\usepackage[T1]{fontenc}` added (user); `check-build` script fixed: its pattern missed biber warnings,
  which carry a `[ms] Module.pm:line>` prefix, so every biber warning had been reported as a clean build.
- **Found:** with `\nocite{*}` all 73 entries build; biber warns about 5 book entries with two ISBNs in one field
  (print + e-book). 7 entries have no year in the key (no author or no date in Zotero). Two overfull lines in
  the bibliography (long URLs).
- **Open:** fix the 5 ISBN fields and the incomplete entries in Zotero.

## 2026-11-06 — Workers, phase 2 task 3: swap rule; 03 renamed to carriers — uncommitted

- **Decided (user):** start Task 3; rename `math/03_loads.md` to carriers and cover blanks in its intro. Mine: the
  swap rule also applies to the oven removal (it can prevent an overstay); a swap is only tried when the planned
  worker is busy (on a share or a break), not when it merely waits for an earlier share of its own.
- **Done:** `math/03_carriers.md` (renamed; title, status and carrier definition with plates and blanks; outdated
  oven sentence fixed; change log); links in `math/`, `CLAUDE.md`, code comments, tests, notebook 05 and the
  unpublished schema 0.6 updated (published schemas 0.4/0.5 left as they are). DES: `_swap`,
  `_planned_share_start`, `_fits_shift` (shared with `_in_shift`), SWAP log record, all batch members get the new
  worker; `tests/test_des_swap.py` (7 tests); the two-worker overstay example now swaps, so the overstay test uses
  one worker (overstay 3 by hand); full suite 1007 passed, ruff clean. [13](13_des.md) §3, [04](04_workers.md) §5.
- **Found:** with two workers the earlier overstay example is resolved by the swap rule (W2 unloads at 8 and also
  takes L1's mill setup at 9): the rule reduces overstay as intended. No reference to `03_loads.md` in `seipl27`.
- **Open:** Task 4 (snapshot with workers, metrics); commit.

## 2026-11-05 (12) — [thesis] Outline: separate model chapter — uncommitted

- **Decided (user):** P1, the former chapter 4 "Methodology" is split into 4 "Problem Analysis and Formal Model"
  (process chain and SRS requirements, formal model, Fidentis application example) and 5 "Solution Approach and
  Implementation" (rescheduling policy, NSGA-II, selection rule, implementation); nine chapters.
- **Done:** outline renumbered (cross-references, review items), `seipl27/CLAUDE.md` thesis structure updated;
  the outline file is now `Thesis Outline - Critique and Proposal.md` (renamed and committed by the user).
- **Found (user):** the finding in (11) was wrong. "The planner does not form batches" meant the creation of
  carriers (formerly called batches), which nesting does; it still holds. Oven p-batches are a separate, narrow
  case. Outline point 5 rewritten accordingly.
- **Open:** P2 (merge chapter 3 into 1.2), P3 (research method, e.g. DSR); objective set now needed before
  section 4.2 is final; Better BibTeX auto-export to `seipl27/Bib/stud77.bib`.


## 2026-11-05 (11) — [thesis] Outline update — uncommitted

- **Decided (user):** update the outline file with the review fixes; the in-depth structure stays a living document,
  only some points are settled now.
- **Done:** `seipl27/Thesis Outline — Critique and Proposal.md` restructured: status tags (decided / applied /
  proposed / open); section-level fixes applied (SRS before model, "what is validated" first in chapter 5, simulator
  design in 4.4 and configuration in 5.3, GA choice justified in 4.3, problem features in 1.1); stale references
  fixed (policy in 4.3, no Foundations chapter); terminology (carriers, loads, runs, workers); references split into
  those used in `math/` and those cited from memory.
- **Found:** [corrected in (12)] the outline's point "the planner does not form batches" is outdated: oven runs are a planner decision
  since 2026-11-03 ([03](03_carriers.md)), so batch-formation literature is relevant for the oven step.
  `seipl27/Bib/stud77.bib` holds only the 4 template entries; the Better BibTeX export does not reach it yet.
- **Open:** P1 separate model chapter, P2 merge chapter 3 into 1.2, P3 rename "Methodology" / add DSR; Pareto front
  vs. scalarized GA; objective set of the GA; GA not started; clearance of the Fidentis application example.

## 2026-11-05 (10) — Workers, phase 2 task 2: calendar in the DES — uncommitted

- **Decided (user):** start Task 2. Mine: the DES invents no break for days without a planned one (the planning
  tool plans breaks); overtime and overruns are read off the realized schedule (no extra log records);
  `Assignment.share_lengths` for realized share lengths.
- **Done:** `sim/des.py`: shift window with WAKE wake-ups (`_in_shift`), breaks taken or postponed
  (`_take_breaks`, `_free_now`), `realized_breaks()`, `SimResult.breaks` realized; `Assignment.share_lengths`, used
  by the checker's worker intervals, wrong count reported as C11; `tests/test_des_calendar.py` (17 tests),
  2 new checker tests; full suite 1000 passed, ruff clean. [13](13_des.md) §3, [04](04_workers.md) §5.
- **Found:** (1) my first hand values were 20 minutes off (k1's packaging is ready at 150, not 170), corrected in
  the test, not in the code; (2) a disturbed seed showed that the checker used *planned* share lengths for a
  realized schedule and reported a break overlap that did not happen (A's prefix was shorter) → realized share
  lengths now travel with the realized schedule. Without that, the "one checker for every plan, incl. realized
  schedules" rule (`CLAUDE.md`) would not hold for workers.
- **Open:** Task 3 (swap rule), Task 4 (snapshot, metrics); commit.

## 2026-11-05 (9) — Workers, phase 2 task 1: shares in the DES — uncommitted

- **Decided (user):** plan approved with both defaults (rule 2: attended shares scale with the operation's factor;
  rule 4: no share started that is expected to run past 19:30). Mine: share events carry `op * 4 + share`
  (an operation has at most 3 shares) to keep the event tuple; the first operation of a batch carries its shares,
  also after the start (`followers`).
- **Done:** `sim/des.py`: events SHARE_END and SUFFIX_DUE (priorities after COMPLETE), worker state (planned order,
  next, busy), start condition with workers, soft suffix with OVERSTAY log record, machine-less operations
  (`NO_MACHINE`), realized durations (rule 2), `breaks` parameter and `SimResult.breaks`; DES guard removed (test
  case dropped in `test_worker_compile.py`); `tests/test_des_workers.py` (12 tests); full suite 981 passed, ruff
  clean. [13](13_des.md) §3, [22](22_scenarios.md) §3, [04](04_workers.md) §5.
- **Found:** the hand-computed overstay example (polishing 6 instead of 4 → removal 2 minutes late, mill runs
  shifted to 11–17 and 17–23) matched on the first run.
- **Open:** Task 2 (calendar in the DES); `Simulation.snapshot` still assumes a machine per operation (Task 4,
  only reached through the guarded planning tool); commit.

## 2026-11-05 (8) — Workers, phase 2: DES plan — no code change

- **Decided (user):** start phase 2 (DES).
- **Done:** plan `docs/superpowers/plans/2026-11-05-workers-phase2-des.md` (4 tasks: shares and machine-less
  operations; calendar; swap rule; snapshot and metrics) after reading `sim/des.py`, `sim/snapshot.py`,
  `sim/scenario.py`.
- **Open (to the user):** rule 4 (refuse a share expected to run past 19:30, default) and rule 2 (attended shares
  scale with the operation's factor, default); plan approval.

## 2026-11-05 (7) — Workers, step 2d: checker C11–C14 — uncommitted (phase 1 complete)

- **Decided (user):** start Task 6. Mine: constraint labels C11 (assignment, qualification, machine-less
  operations without machine, same workers in a batch), C12 (overlap per worker), C13 (shift window), C14
  (breaks); a break is required only on days on which the worker has a share; overtime and the common break stay
  costs, not constraints; C13/C14 only with a calendar.
- **Done:** `check_schedule(..., breaks=())`, `worker_shares_wrong`, `worker_overlaps`, `outside_shift`,
  `break_violations`, `_worker_intervals` (a batch counts once); mini instance `data/instances/toy-workers.json`
  with a hand plan; `tests/test_workers_checker.py` (20 tests: feasible hand plan, one violation per single
  change for C1, C2, C11, C12, C13, C14, break rules, touching break, worker free during rest, oven batch, no
  calendar); full suite 971 passed, ruff clean. [04](04_workers.md) §3 (C1', C11–C14 in LaTeX), §5;
  [01](01_basic-fjsp.md) C1 note; README.
- **Found (by the tests):** machine-less operations were swept as machine `None` and reported as C5; an unknown
  worker also produced a "no break" C14. Both fixed at the source (sweep skips machine-less operations; unknown
  workers are only reported under C11).
- **Open:** phase 1 done (calendar, day tardiness, format, compilation, schedule format, checker); next: plan for
  phase 2 (DES with shifts, breaks, overtime, swap rule, oven overstay); commit.

## 2026-11-05 (6) — Workers, step 2c: schedule format — uncommitted

- **Decided (user):** start Task 5. Mine: `Assignment.machine` stays required but may be `None` (explicit for
  machine-less operations, no silent omission); breaks belong to the schedule because the planner decides them.
- **Done:** `Assignment.machine: str | None`, `Assignment.workers`, `Break`, `Schedule.breaks`
  (`model/schedule.py`); `tests/test_worker_schedule.py` (5 tests: machine-less assignment, machine still
  required, JSON roundtrip with breaks, negative break start, an old CP-SAT plan without workers still feasible);
  full suite 951 passed, ruff clean. [04](04_workers.md) §5, change log.
- **Found:** no stored JSON schema for `Schedule` (only for `Instance`), so no schema file to bump.
- **Open:** Task 6 (checker C11–C14 with the mini instance `toy-workers.json`); commit.

## 2026-11-05 (5) — Workers, step 2b: compilation and guards — uncommitted

- **Decided (user):** start Task 4; if the operation model (machine and/or worker, prefix, suffix, unattended)
  proves too complex for CP-SAT or the GA, downgrade to (a) prefix and unattended only, or (b) fully attended
  operations (machine + worker, worker only, machine only) — recorded in [04](04_workers.md) §6, to be decided by
  solve times after phase 4. Mine: shares attached in `operation_graph` (it already knows run roles), compiled
  shares independent of the duration; guards at the four public entry points instead of deep inside.
- **Done:** `Node.shares`, `Node.duration`; `compiled.Share`, `share_interval`, `reject_workers`;
  `CompiledInstance.worker_ids`, `fixed_duration`, `shares`; `static_horizon` with fixed durations; guards in
  `Simulation`, `dispatch`, `solve`, `repair`; `tests/test_worker_compile.py` (13 tests); full suite 946 passed;
  ruff clean (3 findings in my new lines of Tasks 1 and 3 fixed). [04](04_workers.md) §5, §6, change log.
- **Found:** an empty file `c]$` appeared in the project root (11:39, not created by this pass's commands as far
  as I can tell); left untouched.
- **Open:** Task 5 (schedule format with workers and breaks), Task 6 (checker); commit.

## 2026-11-05 (4) — Workers, step 2a: worker shares in the format — uncommitted

- **Decided (user):** start Task 3. Mine: shares of carrier operations only on the carrier step (one place per
  step), machine-less carrier operations not supported; share length checked against the shortest machine option
  (shortcut, run estimates left to the checker); an extra rule "attended setup/removal needs workers".
- **Done:** `WorkerShare`, `Instance.workers`, `Operation.duration`, `Operation.worker`, `CarrierStep.worker`,
  `setup_attended`, `removal_attended` with validation; `operation_graph` and `lead_time_bound` handle
  machine-less operations; schema 0.6 regenerated in place (unpublished); `tests/test_worker_format.py`
  (22 tests: 15 negative instance rules, 4 invalid shares, positives); the carrier test's message updated to
  "options or duration missing"; full suite 932 passed before the last negative test, affected files 100 passed
  after it. [04](04_workers.md) §2 (kinds table), §5; [notation](notation.md) $O^{\emptyset}$, $W$,
  $\mathcal{A}_o$, $\eta$, $W_\eta$, $p_o$, $a^{\mathrm{pre}}_o$, $a^{\mathrm{suf}}_o$.
- **Found:** the plan's symbols $r_o$ (suffix) and $\sigma$ (share) clash with releases $r_k$ and the scenario
  $\sigma$; renamed. Compiling a worker instance now yields machine-less operations with no options; consumers
  (DES, rules, CP-SAT, repair) do not handle them yet: guards come in Task 4.
- **Open:** Task 4 (compilation and guards); commit.

## 2026-11-05 (3) — Workers, step 1b: tardiness in missed shipping days — uncommitted

- **Decided (user):** start Task 2. Mine: one objective `TOTAL_TARDINESS` whose unit follows the instance (days
  with a calendar, minutes without), so all planners and `lexicographic` work unchanged; spread with a calendar
  $|\mathcal{K}^d| (\lfloor H/1440 \rfloor + 1)$; minute tardiness kept as a metric.
- **Done:** `calendar.WeekCalendar`, `CompiledInstance.calendar`; `objectives` (evaluation with `days_late`,
  CP-SAT with one reified Boolean per order and cutoff, spread); `assign_due_dates` rounds up to the next cutoff;
  `run_metrics` column `tardy_days`; `tests/test_day_tardiness.py` (13 tests); full suite 910 passed.
  [06](06_due-dates.md) (O1'), spread, CP-SAT mapping, implementation, change log; [04](04_workers.md) §4, §5.
- **Found:** `TARDY_ORDERS` needs no change ($T_k > 0 \iff C_k > d_k$ in both units). The 5 tests that passed
  before the implementation are the ones where days and minutes coincide or the old behavior is checked.
- **Open:** Task 3 (worker shares and machine-less operations in the format); commit.

## 2026-11-05 (2) — Workers, step 1a: work calendar — uncommitted

- **Decided (user):** work on `main`, no subagents; plan `docs/superpowers/plans/2026-11-05-workers-phase1-...`
  executed one task at a time with approval in between. Mine: `t = 0` Monday 08:00 as `Calendar.origin` (minute
  of the week), calendar functions duck-typed so the compiled form can reuse them.
- **Done:** `Calendar` model and `Instance.calendar` (schema 0.6, all data, generators, loaders and tests bumped,
  `schemas/instance-0.6.json`); validation (time order shift/break, break inside the shift, overtime before
  midnight, cutoff and origin ranges, working days, `time_unit == "min"`, due dates on cutoffs);
  `simulation.calendar` (`minute_of_day`, `day_index`, `day_start`, `is_working_day`, `cutoffs`, `next_cutoff`,
  `days_late`); `tests/test_calendar.py` (21 tests, hand values, one negative test per rule); full suite 897
  passed. `math/`: [04](04_workers.md) created, [notation](notation.md) section Calendar, README,
  [references](references.md) (Kasapidis et al. 2023), [06](06_due-dates.md) change log.
- **Found:** Lunardi et al. 2020 and Kasapidis et al. 2023 metadata checked in Zotero (`8Z7BQGIF`, `E58NU6WE`).
- **Open:** Task 2 of the plan (tardiness in days in objectives, CP-SAT, due-date rounding, metrics); commit.

## 2026-11-05 — Workers and shifts: design spec — no code change

- **Decided (user):** QM per plate stays (whole plate at once); terminology "order-internal precedence", no "JPC";
  individual workers with qualification sets; partial occupation as attended prefix/suffix of an operation, rest as
  unattended share without resource (revises 2026-11-04 (2) block 2, no time lag on edges); rest and oven program
  fixed under disturbances; oven removal hard in the plan, soft in execution (pausing a running task not modeled);
  swap rule in the DES (free qualified worker takes a waiting task if it fits before their next task), complete
  rescheduling may reassign, repair keeps assignments; shifts 08:00–17:30, break 60 min in [12:00, 13:00] with
  penalties for postponement and spread, overtime up to 2 h penalized; due date = shipping date, deadline 12:00,
  tardiness in missed shipping days (weekends not counted); objective tardiness + $w_O$ · overtime on one level
  ($w_O$ varied in experiments), then break, then makespan on an activity clock; placeholders for durations.
  Mine (in the spec, marked): $t = 0$ Monday 08:00, rule and repair behavior, CP-SAT mapping, metrics, order of
  implementation, builder-check calls (runs keep setup/removal operations; oven shares per run inside the fixed
  program; planned order per worker; oven overstay as level 0; legacy bench kept; due dates rounded up to cutoffs).
- **Done:** spec `docs/superpowers/specs/2026-11-05-workers-shifts-design.md`; builder check by a subagent (7
  questions, 6 settled); sources checked in Zotero: Kasapidis et al. 2023 (`E58NU6WE`, p. 2, multiple necessary
  resources, full occupation), Lunardi et al. 2020 (`8Z7BQGIF`, p. 2, unavailability from shift patterns), Wang et
  al. 2025 (`QJHCEX6V`, abstract only).
- **Found:** partial occupation (prefix/suffix) is not covered by the FMRJ sources read (all resources for the whole
  duration) → own modeling; the dental route has no shipping step (`finish` is last).
- **Decided (user, after the check):** packaging and shipping as a new worker-only last operation per order,
  finished by the courier cutoff, possibly an s-batch across orders (mine: per order first, s-batch later with
  polishing across orders); unattended print and mill runs vary; a calendar Gantt for the notebooks (design in the
  spec §8a, mine).
- **Open:** **[check with Fidentis]** oven overstay as level 0 and the oven blocked while parts wait; spec not yet
  approved; `math/04_workers.md` written during implementation.

## 2026-11-04 (4) — Sprint review; notebooks re-executed — no code change

- **Decided (user):** notebook reproducibility is not fixed now (not written about yet), kept as a todo; workers next.
- **Done:** sprint plan compared with commits, protocol and code; all five notebooks re-executed from scratch into
  copies outside the repo (repo notebooks unchanged) and outputs compared cell by cell. This ran before or while
  pass (3) edited `04_rescheduling`; the comparison does not cover its new cells.
- **Found:**
  - all notebooks run without errors (01: 39 s, 02: 134 s, 03: 65 s, 04: 171 s, 05: 402 s);
  - `04_rescheduling` mk01 table reproduces exactly (except planner time): CP-SAT ends before its time limit there;
  - CP-SAT results that stop at the time limit are not reproducible, also with `workers=1`: `05_carriers` CP-SAT
    rescheduling 1248.2 → 1255.8, `04` due-date cell small differences; `02`/`03` differ as documented (8 workers) —
    [12](12_cp-sat.md) §5; the time limit is wall-clock, so the stopping point depends on machine load;
  - stale output: `04` cell 4 showed a REPLAN record without `triggers` (added 2026-10-30), a result of rerunning
    only changed cells;
  - M2.3 exists only for mk01 with 10 seeds (not 30); no "always" policy; the periodic policy is in no notebook;
  - "JPC" is not defined in `math/` and not found in the Zotero library (only Li et al. 2017, `R9F79A5C`, where JPC
    means job production cost); the feature itself is the DAG per order, "non-linear routes", $\beta = bom$
    (Dauzère-Pérès et al. 2024, `ZSNHKWD6`, p. 13), already in [01](01_basic-fjsp.md). "Precedence constraints between
    jobs" means something else in the literature (`ZSNHKWD6`, p. 9) and contradicts the rule that predecessors stay
    within an order;
  - protocol entries 2026-11-02 (2) to 2026-11-03 (10) say "uncommitted" but are in commit `cd7ca2b`.
- **Open (todo):** reproducible CP-SAT under a time limit (candidate: a deterministic time limit instead of
  wall-clock time **[uncertain: OR-Tools parameter not checked]**); full re-run of all notebooks before any result is
  used in the thesis; M2.3 with 30 seeds and more instances; rename or drop "JPC" (`CLAUDE.md`, planned file `02`).

## 2026-11-04 (3) — Mean start-shift trigger; tardiness-trigger examples — uncommitted

- **Decided (user):** mean start deviation as the aggregate for the start-shift trigger (the sum was rejected: with
  the end of the plan only pushed by 3 minutes it adds nothing over the end metrics, and it would need a threshold
  that depends on the number of remaining operations); the max stays for an ablation. Tardiness trigger needs no
  new code (exists as $\Delta f$); examples go into the notebook. Mine: both start-shift thresholds optional and
  independent, no validation added.
- **Done:** `ReschedulingPolicy.max_mean_shift`, `mean_shift` / `mean_shift_deviation` in the REPAIR record,
  trigger name `mean_shift` ([rescheduling.py](../src/simulation/control/rescheduling.py)); hand-computed test
  `test_mean_shift_trigger_next_to_the_max_shift_trigger` (toy, $\Delta S_{\mathrm{mean}}$ 4/6 and 8/6, max 1 and 2);
  [05](05_rescheduling-frozen-part.md) §3, §5, §6, change log, [notation](notation.md); notebook `04_rescheduling`:
  tardiness trigger on the toy plan and on mk01 with due dates. Full test suite: 876 passed.
- **Found:** sources for deviation triggers and start-time deviation as stability measure: Vieira et al. 2003
  (`H76SDH6L`, trigger when the difference exceeds a limit), Wu et al. 1993 (`TLCUQTJ9`, start-time deviation as an
  objective), Shiau et al. 2026 (`F5VQRD7Z`); none uses max or mean against an anchor as a trigger, so that part
  stays own design. mk01 with due dates (10 seeds, one run): $\delta_f = 0$ lowers $\sum T$ (tight 71.8 → 58.6, mixed
  31.8 → 25.6) at 27–33 instead of about 6 reschedulings; $\delta_f = 10$ is like the makespan trigger.
- **Open:** direction of the triggers (user: a change of tardiness from 1 to 0 should not trigger; candidate
  one-sided $\Delta f$, [05](05_rescheduling-frozen-part.md) §6); ablation max vs. mean vs. both on mk01 (not run);
  thesis section on the trigger, if already written, needs the mean ($\Delta S_{\mathrm{mean}}$).

## 2026-11-03 (11) — [thesis] Thesis repo and Claude setup — seipl27 `53dbda9`

- **Decided (user):** thesis in English, folder `seipl27`, main file `main.tex`, bibliography via Better BibTeX
  auto-export of collection MA into `Bib/stud77.bib`, own private Git repo, Claude drafts from `math/` and reviews.
  Mine: no further skills beyond the user's four; `writing-anti-ai` trimmed to an English academic style lint.
- **Done:** `seipl27/CLAUDE.md` (from the user's draft) with terminology aligned to this `CLAUDE.md` and
  [03](03_carriers.md), links to `math/`, protocol, result origins (`% src:`), figures, bib; skills `check-build`
  (BibTeX warnings parsed, `.latexmkrc` with `$pdf_mode = 1`), `draft-section` (reads `math/`, `% DRAFT(claude)`,
  `ai-log.md`, style self-check), `thesis-review`, `writing-anti-ai`; preamble English with `amsmath`, `booktabs`,
  `acronym`, `cleveref`, `notation.tex` stub; `git init` with LaTeX `.gitignore`, private remote
  `PaulSeipl/seipl27`. Thesis section in this `CLAUDE.md`.
- **Found:** the user's draft defined Load as the persistent carrier, contradicting [03](03_carriers.md); fixed in the
  thesis `CLAUDE.md`. Build clean (`check_build.py main.tex`, exit 0).
- **Also:** terminology moved into [terminology.md](terminology.md), imported by both `CLAUDE.md` files (`@`-import);
  merged version (carrier includes blanks, parts added).
- **Open:** Better BibTeX install and export (user); macros in `notation.tex`
  when chapter 4 is written; Lorem-ipsum chapter and template citations removed with the first real chapter.

## 2026-11-04 (2) — Attended time decided; sources for leveling and robustness — no code change

- **Decided (user):** attended time by three building blocks (operation with a resource set; rest time as a time lag
  on an edge; run structure only for handoff steps with a scarce worker at the end); workload balance for worker
  fatigue probably beyond the thesis; Guo et al. 2023 dropped (Chinese only).
- **Done:** user added the papers to Zotero; passages checked with `text --grep` (7 new, 5 already in the library);
  [32](32_target-data-model.md) §2–3 and [references](references.md) updated.
- **Found:** leveling is a project-scheduling concept with mostly fixed schedule length; the buffer goal belongs to
  robust pro-active scheduling, a strategy next to our predictive-reactive one (`DG38JM6L`, `DPAZ3QNT`); Zhou et al.
  2026 (`EA8QC55F`) use an event trigger between right shift and full rescheduling like ours.
- **Open:** Hartmann & Briskorn surveys, Aribi et al., Sun et al. not in the library; year of Davenport et al.

## 2026-11-04 — Target data model (diagrams): comparison and decisions — no code change

- **Decided (user):** proposing batches to nesting is deprecated; a print run uses exactly one plate set; plate sets
  to be modeled eventually; nesting gets remaining capacities instead of estimated durations (nesting estimates
  better); operations per part to be added with rework; s-batches via maxBatch on many steps; forecast later.
- **Done:** scope note [32](32_target-data-model.md) (correspondence, decisions, todos), pointer in
  [03](03_carriers.md) §6, README.
- **Found:** most of the target model maps onto the code; missing: attended/unattended split, plate sets, capacity
  interface to nesting, rework, calendars, priority, forecast. Aggregate capacity hides timing, so printers need free
  gaps. Zotero not reachable: resource leveling, slack-based robustness and workload balance sources found by web
  search only, not in the library.
- **Open:** attended time (under discussion: three building blocks proposed); add the leveling / robustness / fatigue
  sources to Zotero and check them; workload balance formulation.

## 2026-11-03 (10) — Generator with blanks; dental example — uncommitted

- **Decided (user):** step 3 before committing. Mine: blank capacity as a generator parameter with a placeholder
  (16 parts), steps per carrier with a time per size unit, machine pools for steps sharing machines.
- **Done:** `CarrierGeneratorParams`: `RouteOperation.carries`, `per_carrier`, `machine_pool`, `blank_capacity`,
  blank nesting next fit per part in due-date order — [21](21_instance-generator.md) §4a; example file with blank
  milling, separation, polishing (bench) and carrier milling on the same mills; notebook `05_carriers` re-run in full
  (data changed) with plates and blanks plotted — [03](03_carriers.md) §5; tests (nesting by hand, part times, shared
  mills, polishing waits for both blanks, solvable and replayed, 8 negatives); 875 tests pass.
- **Found:** old parameter files generate the same instances as before (same random draws); the new example is a
  different random instance. The mills are a second bottleneck; CP-SAT does not beat the best rule within 60 s on
  293 operations.
- **Open:** Fidentis durations and blank capacity; polishing across orders; who composes the blank; the remaining
  factory route; a rule that waits to fill oven runs; commit.

## 2026-11-03 (9) — Carrier kinds: blanks (G1, G2) — uncommitted

- **Decided (user):** start step 2. Design (mine): the kind of a carrier is the type of its parts; carrier
  operations name the part type they carry (`carries`), optional with a single kind, so existing instances stay
  valid.
- **Done:** `Operation.carries`, one carrier chain per kind, synchronization across kinds in `operation_graph`
  (schema 0.5, still uncommitted, regenerated) — [03](03_carriers.md) §1, §3, §5, [notation](notation.md);
  `tests/test_carrier_kinds.py` (hand optimum 13, all rules, zero-disturbance, C3, 7 negatives); 865 tests pass.
- **Found:** checker, DES, rules and CP-SAT needed no change: the kinds only change the compiled edges.
- **Open:** generator and dental example with blanks, carrier milling, separation and polishing (step 3; needs the
  blank capacity); polishing across orders; the remaining factory route.

## 2026-11-03 (8) — Runs per carrier (G3, G4) — uncommitted

- **Decided (user):** explicit run mode per carrier step instead of an implicit rule; polishing is often across
  orders (recorded, not modeled).
- **Done:** `CarrierStep.runs` ("none" / "given" / "per_carrier"), schema 0.5 (data, generators, tests bumped;
  `schemas/instance-0.5.json`); validation of setup, removal, estimator and given runs against the run mode;
  `operation_graph` derives one run per carrier — [03](03_carriers.md) §3, §5, [notation](notation.md);
  `tests/test_carrier_runs.py` (hand optimum 12, all rules, zero-disturbance, C9, 6 negatives); 845 tests pass.
- **Found:** setup and removal on a step without given runs were silently dropped before; checker, DES, rules and
  CP-SAT needed no change (they work on machine groups).
- **Open:** G1/G2 (blanks as a second carrier kind), blank capacity, polishing across orders, generator and
  notebook (step 3).

## 2026-11-03 (7) — Mill as a shared machine: facts and gaps — no code change

- **Decided (user):** derive what the model misses from the factory route.
- **Done:** facts on the mill recorded and mapped against the model — [03](03_carriers.md) §6 (G1–G4).
- **Found:** milling is an s-batch, so the batch-step gap stays latent; a blank is a second carrier kind shared by
  orders (G1, G2); setup and removal of a carrier step without given runs are silently ignored (G3).
- **Corrected (user):** QM waits for the primary parts, not the blank (separated before QM, then independent); the
  carrier mill needs no nesting, its load is the carrier. Answers: separation is a worker step; one blank per mill
  run; a worker composes the blank (who should, open).
- **Decided (user):** separation per blank; polishing of primary parts before QM (worker, s-batch); bench stand-in
  for worker steps until 04; blank composition given, planner composition open; route completed gradually, model
  kept general.
- **Open:** blank capacity; polishing within or across orders; implementation steps (proposed, not approved).

## 2026-11-03 (6) — Checker review for carriers and batches — uncommitted

- **Decided (user):** fix the batch-step gap later.
- **Done:** review of the checker (C1–C5 on the compiled graph, C8, C9, C10) with probes on the dispatched plan.
- **Found:** two different batch steps on one machine with identical times are accepted as one run (checker, greedy
  rule and CP-SAT alike) — [03](03_carriers.md) §6, todo.
- **Open:** that todo; capacity of a carrier in telescopes is not checked (composition comes from nesting).

## 2026-11-03 (5) — Oven batches, step 4: rescheduling, generator, notebook — uncommitted

- **Decided (user):** start step 4.
- **Done:** rescheduling tests with batches (rule and CP-SAT planners); generator parameter `batch_capacity` and
  example file with oven capacity 3 ([21](21_instance-generator.md)); `plot_gantt` draws one bar per batch;
  notebook `05_carriers` re-run with oven runs and the loads of every oven run listed — [03](03_carriers.md); 826 tests
  pass.
- **Found:** dental example: makespan 1850 → 978 with oven runs (6 instead of 16); the oven stays the bottleneck;
  CP-SAT groups carriers across print runs, the greedy rule does not; CP-SAT rescheduling (tardiness first) lowers
  total tardiness under disturbances from 274 to 171.
- **Open:** a dispatching rule that waits to fill oven runs; Fidentis durations; print file generation; priority
  classes.

## 2026-11-03 (4) — Oven batches, step 3: CP-SAT — uncommitted

- **Decided (user):** start step 3.
- **Done:** CP-SAT batch slots per family (presence, start, machine, assignment, capacity, symmetry breaking), slot
  intervals instead of the operations' intervals; frozen batch members take a slot with their constant start —
  [03](03_carriers.md) §5, [12](12_cp-sat.md); tests: optimum 36 without and 18 with batching (by hand and proven),
  zero-disturbance of the batched plan, batching optional on the mini instance (20), snapshot with a running batch;
  815 tests pass.
- **Found:** CP-SAT batches carriers that reach the oven at different times only if waiting pays off; the greedy rule
  never waits.
- **Open:** step 4 (rescheduling tests with batches, generator parameter, notebook 05 with oven runs).

## 2026-11-03 (3) — Oven batches, step 2: DES, dispatching, repair — uncommitted

- **Decided (user):** start step 2 (rule: greedy, no waiting; oven duration fixed).
- **Done:** DES joint start of a batch with fixed duration ([13](13_des.md)); greedy batching in dispatching
  ([11](11_dispatching-rules.md)); repair moves a batch as one ([05](05_rescheduling-frozen-part.md)); tests
  `tests/test_batches.py` (hand example, all rules, late worker, fixed duration, repair, 5 seeds); 810 tests pass.
- **Found:** greedy batching only batches carriers that are ready together (e.g. from one print run); carriers of
  different print runs reach the oven at different times and run alone unless a rule waits. CP-SAT from a snapshot
  with a running batch is infeasible until step 3 (fallback keeps the plan).
- **Open:** step 3 (CP-SAT batch slots, also from snapshots), step 4 (rescheduling, generator, notebook).

## 2026-11-03 (2) — Oven batches, step 1: format and checker — uncommitted

- **Decided (user):** an oven run holds up to 3 carriers in parallel (p-batch); program duration fixed (no deviation);
  loading inside the program time; dispatching starts with the ready carriers (greedy); any carriers compatible.
- **Done:** `CarrierStep.batch_capacity`, `CompiledInstance.batch_capacity`, checker C10 (same machine and times,
  at most $c_s$; otherwise C5) — [03](03_carriers.md); tests `tests/test_batches.py`; sources Potts & Kovalyov (2000) and
  Fowler & Mönch (2022) checked in Zotero.
- **Open:** step 2 (DES joint start, greedy batching rule, repair keeps batches), step 3 (CP-SAT batch slots),
  step 4 (rescheduling, generator, notebook).

## 2026-11-03 — Dental carrier example in a notebook — uncommitted

- **Decided (user):** show the dental carrier example in a notebook and visualize carriers and loads.
- **Done:** `plot_carriers` (carriers grouped by run, parts as segments sized e.g. by telescopes, capacity line) and
  shared colors for carrier and run operations in `plot_gantt` (`simulation.viz`, test); notebook
  `notebooks/05_carriers.ipynb`: nesting figure, print times per run, plans (rule, CP-SAT makespan, CP-SAT
  tardiness first), Gantt chart, execution under disturbances (no tool, repair, CP-SAT rescheduling).
- **Found:** the single oven is the bottleneck while every carrier has its own oven operation (16 × 90 min); due dates
  from the lead-time bound were all missed, so the notebook calibrates them with the rule plan
  ([06](06_due-dates.md)). Tardiness first costs 3 minutes of makespan (1850 vs. 1847) and avoids 11 late orders;
  CP-SAT rescheduling lowers total tardiness from 455 (repair) to 298.
- **Open:** oven batching (removes the bottleneck); Fidentis durations.

## 2026-11-02 (7) — Generator with carriers — uncommitted

- **Decided (user):** one secondary part per order with $N$ telescopes, one per primary part (median 4); carrier
  capacity 12 telescopes; up to 4 carriers per print run; priority classes not handled now, nesting by due dates;
  the research stays general (dental case as parameters).
- **Done:** `simulation.carrier_generator` with general parameters (carried / counted part types, size range,
  capacity, carriers per run, route template, machines and durations per step, estimator, due dates) and nesting
  emulation (due-date order, next fit, consecutive carriers per run) — [21](21_instance-generator.md) §4a; example
  `data/generator/dental-carriers-example.json` (placeholder durations); 22 tests; 777 tests pass.
- **Found:** next fit in due-date order leaves some carriers underfilled (e.g. 40 orders → 16 carriers); real nesting
  may fill better.
- **Open:** Fidentis durations for the example; priority classes; freezing at print file generation; oven batching.

## 2026-11-02 (6) — Carriers, step 5: rescheduling and due dates — uncommitted

- **Decided (user):** start step 5.
- **Done:** dispatching from a snapshot continues a partly started run on its machine; rescheduling with the rule
  planner and CP-SAT on the carrier instance (thresholds and safety net) keeps all constraints; due dates for carrier
  instances (lead-time bound with carrier steps, reference plans with carrier and run entries) — [03](03_carriers.md) §5,
  [06](06_due-dates.md), [11](11_dispatching-rules.md); 755 tests pass.
- **Found:** CP-SAT handled partly started runs already through the span interval (step 3); only dispatching needed a change.
- **Open (questions to the user):** generator with carriers (parts per order, nesting emulation, priority classes);
  how print file generation freezes a run; oven batching as the next carrier step.

## 2026-11-02 (5) — Carriers, step 4: run-duration estimator — uncommitted

- **Decided (user):** start step 4.
- **Done:** run duration from nesting (`Run.duration`), else `estimate_run_duration` ($p^0 + \lambda \sum p_\pi$,
  clamped to $[\max p_\pi, \sum p_\pi]$), else the constant per machine; set once in the compilation, so every
  consumer sees the same value — [03](03_carriers.md) §3, §5; format fields `Part.times`, `CarrierStep.estimator`,
  `Run.duration` (schema 0.4 regenerated in place, it was not committed); tests by hand; 745 tests pass.
- **Found:** with the estimator the duration no longer depends on the printer (identical printers assumed).
- **Open:** form and parameters of the estimator with Fidentis data; machine-dependent run durations; step 5.

## 2026-11-02 (4) — Carriers, step 3: CP-SAT — uncommitted

- **Decided (user):** start step 3.
- **Done:** CP-SAT with C8 (equal machine choices within a run) and C9 (one span interval per run and machine
  instead of the single intervals) — [12](12_cp-sat.md), [03](03_carriers.md) §5; tests: optimum 20 on the mini instance
  (lower bound by hand), zero-disturbance of the CP-SAT plan, blocking while a removal waits (from a snapshot, one
  printer), partly started run continued on its machine; 735 tests pass.
- **Found:** a mutation run without the span lets the solver put the next setup into the gap before a waiting
  removal (C9 violated), so the test checks the real case. With all steps 1–3 the Definition of Done for carriers is
  met except the estimator (step 4) and rescheduling / generator (step 5).
- **Open:** estimator (step 4); dispatching from a partly started run, generator with carriers, due dates for
  carrier instances (step 5); oven batching.

## 2026-11-02 (3) — Carriers, step 2: DES and dispatching — uncommitted

- **Decided (user):** start step 2.
- **Done:**
  - order completion over all operations serving an order (`objectives._order_ends`, `run_metrics`), so carrier and
    run owners are not counted as orders — [03](03_carriers.md) §5;
  - scenarios over all compiled operations (same draws for instances without carriers) — [22](22_scenarios.md);
  - dispatching: a run as one unit, placed back to back on one machine — [11](11_dispatching-rules.md);
  - DES unchanged: C9 holds through the planned order per machine — [13](13_des.md);
  - tests: SPT + ECT reproduces the hand plan; all 15 rule combinations feasible and zero-disturbance; late removal
    blocks the printer; disturbed execution with repair keeps C8/C9; 731 tests pass.
- **Found:** ECT sees only the setup of a run and picks the busy printer (makespan 23 vs. 20 with least load).
- **Open:** step 3 (CP-SAT with C8/C9 and the zero-disturbance check against the CP-SAT value), estimator (step 4),
  partly started runs in rescheduling (step 5), oven duration under disturbances.

## 2026-11-02 (2) — Carriers, step 1: format, compilation, checker — uncommitted

- **Decided (user):** naming: **carrier** for the build plate with its bound parts, **load** keeps the meaning of
  `CLAUDE.md` (what one machine run processes), **run** for the machine run; start step 1.
- **Done:**
  - instance format 0.4: parts with types, operation scopes and roles, `carrier_steps`, `carriers`, `runs`;
    validation with one negative test per rule (20) — [03](03_carriers.md) §5;
  - derivation rule (`operation_graph`) and compilation: one operation per carrier and run instead of per order;
    `op_order` → `op_orders`, new `machine_groups`; objectives, dispatching, visualization adapted;
  - checker C8 (one machine per run) and C9 (machine blocked from setup start to removal end);
  - mini instance `data/instances/toy-carriers.json` with a hand-computed plan (makespan 23); 707 tests pass.
- **Found:** the compiled graph is acyclic by construction unless a run groups a step at different chain positions;
  the cycle check stays in the validation (test with such runs).
- **Open:** step 2 (DES and a dispatching rule with C8 / C9), step 3 (CP-SAT), step 4 (estimator), step 5
  (rescheduling, generator), oven batching; print file generation; primary parts at several QMs; Zotero sources.

## 2026-11-02 — Load model: decisions — uncommitted

- **Decided (user):** load spec ("persistent batch dependencies") with answers: MES data model (orders with typed
  parts and one route; scopes order / part type / load; loads list member parts; print runs list plates; all
  synchronization derived by one compiler rule); **one QM per plate**; print runs given by nesting, oven runs a planner
  decision in a later step; estimator for the whole print run; frozen after print file generation; setup and removal
  as own operations with default times; loads before workers; walking time not included in durations.
- **Done:** decisions recorded in [03](03_carriers.md) §0; first format sketch with explicit cross-references discarded.
- **Open:** primary parts used by several plate QMs; print file generation in the model; owner of load operations in
  the schedule format; Zotero was not reachable, sources unverified.

## 2026-10-30 (7) — LLMs in scheduling: scope decision — uncommitted

- **Decided (user):** option A, no LLM component in the thesis for now; B (LLM as offline generator of rules or GA
  operators) and possibly C (bounded online advisor) may be tried later.
- **Discussed:** the user's view of the field (strong on hybrid prototypes; gaps in domain breadth, feasibility
  under real constraints, end-to-end decision support; weak on generalizable, trustworthy, production-ready decision
  models). Supported by the review in Shiau et al. (2026); the user's further papers are not in the library yet.
  Own answer: feasibility is mainly an architecture question (verifier has the last word); the open question is the
  measured added value over a strong non-LLM baseline; production readiness cannot be shown in a thesis, a closed-loop
  evaluation in simulation can.
- **Done:** [31](31_llm-in-scheduling.md) with the assessment, the evidence table, the paper's limits, options A/B/C.
- **Open:** add the user's further LLM papers to Zotero before citing them.

## 2026-10-30 (6) — Safety net, trigger on the objective, LLM paper — uncommitted

- **Decided (user):** do todos 1 (periodic safety net) and 2 (trigger on the planner's objective); then review the
  paper of Shiau et al. (2026) on bounded LLM judgment, which challenges the view that LLMs are of little use for
  scheduling.
- **Done:**
  - `ReschedulingPolicy(objective, max_objective_change, period)`: trigger on $|\Delta f| > \delta_f$ and a periodic
    complete rescheduling at the latest $\tau$ minutes after the last one (hybrid policy); anchor with time
    (`Anchor(plan, t)`); REPLAN records list their triggers — [05](05_rescheduling-frozen-part.md) §3;
  - DES event WAKE (`wake_at`) so that the planning tool gets a time point without a factory event — [13](13_des.md) §3;
  - tests: periodic at 4 and 8 without disturbance; period restarts after a triggered rescheduling (4, 6, 10);
    tardiness trigger fires at $t = 9$ where the makespan trigger fires at 11; invalid policies rejected.
  - Paper read in full (`F5VQRD7Z`); frozen horizon, anti-thrashing and stability measures recorded —
    [05](05_rescheduling-frozen-part.md) §6, [23](23_metrics.md) §6, [references](references.md).
- **Found (paper):** the LLM never schedules; it audits a deterministic rule over already verified candidates, falls
  back to the rule on any failure, and a human decides. The validation used a deterministic **stub** instead of a real
  LLM (p. 21), so it shows fail-safe integration, not judgment quality; the gated policy is not compared with simpler
  policies (p. 24, protocol proposed only). The non-LLM part (ignore / repair / frozen-horizon rescheduling, stability
  score, recovery threshold, anti-thrashing) is close to our planning tool.
- **Open:** choice of $\tau$; anti-thrashing as minimum interval; Kendall sequence similarity as metric; frozen
  horizon (machine and start kept, affected operations released).

## 2026-10-30 (5) — Protocol

- **Decided (user):** a working protocol inside `math/` instead of a change log in the repository; maintained after
  every pass (rule in `CLAUDE.md`).
- **Done:** this file; `CHANGELOG.md` removed again.

## 2026-10-30 (4) — Due dates, tardiness, lexicographic objective, calibration — commit `28ac70f`

- **Decided (user):**
  - due dates per order, soft, no weights or priorities yet (express orders later);
  - DES event `DUE` renamed to `PLANNED_START` (no confusion with due dates);
  - notebook split by topic; from now on only changed cells (and cells affected by library changes) are rerun;
  - $\theta = 0.5$ is not meaningful (an order that cannot be on time even alone) → calibrate due dates;
  - lexicographic objective instead of "hard deadlines first, soft as fallback";
  - **todo:** rescheduling trigger on the planner's objective (not only the makespan).
- **Done:**
  - instance schema 0.3 with `Order.due_date`, validation, generation from the longest path $\Lambda_k$ (Li et al.
    2026, own adaptation for parallel branches), generator parameter — [06](06_due-dates.md), [21](21_instance-generator.md);
  - objectives total tardiness and number of tardy orders (exact CP-SAT reification), EDD rule, brute-force oracle —
    [06](06_due-dates.md) §4, [11](11_dispatching-rules.md), [12](12_cp-sat.md);
  - `lexicographic(...)`: exact weighted sum, weights from the spreads of the lower levels, valid also for snapshot
    models (proof in [06](06_due-dates.md) §4);
  - calibration: due dates relative to the flow times of a reference plan, $\theta_k \ge 1$ — [06](06_due-dates.md) §1;
  - due-date metrics (total tardiness, tardy orders, $L_{\max}$) — [23](23_metrics.md);
  - notebooks `01`–`04`; `04_rescheduling` section "Due dates".
- **Found:**
  - CP-SAT optimizes one objective; calling `minimize` again replaces it (OR-Tools 9.15). Tardiness alone has many
    optima with $\sum T = 0$ and stops at makespan 52 on mk01; tardiness then makespan gives 0 / 40.
  - With $\Lambda_k$-based due dates and Li et al.'s set, 9–10 of 10 mk01 orders are late under disturbances.
  - Calibrated ($\theta \in \{1, 1.2, 1.5\}$): rescheduling with tardiness first lowers $\sum T$ from 74 (repair only)
    to 33, at a longer makespan (60 vs. 52); still 6–7 orders late → slack has to match the disturbance level.
  - Wu et al. (1993, `TLCUQTJ9`): their "sequence deviation" is a start-time deviation against the right-shift
    schedule, not a count of swaps — [23](23_metrics.md) §6.
- **Open:** trigger on the planner's objective (todo); slack vs. disturbance level; generator only with $\Lambda_k$;
  performance of large lexicographic weights.

## 2026-10-30 (3) — Metrics, OVERDUE, frozen-horizon literature — commit `8c931b3`

- **Decided (user):** OVERDUE event first, then metrics; frozen horizon later; periodic safety net stays a todo;
  dynamic threshold noted for later.
- **Done:**
  - OVERDUE event at the expected end of a running operation, then every minute — [13](13_des.md) §3;
  - metrics per run (makespan, mean flow time, $D_S$, $D_M$, repairs, reschedulings, planner time), CSV output —
    [23](23_metrics.md);
  - notebook: mk01 table with metrics, reproducible CP-SAT start plan (1 worker).
- **Found:**
  - before OVERDUE, an overrun was only seen at the next unrelated event (toy: nothing between $t = 10$ and 14);
  - CP-SAT rescheduling lowers the makespan but raises the mean flow time; rule planner has the lowest flow time;
  - the budget $\kappa$ limits changes per rescheduling, not per run;
  - `solve` with 8 workers is not reproducible (start plan changed between runs).
  - Frozen horizon: no source in Zotero (only Pinedo on freezing single jobs with tolerances); web: Sridharan et al.
    (1987), Blackburn et al. (1986) on MPS freezing, not in the library **[uncertain]** — [05](05_rescheduling-frozen-part.md) §6.
- **Open:** sequence deviation; tardiness (needed due dates → next pass).

## 2026-10-30 (2) — Start offsets (B), trigger anchor — commit `8c931b3`

- **Decided (user):**
  - start offsets count from **actual readiness** (option B), with and without repair;
  - trigger against an **anchor** (option a); periodic safety net (b) as todo; dynamic threshold (c) later.
- **Done:** late offset delays the start after the operation is due and ready, counted once —
  [13](13_des.md) §3, [22](22_scenarios.md); anchor = plan of the last complete rescheduling (also after a
  rejection) — [05](05_rescheduling-frozen-part.md) §3; notebook rescheduling section.
- **Found:**
  - with the old offset rule, repair added a late worker on top of predecessor delays (mk01: 65 vs. 45 without repair);
  - repair alone gains almost nothing once start offsets exist (late workers keep the plan behind);
  - drift: with $\delta_C = 2$ the trigger measured against the last sent plan almost never fired (0.1 per run);
    with the anchor 6 reschedulings, makespan 51.7 instead of 58.7.

## 2026-10-30 (1) — CP-SAT rescheduling — commit `8c931b3`

- **Done:** CP-SAT from a snapshot (frozen operations as fixed intervals, C6 as lower bound, change budget as
  constraint, `cpsat_planner`) — [12](12_cp-sat.md) §7.
- **Found:** rule-based rescheduling can make a good plan worse (toy 14 vs. 13), CP-SAT does not (13); budget trades
  stability for makespan (toy: $\kappa = 0/1/2$ → 16/15/14).

## 2026-10-29/30 — Repair and rescheduling design — commits `17d05a8`, `77ac242`

- **Decided (user):**
  - the DES is only the factory; repair and complete rescheduling belong to the planning tool;
  - terminology: repair = left/right shift (schedule repair), complete rescheduling = regeneration (Vieira et al. 2003);
  - no improvement condition for accepting a new plan (makespan is not the only objective);
  - start deviation: no deviation with probability $q$, else uniform in $[-a, b]$; durations stay log-normal;
  - no overtaking on machines; left shift only for tight operations, gaps are kept;
  - stability first as acceptance by change budget, later as objective;
  - reference plan = the plan last sent to the MES;
  - feasibility checker split into named functions.
- **Done:** checker with C6/C7; DES as `Simulation`; shift repair; thresholds and budget; dispatching from a
  snapshot — [05](05_rescheduling-frozen-part.md), [01](01_basic-fjsp.md), [11](11_dispatching-rules.md) §5,
  [13](13_des.md), [22](22_scenarios.md).
- **Open:** drift (noted), stability as objective, frozen horizon, QM rework loops, workers and loads as blockers.

## 2026-10-23 — Snapshots — commit `d7ca0e5`

- **Done:** pausable DES, snapshot with frozen part and expected ends, leakage test — [13](13_des.md).

## 2026-10-22 — Scenarios and generator — commit `2b20b69`

- **Done:** log-normal processing-time factors (mean 1) — [22](22_scenarios.md); DES v2 under disturbances —
  [13](13_des.md); instance generator with routing modes and templates — [21](21_instance-generator.md).

## 2026-10-21 — CP-SAT and DES v1 — commits `6300e52`, `bf25ab4`

- **Done:** CP-SAT model of C1–C5 with objective interface, warm start, brute-force check — [12](12_cp-sat.md);
  DES v1 replay and zero-disturbance tests — [13](13_des.md).

## 2026-10-19/20 — Feasibility checker, dispatching rules — commits `e8617db`, `75065e4`

- **Done:** independent checker for C1–C5 — [01](01_basic-fjsp.md) §5; rules SPT, FIFO, MWKR, LRP with least load,
  ECT or joint mode, hand-computed examples — [11](11_dispatching-rules.md); loads draft — [03](03_carriers.md);
  visualization and first notebook.
- **Found:** problem classified as FJSP with arbitrary precedence graphs (Kasapidis et al. 2021) plus release times;
  complexity via Garey et al. (1976) — [01](01_basic-fjsp.md).

## 2026-10-18 — Data model and loaders — commit `1217f7e`

- **Done:** Pydantic models, `CompiledInstance`, JSON and Brandimarte loaders, schema 0.2 — [01](01_basic-fjsp.md),
  [notation](notation.md).

## 2026-10-01 — Project start — commit `2eb3e4e`

- **Done:** README, diagrams, project setup.
