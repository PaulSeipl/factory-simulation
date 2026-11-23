"""A machine that is DOWN or DECOMMISSIONED is no option of a step (instance._options)."""

import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fake_mes import FakeMes

from mes_bridge.api import ProblemOut
from mes_bridge.client import MesClient
from mes_bridge.factory import MesFactory
from mes_bridge.instance import build_instance, epoch_of
from mes_bridge.state import build_snapshot, group_started, id_map, out_of_service
from simulation.model.compiled import compile_instance

DATA = Path(__file__).parent / "data"
BERLIN = ZoneInfo("Europe/Berlin")
M2 = str(uuid4())


def _raw(name: str, *, second: bool = True) -> dict:
    """A recording; with `second`, a second printer every print may use."""
    raw = json.loads((DATA / name).read_text(encoding="utf-8"))
    inst = raw["instance"]
    if second:
        am = next(m for m in inst["machines"] if m["equipment_type"] == "AM_SYSTEM")
        inst["machines"].append({**am, "id": M2, "name": "AM 2"})
        for o in inst["operations"]:
            if o["task_type"] == "AM_PREP":
                o["machine_options"].append(M2)
    return raw


def _printer(raw: dict) -> str:
    return next(m["id"] for m in raw["instance"]["machines"] if m["equipment_type"] == "AM_SYSTEM")


def _set_status(raw: dict, machine: str, status: str | None) -> None:
    next(m for m in raw["instance"]["machines"] if m["id"] == machine)["status"] = status


def _print_options(raw: dict) -> set[str]:
    p = ProblemOut.model_validate(raw)
    inst = build_instance(p, epoch=epoch_of(p.as_of, BERLIN))
    return {m for step in inst.carrier_steps.values() for m in step.options if m in {_printer(raw), M2}}


def test_a_down_machine_is_dropped_from_the_options_of_a_step_not_started():
    raw = _raw("problem_mill_prep.json")
    first = _printer(raw)
    assert _print_options(raw) == {first, M2}
    _set_status(raw, first, "DOWN")
    assert _print_options(raw) == {M2}


def test_a_decommissioned_machine_is_dropped_too():
    raw = _raw("problem_mill_prep.json")
    _set_status(raw, M2, "DECOMMISSIONED")
    assert _print_options(raw) == {_printer(raw)}


@pytest.mark.parametrize("status", ["IDLE", "RUNNING", None])
def test_a_machine_in_service_stays_an_option(status):
    raw = _raw("problem_mill_prep.json")
    _set_status(raw, _printer(raw), status)
    assert _print_options(raw) == {_printer(raw), M2}


def test_the_only_machine_down_keeps_the_options_and_warns(caplog):
    raw = _raw("problem_mill_prep.json", second=False)
    only = _printer(raw)
    _set_status(raw, only, "DOWN")
    with caplog.at_level(logging.WARNING, logger="mes_bridge.instance"):
        assert _print_options(raw) == {only}
    assert any("down or decommissioned" in r.message for r in caplog.records)


def test_a_started_print_on_a_machine_now_down_still_builds_the_snapshot():
    raw = _raw("problem_printing.json")
    running = next(t for t in raw["snapshot"]["tasks"] if t["key"].endswith(":AM_PREP"))["equipment_id"]
    _set_status(raw, running, "DOWN")
    p = ProblemOut.model_validate(raw)
    epoch = epoch_of(p.as_of, BERLIN)
    ci = compile_instance(build_instance(p, epoch=epoch))
    snap = build_snapshot(p, ci, id_map(p, ci), epoch=epoch)
    assert running in {f.machine for f in snap.frozen}


def test_a_machine_going_down_is_a_complete_rescheduling():
    raw = _raw("problem_printing.json")
    inst = raw["instance"]
    mill = next(m for m in inst["machines"] if m["equipment_type"] == "MILL")
    mill2 = {**mill, "id": str(uuid4()), "name": "Mill 2"}
    inst["machines"].append(mill2)
    for o in inst["operations"]:
        if mill["id"] in o["machine_options"]:
            o["machine_options"].append(mill2["id"])
    fake = FakeMes(raw)
    client = MesClient(fake)
    client.login("scheduler", "pw")
    as_of = datetime.fromisoformat(raw["as_of"])
    factory = MesFactory(client, epoch=epoch_of(as_of, BERLIN), clock=lambda: as_of)
    assert factory.refresh() is True  # the first
    assert factory.refresh() is False  # nothing changed
    _set_status(raw, mill["id"], "DOWN")
    assert factory.refresh() is True
    assert factory.refresh() is False


@pytest.mark.parametrize("name", ["problem_printing.json", "problem_mill_prep.json", "problem_blank.json"])
def test_a_machine_down_takes_no_new_work_but_keeps_what_started(name):
    """state.out_of_service: every operation not started (nor in a run with a started one) loses a DOWN machine when
    another option is left; a started run keeps its machine (its facts). Each machine of the recording in turn."""
    for machine in [m["id"] for m in _raw(name, second=False)["instance"]["machines"]]:
        raw = _raw(name)
        _set_status(raw, machine, "DOWN")
        p = ProblemOut.model_validate(raw)
        epoch = epoch_of(p.as_of, BERLIN)
        ci = compile_instance(build_instance(p, epoch=epoch))
        snap = build_snapshot(p, ci, id_map(p, ci), epoch=epoch)
        started = {(f.order_id, f.op_id) for f in snap.frozen}
        out = out_of_service(ci, p, started)
        if machine not in ci.machine_index:
            assert out is ci
            continue
        down = ci.machine_index[machine]
        started_idx = {ci.op_index[k] for k in started}
        group_of = {o: g for g in ci.machine_groups for o in g}
        for o, opts in enumerate(out.options):
            group = group_of.get(o, (o,))
            if group_started(group, started_idx):
                assert opts == ci.options[o]
            elif all(any(m != down for m, _ in ci.options[g]) for g in group):
                assert down not in {m for m, _ in opts}
            else:
                assert opts == ci.options[o]  # nothing else left: kept


def test_a_new_break_window_is_a_complete_rescheduling():
    """A planning setting (break window, length) changes the calendar; a repair would keep the old breaks."""
    raw = _raw("problem_printing.json", second=False)
    client = MesClient(FakeMes(raw))
    client.login("scheduler", "pw")
    as_of = datetime.fromisoformat(raw["as_of"])
    factory = MesFactory(client, epoch=epoch_of(as_of, BERLIN), clock=lambda: as_of)
    assert factory.refresh() is True  # the first
    assert factory.refresh() is False
    raw["instance"]["calendar"].update(break_earliest="11:30:00", break_latest="13:00:00", break_minutes=30)
    assert factory.refresh() is True
    assert factory.refresh() is False
