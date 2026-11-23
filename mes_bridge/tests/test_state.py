"""MES snapshot -> thesis Snapshot and the id map (task 1.5c), on the recorded responses of `tests/data/`."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from mes_bridge.api import ProblemOut
from mes_bridge.instance import MILL, PRINT, MappingError, at, build_instance, epoch_of
from mes_bridge.state import build_snapshot, id_map
from simulation.check.feasibility import check_schedule
from simulation.model.compiled import compile_instance
from simulation.planners.dispatching import dispatch_plan, spt

DATA = Path(__file__).parent / "data"
BERLIN = ZoneInfo("Europe/Berlin")


def _raw(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _state(raw: dict):
    p = ProblemOut.model_validate(raw)
    epoch = epoch_of(p.as_of, BERLIN)
    ci = compile_instance(build_instance(p, epoch=epoch))
    ids = id_map(p, ci)
    return p, epoch, ci, ids, build_snapshot(p, ci, ids, epoch=epoch)


def _frozen(snap) -> dict:
    return {(f.order_id, f.op_id): f for f in snap.frozen}


def _task(raw: dict, suffix: str) -> dict:
    return next(t for t in raw["snapshot"]["tasks"] if t["key"].endswith(suffix))


def _am_job(raw: dict) -> str:
    return next(j["id"] for j in raw["instance"]["jobs"] if j["kind"] == "AM")


@pytest.mark.parametrize("name", ["problem_mill_prep.json", "problem_printing.json", "problem_blank.json"])
def test_the_rule_replans_from_the_snapshot_feasibly(name):
    _, _, ci, _, snap = _state(_raw(name))
    plan = dispatch_plan(ci, spt, snapshot=snap)
    assert check_schedule(ci, plan.assignments, snapshot=snap, breaks=plan.breaks) == []


def test_id_map_names_each_mes_step_by_its_instance_operations():
    raw = _raw("problem_mill_prep.json")
    _, _, ci, ids, _ = _state(raw)
    am = _am_job(raw)
    c1 = f"{am}:1"
    assert ids.ops[f"job:{am}:AM_PREP"] == ((f"R:{am}", "setup"), (f"R:{am}", PRINT))
    assert ids.ops[f"job:{am}:PART_POWDER_REMOVAL"] == ((f"R:{am}", "removal"),)
    assert ids.ops[f"carrier:{c1}:MILL_PREP_SECONDARY"] == ((f"M:{c1}", "setup"), (f"M:{c1}", MILL))
    assert ids.ops[f"carrier:{c1}:SECONDARY_PLATE_REMOVAL"] == ((f"M:{c1}", "removal"),)
    assert ids.ops[f"carrier:{c1}:HEAT_TREATMENT"] == ((f"C:{c1}", "HEAT_TREATMENT"),)
    # every compiled operation belongs to exactly one MES step
    key_of = ids.key_of()
    assert set(key_of) == set(ci.op_keys) and len(key_of) == sum(len(v) for v in ids.ops.values())


def test_a_finished_and_a_running_task_are_frozen():
    raw = _raw("problem_mill_prep.json")
    p, epoch, _, _, snap = _state(raw)
    done = [f for f in snap.frozen if not f.running]
    run = [f for f in snap.frozen if f.running]
    assert len(done) == len(run) == 1 and done[0].op_id == run[0].op_id == "DATA_PREP_SEC_MILL"
    assert (done[0].start, done[0].end) == (580, 600)  # 09:40-10:00 Berlin
    running = next(t for t in p.snapshot.tasks if t.finished_at is None)
    assert run[0].start == 600 and run[0].end == max(at(running.expected_end, epoch), snap.t + 1)
    assert done[0].workers == run[0].workers == (str(p.instance.workers[0].id),)
    assert run[0].share_lengths == (run[0].end - run[0].start,)


def test_a_handed_off_print_freezes_its_setup_done_and_its_run_running():
    raw = _raw("problem_printing.json")
    _, _, _, _, snap = _state(raw)
    am = _am_job(raw)
    f = _frozen(snap)
    setup, main = f[f"R:{am}", "setup"], f[f"R:{am}", PRINT]
    assert (setup.start, setup.end, setup.running) == (625, 645, False)
    assert (main.start, main.end, main.running) == (645, 645 + 3000, True)  # the entered 3000 minutes
    assert setup.machine == main.machine == _task(raw, ":AM_PREP")["equipment_id"]
    assert setup.workers and main.workers == ()  # the print runs unattended
    assert (f"R:{am}", "removal") not in f


def test_a_print_still_being_set_up_freezes_only_the_setup():
    raw = _raw("problem_printing.json")
    t = _task(raw, ":AM_PREP")
    t["handoff_at"], t["expected_end"] = None, None
    t["expected_attended_end"] = raw["as_of"]  # already due: the setup runs until t + 1 at least
    _, _, _, _, snap = _state(raw)
    am = _am_job(raw)
    f = _frozen(snap)
    assert f[f"R:{am}", "setup"].running and f[f"R:{am}", "setup"].end == snap.t + 1
    assert (f"R:{am}", PRINT) not in f


def test_a_finished_print_freezes_setup_and_run_as_done():
    raw = _raw("problem_printing.json")
    t = _task(raw, ":AM_PREP")
    end = datetime.fromisoformat(t["handoff_at"]) + timedelta(minutes=30)
    t["finished_at"] = end.isoformat()
    _, epoch, _, _, snap = _state(raw)
    am = _am_job(raw)
    f = _frozen(snap)
    assert not f[f"R:{am}", "setup"].running and not f[f"R:{am}", PRINT].running
    assert f[f"R:{am}", PRINT].end == at(end, epoch)


def test_a_done_step_without_a_start_is_rejected():
    raw = _raw("problem_printing.json")
    raw["snapshot"]["tasks"] = [t for t in raw["snapshot"]["tasks"] if not t["key"].endswith(":DATA_PREP_SEC_MILL")]
    with pytest.raises(MappingError, match="no start time"):
        _state(raw)


def test_a_started_task_without_a_worker_is_rejected():
    raw = _raw("problem_mill_prep.json")
    raw["snapshot"]["tasks"][0]["worker_id"] = None
    with pytest.raises(MappingError, match="without a worker"):
        _state(raw)


def test_a_worker_outside_the_instance_is_rejected():
    raw = _raw("problem_mill_prep.json")
    raw["snapshot"]["tasks"][0]["worker_id"] = str(uuid4())
    with pytest.raises(MappingError, match="not in the instance"):
        _state(raw)


def test_a_task_on_a_machine_its_operation_cannot_use_is_rejected():
    raw = _raw("problem_printing.json")
    mill = next(m["id"] for m in raw["instance"]["machines"] if m["equipment_type"] == "MILL")
    _task(raw, ":AM_PREP")["equipment_id"] = mill
    with pytest.raises(MappingError, match="cannot run on"):
        _state(raw)


def test_a_task_finished_in_the_minute_it_started_lasts_one_minute():
    """Found by the end-to-end run (2.4): start and finish within one minute gave start == end."""
    raw = _raw("problem_mill_prep.json")
    done = next(t for t in raw["snapshot"]["tasks"] if t["finished_at"])
    done["finished_at"] = done["started_at"]
    _, _, ci, _, snap = _state(raw)
    f = next(x for x in snap.frozen if not x.running)
    assert f.end == f.start + 1
    plan = dispatch_plan(ci, spt, snapshot=snap)
    assert check_schedule(ci, plan.assignments, snapshot=snap, breaks=plan.breaks) == []


def test_a_print_handed_off_in_the_minute_it_started_keeps_a_one_minute_setup():
    raw = _raw("problem_printing.json")
    t = _task(raw, ":AM_PREP")
    t["handoff_at"] = t["started_at"]
    _, _, _, _, snap = _state(raw)
    am = _am_job(raw)
    f = _frozen(snap)
    assert f[f"R:{am}", "setup"].end == f[f"R:{am}", "setup"].start + 1 == f[f"R:{am}", PRINT].start


def test_a_step_started_in_the_minute_its_predecessor_finished_keeps_the_order():
    """Found by the end-to-end run (2.4): whole minutes put the print's start before its mill data prep's end."""
    raw = _raw("problem_printing.json")
    preps = [t for t in raw["snapshot"]["tasks"] if t["key"].endswith(":DATA_PREP_SEC_MILL")]
    last = max(preps, key=lambda t: t["finished_at"])
    last["started_at"] = last["finished_at"]  # a one-minute floor stretches it past the print's start
    am = _task(raw, ":AM_PREP")
    am["started_at"] = am["handoff_at"] = last["finished_at"]
    _, _, ci, _, snap = _state(raw)
    f = _frozen(snap)
    run = f"R:{_am_job(raw)}"
    prep_end = max(x.end for x in snap.frozen if x.op_id == "DATA_PREP_SEC_MILL")
    assert f[run, "setup"].start >= prep_end and f[run, PRINT].start >= f[run, "setup"].end
    assert all(x.end <= snap.t for x in snap.frozen if not x.running)
    plan = dispatch_plan(ci, spt, snapshot=snap)
    assert check_schedule(ci, plan.assignments, snapshot=snap, breaks=plan.breaks) == []


def test_one_mes_task_over_two_orders_is_split_into_consecutive_pieces():
    """Found in 3.1c: one DATA_PREP_PRIMARY over both orders' primary parts froze its worker twice at once (C12)."""
    raw = _raw("problem_blank.json")
    _, _, _, _, snap = _state(raw)
    preps = sorted((f.start, f.end, f.workers) for f in snap.frozen if f.op_id == "DATA_PREP_PRIMARY")
    assert len(preps) == 2
    (s1, e1, w1), (s2, e2, w2) = preps
    assert s1 < e1 == s2 < e2 and w1 == w2
    task = next(t for t in raw["snapshot"]["tasks"] if t["key"].endswith(":DATA_PREP_PRIMARY"))
    assert (
        e2 - s1
        == at(datetime.fromisoformat(task["finished_at"]), epoch_of(datetime.fromisoformat(raw["as_of"]), BERLIN)) - s1
    )
