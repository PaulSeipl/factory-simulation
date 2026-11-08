# Terminology (binding)

Single source for the terms used in code, `math/` and the thesis. Imported by `simulation/CLAUDE.md` and `seipl27/CLAUDE.md`; change terms only here. Formal definitions: [03_carriers.md](03_carriers.md) (carriers, loads, runs), [05_rescheduling-frozen-part.md](05_rescheduling-frozen-part.md) (repair, rescheduling).

- **Order:** customer order
- **Operation:** one processing step of an order; `id` is unique only within its order, `(order_id, op_id)` identifies an operation globally
- **Step:** the process step type of an operation (e.g. printing, QM); repeats across orders
- **Part:** physical item of an order. **Secondary part:** printed on a build plate. **Primary part:** milled from a blank
- **Carrier:** a build plate with the parts printed on it, or a blank with the parts milled from it, possibly from several orders. The parts stay bound to it from the forming operation (print, milling) to the separating operation (sawing). This persistent binding is the "persistent batch dependency" of the thesis title
- **Machine Run** (short: **Run**): an unattended machine run (called "Job" in the MES); setup, main operation and removal on one machine. Its load is one or more carriers (e.g. up to four plates in one print)
- **Load:** the units processed together in one machine run (corresponds to "batch" in the BPM literature). Carriers persist across operations; loads exist only for one machine run
- **Instance:** static problem description of an experiment; **Snapshot:** instance plus runtime state at time t; **Scenario:** sampled disturbances for one seed
- **DES:** Discrete-Event Simulation, not "deterministic"
- **Repair (shift repair):** adapting the current plan by moving start times earlier or later (left/right shift); machine assignment and order per machine stay unchanged ("schedule repair" in Vieira et al. 2003)
- **Complete rescheduling:** a planner generates a new plan for all operations not yet started, from a snapshot ("regeneration" in Vieira et al. 2003)
- **Order-internal precedence** (also **non-linear routes**, $\beta = bom$ in Dauzère-Pérès et al. 2024): the precedence DAG within one order. Do not write "JPC": "job" means the machine run in the MES, and no source for the abbreviation is in the library
- Do not use "job" or "batch" loosely; FJSP literature means something specific by both
