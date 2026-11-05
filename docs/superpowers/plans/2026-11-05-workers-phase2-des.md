# Workers, phase 2: DES with workers, shifts and breaks — plan

**Goal:** the DES executes plans with workers: worker shares, machine-less operations, shifts, breaks, overtime,
the swap rule and the soft oven suffix; the realized schedule passes the checker and, without disturbances,
equals the plan (zero-disturbance test).

**Spec:** `docs/superpowers/specs/2026-11-05-workers-shifts-design.md` §3.2, §6, §8. Working style: one task at a
time, tests, result, approval (`CLAUDE.md`). Rules, CP-SAT, repair and rescheduling keep their guard
(`reject_workers`) until phases 3–4; only the DES guard goes.

## Behavior to implement (decisions; mine marked)

1. **Workers follow their planned order** (no overtaking), like machines (user, 2026-11-05). A share can start
   when its operation can start (or, for a suffix, when the operation's machine part is done) and it is next in
   its worker's planned order.
2. **Realized durations under disturbances (mine, from spec §3.2):** everything scales with the scenario factor
   except rest and fixed programs.
   - machine operation: $p' = \mathrm{round}(p f)$ as today; its prefix/suffix $a' = \min(\mathrm{round}(a f), p')$;
   - machine-less operation with prefix: $a' = \mathrm{round}(a f)$, $p' = a' + (p - a)$ (rest fixed, user);
   - whole share: the operation's $p'$;
   - oven batch: $f = 1$ (program fixed, as today).
3. **Suffix (oven removal), soft (user):** when the program ends and the suffix worker is busy, the removal
   waits; the operation (and the machine) ends later. Waiting minutes are recorded as **oven overstay**.
4. **Shift window (mine):** a worker starts a share only on a working day, at or after shift start, outside its
   break, and only if the share's *planned* length fits before shift end + max overtime (no leakage: planned,
   not realized); otherwise it waits for the next possible time. A share that then runs past 19:30 is finished
   (no preemption) and recorded as an **overrun**.
5. **Breaks (user, spec §6):** each worker takes its planned break at the planned start if free; if busy, right
   after finishing the current share (postponed individually). A worker does not start a new share while its
   break is due. Realized breaks are part of the result; postponement and spread are metrics.
6. **Overtime:** realized worker time after shift end is recorded per worker and day (metric).
7. **Swap rule (user, spec §6):** when an operation's share is due (operation ready, planned start reached) but
   its planned worker is busy, a qualified worker who is free now, may work now (rule 4/5), and whose next
   planned share starts no earlier than now + planned share length takes it; tie-break: most room before the
   next planned share (mine). The DES writes the actual worker into its current plan. Never fires without
   disturbances.
8. **Snapshot:** `FrozenOperation.workers` (actual workers of started shares; a running oven shows its planned
   suffix worker); the planning tool sees swaps at the next time point.

## Tasks

### Task 1: Shares and machine-less operations in the DES (no calendar effects)
- `Simulation(ci, plan, scenario=None, breaks=())`; validation with `check_schedule(..., breaks=breaks)`; DES
  guard removed (machine-less operations, workers present).
- State: planned worker per share, planned order per worker, busy-until per worker; realized durations by rule 2;
  start condition extended by rule 1; suffix handling by rule 3 (event when the machine part ends).
- `realized()` / `current_plan()` carry `workers`; `SimResult.breaks` (planned breaks passed through here).
- Tests (`tests/test_des_workers.py`): zero-disturbance on `toy-workers.json` (hand plan) and on the carrier
  instance with the oven batch (`test_worker_compile.CARRIERS` plan); realized schedules pass the checker under
  5 seeds; hand example: worker of a prefix late (start offset) delays the operation; oven suffix worker busy →
  overstay by hand; Gegenbetten rest fixed, prefix scaled.
- `math/13_des.md`, `22_scenarios.md` (rule 2), `04_workers.md` §5; protocol.

### Task 2: Calendar in the DES (shift window, breaks, overtime)
- Rules 4–6: waiting for the shift window; breaks taken at the planned time or postponed; realized breaks;
  overtime and overrun records in the log.
- Tests: zero-disturbance with breaks; hand examples: a delayed share near 17:30 that still fits (overtime
  recorded), one that does not fit before 19:30 (waits until 08:00 next working day, Friday → Monday), a share
  running into the break (break postponed), realized schedule + realized breaks pass C11–C14 except where a
  postponement is the recorded deviation (C14 window check relaxed for realized breaks: documented).
- `math/13`, `04`; protocol.

### Task 3: Swap rule
- Rule 7, current plan updated with the actual worker; log record `SWAP`.
- Tests: hand example (Anna late, Ben free and fits → Ben takes it; Ben's next task too early → no swap;
  qualification respected); zero-disturbance never swaps; checker on the realized schedule.
- `math/13`, `04`; protocol.

### Task 4: Snapshot and metrics
- `FrozenOperation.workers`; `snapshot()` fills it (rule 8); checker C7 compares workers of started shares.
- `run_metrics` with workers/calendar: overtime per worker and day (sum), break postponement and spread, oven
  overstay, overruns, swaps.
- Tests: snapshot of a running oven (planned suffix worker), leakage test still holds; metric values by hand.
- `math/23_metrics.md`, `13`, `04`; protocol.

## Open points to confirm (defaults above)
- Rule 4: should a worker refuse to start a share that is expected to run past 19:30 (default), or start it and
  overrun?
- Rule 2: the attended share of a machine operation scales with the same factor as the machine time (default).
