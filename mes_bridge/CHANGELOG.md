# Changelog

`mes_bridge` only; thesis changes go to `math/protocol.md`. Newest first.

## Unreleased

- `mes_bridge.instance.build_instance`: MES problem → thesis `Instance` (slice 1, SECONDARY lane). Plates are
  carriers; the print a given run per AM job (AM_PREP = setup + main, PART_POWDER_REMOVAL = removal), the
  secondary mill a given run per plate (MILL_PREP_SECONDARY = setup + main, SECONDARY_PLATE_REMOVAL = removal);
  cleaning, heat treatment, blasting carrier steps without runs (cleaning and blasting as s-batches of the MES
  linear form); DATA_PREP_SEC_MILL an order operation. Step shape from `params`, run and order minutes from the
  operations (an entered job estimate wins). Epoch Monday 00:00 in the MES time zone, minutes rounded up,
  instants before it clamped to 0; global calendar (shift = daily minutes + break). Shortcuts, each marked in
  the code: break 12:00 / 60 min until 4.3; REWORK left out until slice 3; the last carrier operation in scope
  takes the separating role the format needs (V14); an overdue due date clamps to the first cutoff after release;
  the oven is a worker step with an unattended rest and no p-batch (no oven machine in the export). Anything
  else the format cannot hold raises `MappingError`. Tests: both recordings map, compile, plan with `spt` and
  pass `check_schedule`; hand values; one negative test per `MappingError` rule; a V14 failure surfaces.
- `mes_bridge.api`: hand-written models of `GET /planning/problem` and `PUT` / `GET /planning/schedule`
  (`extra="forbid"`, MES enums as strings). `tests/test_contract.py` compares them field by field with the
  checked-in copy `tests/data/openapi.json` (decision 15); a detector self-test. Recorded problem responses
  `tests/data/problem_mill_prep.json` (two orders on two plates of one print, one mill job formed, one mill
  data prep running) and `problem_printing.json` (both mill jobs formed, AM_PREP handed off), from the MES
  test helpers of `tests/services/test_planning_problem.py` via a temporary test (not committed).
- Skeleton: own uv project with an editable path dependency on `simulation` (no workspace, so the thesis lock
  stays untouched); test that `src/simulation` never imports `mes_bridge`.
