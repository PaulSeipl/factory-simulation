# 21 Instance generator

Files `2x` describe data generation and experiments; `0x` model components; `1x` solution methods and simulation.

## 1. Prose description

The generator creates random instances of the base model ([01](01_basic-fjsp.md)) from a small set of parameters: number of machines, orders and operations, order length, routing flexibility, durations, release times, and the precedence structure of the orders. It is deterministic per seed. The parameters are stored as a separate JSON file next to the instance (`<name>.json` and `<name>.params.json`), so that every generated instance can be reproduced.

Instance and scenario are generated separately (terminology in `CLAUDE.md`): an instance is generated once, disturbance scenarios are sampled for it per seed (next step). This keeps the effect of disturbances separable from the effect of the instance.

## 2. Parameters

| Parameter | Meaning | Default |
|---|---|---|
| `seed` | random seed | (required) |
| `n_machines`, `n_orders`, `n_operations` | totals, including template orders and their operations | (required) |
| `min_order_length` | minimum number of operations of a generated order | 1 |
| `max_machines_per_op` | number of eligible machines per operation, uniform in $1..$`max` | 1 |
| `duration_range` | base duration $b_o$ of an operation, uniform integer in [min, max] | (1, 10) |
| `max_duration_spread` | $p_{o,m} = b_o + \delta_{o,m}$, $\delta_{o,m}$ uniform in $0..$spread; so $\max_m p_{o,m} - \min_m p_{o,m} \le$ spread | 0 |
| `release_range` | release $r_k$, uniform integer in [min, max] | (0, 0) |
| `routing_modes` | allowed precedence structures; each generated order draws one uniformly | (`chain`) |
| `max_branches` | maximum number of parallel branches in `split`, `join`, `split_join` | 2 |
| `templates` | orders with a given precedence structure (see section 4) | none |
| `due_date_tightness` | set of tightness factors $\mathrm{DDT}$; each order draws one uniformly, $d_k = r_k + \lfloor \mathrm{DDT}_k \Lambda_k + 1/2 \rfloor$ ([06](06_due-dates.md)); own random stream | () = no due dates |
| `name` | instance name; default `gen-m{machines}-k{orders}-o{operations}-s{seed}` | derived |

Validation (`GeneratorParams`): ranges with min ≤ max; `max_machines_per_op` ≤ `n_machines`; `min_order_length` at least the minimum length of every allowed routing mode; enough operations for all generated orders at their minimum length.

## 3. Construction

1. Machines $M_1, \dots, M_n$.
2. Order lengths: every generated order gets `min_order_length` operations; each remaining operation is added to a uniformly drawn generated order.
3. Precedence per order of length $n$, depending on the drawn routing mode:

| Mode | Structure | Minimum length |
|---|---|---|
| `chain` | $1 \to 2 \to \dots \to n$ | 1 |
| `split` | head operation $\to$ $k$ parallel branches (chains), no rejoin | 3 |
| `join` | $k$ parallel branches $\to$ tail operation | 3 |
| `split_join` | head $\to$ $k$ branches $\to$ tail (fork and reconvergence) | 4 |

   $k$ is uniform in $2..\min(\text{max\_branches}, \text{number of branch operations})$; the branch operations are split into $k$ non-empty consecutive chains at uniformly drawn cut points.
4. Per operation: number of eligible machines uniform in $1..$`max_machines_per_op`, machines drawn without replacement, base duration and spread as in section 2.
5. Release per order from `release_range`.

`split_join` reproduces the structure of the dental orders on a basic level (one path for the secondary part, paths for the primary parts, reconvergence at QM); identical primary-part paths are not generated automatically but can be given as a template.

The generated instance passes the same validation as every JSON instance (`Instance`), in particular acyclicity.

## 4. Templates

A template gives the operations of one order with their predecessors; per operation it may also give the eligible machines with durations. Given options are kept, missing ones are generated as in section 3. Template orders are named `T1, T2, ...`, generated orders `O1, O2, ...`, operations of generated orders `1..n`.

## 4a. Instances with carriers

A second generator builds instances with carriers ([03](03_carriers.md)), stated generally and parameterized for the dental case (user, 2026-11-02):

| General rule | Dental case |
|---|---|
| Every order follows one route template with scopes (order, part type, carrier) | design → milling of the primary parts → print → oven → QM → saw → finish |
| Every order has one **carried** part; its **size** $n_k$ is the number of **counted** parts of the order, $n_k \sim U\{a, \dots, b\}$ | one secondary part with $n_k$ telescopes, one per primary part; $n_k \in \{1, \dots, 7\}$, median 4 |
| Carrier capacity $Q$ in size units | 12 telescopes (e.g. 3 secondary parts with 4 telescopes) |
| At most $Q_R$ carriers per run of the run step | 4 plates per print |
| An operation scoped to a part type takes $n \cdot p$ for $n$ parts of that type, $p$ drawn per order (s-batch without setup) | milling of $n_k$ primary parts |
| Part time for the run estimator: $n_k \cdot$ `unit_time` | print time per telescope |

**Nesting emulation.** Nesting is external in the real process (it delivers carriers and print runs). The generator emulates it: orders in due-date order (then release, then index), carriers filled one after another (next fit) up to $Q$, consecutive carriers grouped into runs of $Q_R$. Priority classes (only parts of one class on a plate) are not modeled. Next fit keeps urgent parts together but can leave carriers underfilled; real nesting may fill them better.

**Blanks** (second carrier kind, [03](03_carriers.md) G1): if route operations carry the counted type, the counted parts (dental: primary parts) go on blanks, next fit in the same order up to the blank capacity $Q^B$, one part at a time, so an order may span two blanks. In the real process a worker composes the blank (whether a planner should, is open); the emulation stands in for it. **Steps per carrier** (`per_carrier`): every carrier is its own run (setup, main, removal); the main operation is the sum of the part times, a part's time being its size times `unit_time` (plate: telescopes, blank: one per primary part). **Machine pools** (`machine_pool`): several steps on the same machines (blank and carrier milling on the mills; separation and polishing on the bench, a stand-in for workers until the workers component (04, not written yet)).

Due dates (if a tightness set is given) are drawn before nesting from the lead-time bound $\Lambda_k$ incl. carrier steps ([06](06_due-dates.md)), own random stream as in `assign_due_dates`.

## 5. Implementation in code

`simulation.generator`: `GeneratorParams` (Pydantic, frozen, `extra="forbid"`; also the format of the parameter file), `generate_instance(params) -> Instance`. Random numbers from `random.Random(seed)` (standard library).

Tests (`tests/test_generator.py`): same seed gives the same instance, another seed another one; counts, order lengths, numbers of eligible machines, duration ranges, spread and release ranges hold; each routing mode has its shape (sources, sinks, forks, merges, branch count); templates keep structure and given options; one test per parameter inconsistency; a generated instance round-trips together with its parameter file and has a feasible dispatching schedule.

Carriers: `simulation.carrier_generator.CarrierGeneratorParams` (route as `RouteOperation`s, machines per step, duration ranges per step, `carried_type`, `counted_type`, `count_range`, `carrier_capacity`, `carriers_per_run`, `run_step`, `setup`, `removal`, `unit_time`, `estimator`, `batch_capacity` (carrier step → carriers per planner-decided run, e.g. oven 3), `per_carrier` (carrier step → setup, removal, `unit_time`), `machine_pool` (step → machines of another step), `blank_capacity`, `due_date_tightness`) and `generate_carrier_instance`. Validation: ranges, machines (via the pool) and durations for every step of the route, maximum size within the capacity, run step is a carrier step and carries no blank parts, estimator needs `unit_time`, `per_carrier` only for carrier steps that are neither run nor batch steps, carrier operations carry only the carried or the counted type, `blank_capacity` exactly when carrier operations carry the counted type. Example parameter file: `data/generator/dental-carriers-example.json` (40 orders; **the durations are placeholders, not Fidentis data**). Tests (`tests/test_carrier_generator.py`): nesting by hand (7 orders of size 4, capacity 12, 2 carriers per run: carriers O1–O3, O4–O6, O7; runs C1+C2, C3); determinism; for 10 seeds capacity, run size and due-date order of the nesting; part-type operations scale with $n_k$; generated instances solvable by rules and CP-SAT and replayed unchanged; seven negative tests. With blanks: nesting by hand (3 orders of 4 primary parts, blank capacity 6: B1 = O1 + half of O2, B2 = other half of O2 + O3), part times (plate $4 \cdot 4 = 16$, primary part 12), both milling steps on the same mills, blank milling $6 \cdot 12$, polishing of O2 waits for both blanks; solvable and replayed unchanged; eight negative tests. Example file (2026-11-03): blanks of 16 parts, blank milling 8 per part, carrier milling 3 per telescope, setup and removal 10 each, separation 5–10, polishing 3–6 per part (all placeholders).

## 6. Assumptions and open points

- Blanks: capacity in parts, not by size or material; next fit per part; the composition is fixed before planning.
- Carriers: one carried part per order; all machines of a step identical; carrier steps take one duration per step and instance; next-fit nesting in due-date order without priority classes; placeholder durations in the example file.

- Uniform distributions throughout; no correlation between the durations of an operation on different machines beyond the common base duration.
- Branches are chains; nested splits are only possible via templates.
- Workers and loads are not generated yet (they enter with their model components).
- The parameter file stores the generator parameters, not the generator version; a change of the generator code changes the instance for the same parameters. The tests pin the current behavior only indirectly.

## 7. Sources

Own design. Benchmark generators from the literature (e.g. the generation of the Brandimarte instances) have not been read and are not followed.

## 8. Change log

| Date | Commit | Change |
|---|---|---|
| 2026-10-22 | uncommitted | Instance generator with routing modes chain, split, join, split_join, templates, parameter file. |
| 2026-10-30 | uncommitted | Parameter `due_date_tightness` (due dates, see 06); schema 0.3. |
| 2026-11-02 | uncommitted | Generator for instances with carriers: one carried part per order with size = number of counted parts, carrier capacity, runs, nesting emulation in due-date order; dental example parameters. |
| 2026-11-03 | uncommitted | Generator parameter batch_capacity (oven runs). |
| 2026-11-03 | uncommitted | Blanks, steps per carrier and machine pools in the carrier generator; dental example with blank milling, separation, polishing and carrier milling. |
