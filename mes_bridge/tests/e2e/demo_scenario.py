"""The showcase of `mes_bridge/DEMO.md`, checked end to end over the MES's HTTP API. Never the dev database.

Runs in the MES backend's environment, from `backend/`:

    uv run python <this file> [--keep]

It creates the demo database `mes_demo_scenario` (`demo_db.py setup`), starts this branch's MES on 127.0.0.1:8091 and
the bridge on 127.0.0.1:8766 (CP-SAT, `demo_cpsat.json`, both variants), then walks the showcase as a user would,
each step through the HTTP API, and checks what the plan shows afterwards:

 1. first plan: both variants served (ONLINE), every open step from the scheduler, one break per worker and day,
    no worker's attended step over their break
 2. an assignment: BOUND follows it within seconds (a pin), FREE keeps its own choice
 3. clearing it: BOUND re-solves
 4. a new break window (planning settings): re-solved, every break inside the new window
 5. a worker starts the first planned step: it shows as started (MES fact), the plan stays consistent
 6. they finish it
 7. the print is started and handed off with a run of 2000 min, far longer than planned: its successors move
 8. a printer goes DOWN: nothing is planned on it any more
 9. the bridge stops: after the staleness setting (1 min here) the plan falls back to the fill (OFFLINE)

Prints PASS / FAIL per step; exit code 0 when all pass. `--keep` leaves the MES, the bridge and the database
running for a look in the browser (stop with Ctrl+C, then `demo_db.py drop mes_demo_scenario`).
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent.parent  # mes_bridge/
DB = "mes_demo_scenario"
os.environ["POSTGRESQL_DB_NAME"] = DB  # before the app's settings load: every lookup below reads the demo database

from app.core.db import SessionLocal  # noqa: E402
from app.models.config.hardware import AmSystem, EEquipmentStatus  # noqa: E402
from scripts.seed_intern_order import Fixtures  # noqa: E402

API = "http://127.0.0.1:8091/api/v1"
TZ = ZoneInfo("Europe/Berlin")
RESULTS: list[tuple[str, bool, str]] = []
STARTED = {"RUNNING", "UNATTENDED"}  # a step with a task (PlanStepStatusEnum)


# ---------------------------------------------------------------- HTTP


class Mes:
    def __init__(self):
        self.token = None

    def call(self, method, path, body=None):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body, default=str).encode() if body is not None else None
        req = urllib.request.Request(API + path, data, h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path}: {e.code} {e.read()[:500]!r}") from None

    def login(self, user="admin", password="admin"):
        self.token = self.call("POST", "/auth/login", {"username": user, "password": password})["access_token"]

    def plan(self, variant="BOUND"):
        now = datetime.now(UTC)
        frm, to = (now - timedelta(days=1)).isoformat(), (now + timedelta(days=14)).isoformat()
        q = urllib.parse.urlencode({"from": frm, "to": to, "variant": variant})
        return self.call("GET", f"/planning/plan?{q}")


def wait_for(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = cond()
        if out:
            return out, time.time() - t0
        time.sleep(1)
    raise TimeoutError(f"{what} not within {timeout} s")


def wait_solved(mes, variant, before, timeout=60):
    p, waited = wait_for(
        lambda: (p := mes.plan(variant))["scheduler_solved_at"] not in (None, before) and p, timeout, f"{variant} solve"
    )
    return p, waited


def wait_woke(state, since, timeout=60):
    """The bridge ran a step (its BOUND anchor was rewritten): it saw the event, whether or not the plan changed."""
    anchor = state / "BOUND" / "anchor.json"
    _, waited = wait_for(lambda: anchor.exists() and anchor.stat().st_mtime > since, timeout, "a bridge step")
    return waited


def mtime(state):
    anchor = state / "BOUND" / "anchor.json"
    return anchor.stat().st_mtime if anchor.exists() else 0


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)


# ---------------------------------------------------------------- plan checks


def ts(s):
    return datetime.fromisoformat(s)


def break_clashes(plan):
    """Attended steps of a worker that overlap one of their breaks."""
    out = []
    for b in plan["breaks"]:
        b0, b1 = ts(b["start"]), ts(b["end"])
        for s in plan["steps"]:
            if s["worker_id"] != b["worker_id"]:
                continue
            s0, s1 = ts(s["start"]), ts(s.get("attended_end") or s["end"])
            if s0 < b1 and b0 < s1:
                out.append((s["key"], b["start"]))
    return out


def breaks_in(plan, earliest, latest):
    bad = []
    for b in plan["breaks"]:
        local = ts(b["start"]).astimezone(TZ).time()
        if not earliest <= local <= latest:
            bad.append(b["start"])
    return bad


def step(plan, key):
    return next((s for s in plan["steps"] if s["key"] == key), None)


# ---------------------------------------------------------------- processes


def start_servers(env):
    mes_log = open(HERE / "scenario_mes.log", "w")  # noqa: SIM115
    mes = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8091"],
        env=env, stdout=mes_log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    m = Mes()
    wait_for(lambda: _up(m), 60, "the MES")
    return mes


def start_bridge(env, state):
    log = open(HERE / "scenario_bridge.log", "w")  # noqa: SIM115
    shutil.rmtree(state, ignore_errors=True)  # a fresh start: an old anchor would be resumed
    # the bridge's own interpreter, not `uv run`: on Windows terminating `uv` leaves its child running
    python = BRIDGE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return subprocess.Popen(
        [str(python), "-m", "mes_bridge.runner", "--url",
         "http://127.0.0.1:8091", "--port", "8766", "--state-dir", str(state), "--config",
         str(HERE / "demo_cpsat.json")],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip


def _up(m):
    try:
        m.call("GET", "/openapi.json")
        return True
    except Exception:
        return False


def secrets_env():
    from demo_db import SECRETS  # noqa: PLC0415

    env = dict(os.environ)
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        k, v = line.removeprefix("$env:").split(" = ", 1)
        env[k] = v.strip('"')
    return env


# ---------------------------------------------------------------- the scenario


def scenario(mes, env, bridge_state):
    # 1 first plan
    b, waited = wait_for(lambda: (p := mes.plan("BOUND"))["scheduler"] == "ONLINE" and p, 120, "first BOUND plan")
    f, _ = wait_for(lambda: (p := mes.plan("FREE"))["scheduler"] == "ONLINE" and p, 120, "first FREE plan")
    open_steps = [s for s in b["steps"] if s["status"] not in STARTED]
    check("1 first plan: both variants ONLINE", b["scheduler"] == f["scheduler"] == "ONLINE", f"after {waited:.0f} s")
    srcs = {s["source"] for s in open_steps}
    check("1 every open step from the scheduler", srcs == {"SCHEDULER"}, f"{len(open_steps)} steps, sources {srcs}")
    workers = {s["worker_id"] for s in b["steps"] if s["worker_id"]}
    days = {ts(x["start"]).astimezone(TZ).date() for x in b["breaks"]}
    per = {(x["worker_id"], ts(x["start"]).astimezone(TZ).date()) for x in b["breaks"]}
    check("1 breaks: at most one per worker and day", len(per) == len(b["breaks"]) and b["breaks"],
          f"{len(b['breaks'])} breaks, {len(workers)} planned workers, {len(days)} days")  # fmt: skip
    check("1 no attended step over its worker's break", not break_clashes(b), str(break_clashes(b)[:3]))
    check("1 FREE: no attended step over a break", not break_clashes(f), str(break_clashes(f)[:3]))

    # 2 an assignment pins BOUND, FREE stays
    s0 = next(s for s in b["steps"] if s["task_type"] == "DATA_PREP_SEC_MILL" and len(s["order_ids"]) == 1)
    order = s0["order_ids"][0]
    target = sorted(workers - {s0["worker_id"]})[0]
    free_before = step(f, s0["key"])["worker_id"]
    mes.call("PUT", f"/order/orders/{order}/assignments",
             {"items": [{"task_type": "DATA_PREP_SEC_MILL", "worker_id": target}]})  # fmt: skip
    b2, waited = wait_solved(mes, "BOUND", b["scheduler_solved_at"], 30)
    check("2 assignment: BOUND re-solved within 30 s", True, f"{waited:.0f} s")
    check("2 BOUND follows the pin", step(b2, s0["key"])["worker_id"] == target)
    f2 = mes.plan("FREE")
    check("2 FREE ignores the pin", step(f2, s0["key"])["worker_id"] == free_before,
          "free plan keeps its own worker, so Team plan can suggest it")  # fmt: skip

    # 3 clearing it
    mes.call("PUT", f"/order/orders/{order}/assignments", {"items": []})
    b3, waited = wait_solved(mes, "BOUND", b2["scheduler_solved_at"], 30)
    check("3 cleared assignment: BOUND re-solved", True, f"{waited:.0f} s")

    # 4 break window
    settings = mes.call("GET", "/planning/settings")
    mes.call("PUT", "/planning/settings", {"day_start": settings["day_start"], "break_earliest": "12:30:00",
                                           "break_latest": "13:30:00", "break_minutes": 45})  # fmt: skip
    b4, waited = wait_solved(mes, "BOUND", b3["scheduler_solved_at"], 60)
    from datetime import time as t  # noqa: PLC0415

    bad = breaks_in(b4, t(12, 30), t(13, 30))
    check(
        "4 break window 12:30-13:30 / 45 min (12:00 outside): re-solved, breaks inside", not bad, f"{waited:.0f} s, outside {bad[:3]}"
    )
    lens = {(ts(x["end"]) - ts(x["start"])).seconds // 60 for x in b4["breaks"]}
    check("4 breaks last 45 min", lens == {45}, str(lens))
    check("4 no attended step over a break", not break_clashes(b4), str(break_clashes(b4)[:3]))

    # 5 a worker starts the first planned step (as the worker it is planned for)
    first = min((s for s in b4["steps"] if s["task_type"] == "DATA_PREP_SEC_MILL"), key=lambda s: s["start"])
    oid = first["order_ids"][0]
    rw = mes.call("GET", f"/process/ready-work?order_id={oid}")
    pt = next(p for p in rw["proposable"] if p["task_type"] == "DATA_PREP_SEC_MILL")
    task = mes.call("POST", "/process/tasks", {k: pt[k] for k in
                    ("task_type", "subject_type", "subject_id", "order_part_ids", "resulting_status")})  # fmt: skip
    since = mtime(bridge_state)
    mes.call("POST", f"/process/tasks/{task['id']}/start", {"worker_id": first["worker_id"]})
    waited = wait_woke(bridge_state, since)
    time.sleep(3)  # a publication, if any, follows the step
    b5 = mes.plan("BOUND")
    st = step(b5, first["key"])
    check("5 started step woke the bridge", True, f"{waited:.0f} s (started early: the repair moves nothing)")
    started_now = st is not None and abs(ts(st["start"]) - datetime.now(UTC)) < timedelta(minutes=5)
    check("5 started step shows as the MES fact (RUNNING, started now)",
          st is not None and st["status"] == "RUNNING" and st["task_id"] == task["id"] and started_now,
          f"status {st and st['status']}, start {st and st['start']}")  # fmt: skip
    check("5 no attended step over a break", not break_clashes(b5), str(break_clashes(b5)[:3]))

    # 6 they finish it
    parts = pt["order_part_ids"]
    since = mtime(bridge_state)
    mes.call("POST", f"/process/tasks/{task['id']}/complete",
             {"results": [{"order_part_id": p, "outcome": "OK"} for p in parts], "mill_job": {}})  # fmt: skip
    waited = wait_woke(bridge_state, since)
    time.sleep(3)
    b6 = mes.plan("BOUND")
    check("6 finished step left the plan", step(b6, first["key"]) is None, f"{waited:.0f} s")

    # 7 the print overruns
    rw = mes.call("GET", f"/process/ready-work?order_id={oid}")
    am = next(p for p in rw["proposable"] if p["task_type"] == "AM_PREP")
    am_key = next(s["key"] for s in b6["steps"] if s["task_type"] == "AM_PREP" and oid in s["order_ids"])
    succ_before = max(ts(s["end"]) for s in b6["steps"] if oid in s["order_ids"])
    planned_am = step(b6, am_key)
    with SessionLocal() as db:
        plate = Fixtures(db).build_plate.component_id
        db.commit()
    body = {k: am[k] for k in ("task_type", "subject_type", "subject_id", "order_part_ids", "resulting_status")}
    body["job_id"] = am["subject_id"] if am["subject_type"] == "JOB" else None
    if planned_am and planned_am.get("equipment_id"):
        body["equipment_id"] = planned_am["equipment_id"]
    task = mes.call("POST", "/process/tasks", body)
    mes.call(
        "POST", f"/process/tasks/{task['id']}/start", {"worker_id": planned_am["worker_id"] if planned_am else None}
    )
    before = mes.plan("BOUND")["scheduler_solved_at"]
    # one day longer than planned: started now, it ends a day after its planned end
    run = int((ts(planned_am["end"]) - datetime.now(UTC)).total_seconds() // 60) + 1440
    mes.call("POST", f"/process/tasks/{task['id']}/handoff", {
        "results": [{"order_part_id": p, "outcome": "OK"} for p in am["order_part_ids"]],
        "part_plate_assignments": {p: str(plate) for p in am["order_part_ids"]},
        "est_unattended_minutes": run})  # fmt: skip
    b7, waited = wait_solved(mes, "BOUND", before, 60)
    printed = step(b7, am_key)
    print_end = ts(printed["end"]) if printed else datetime.now(UTC) + timedelta(minutes=run)
    after = [s for s in b7["steps"] if oid in s["order_ids"] and s["key"] != am_key
             and s["process_area"] == planned_am["process_area"] and s["status"] not in STARTED]  # fmt: skip
    early = [s["key"] for s in after if ts(s["start"]) < print_end - timedelta(minutes=1)]
    succ_after = max(ts(s["end"]) for s in b7["steps"] if oid in s["order_ids"])
    check("7 overrun print (+1 day): republished, the print ends at the entered run", printed is not None
          and abs(print_end - (datetime.now(UTC) + timedelta(minutes=run))) < timedelta(minutes=5),
          f"{waited:.0f} s, print end {print_end.astimezone(TZ):%a %H:%M}")  # fmt: skip
    check("7 its successors start after the print", not early and after,
          f"{len(after)} successors, order finish {succ_before.astimezone(TZ):%a %H:%M} -> "
          f"{succ_after.astimezone(TZ):%a %H:%M}, too early {early[:3]}")  # fmt: skip
    check("7 no attended step over a break", not break_clashes(b7), str(break_clashes(b7)[:3]))

    # 8 a printer down
    with SessionLocal() as db:
        down = db.scalar(select(EEquipmentStatus.id).where(EEquipmentStatus.status == "DOWN"))
        printers = [str(x.id) for x in db.scalars(select(AmSystem))]
    # a job with a started step is bound to its printer (the running print, its plate's powder removal): it stays
    started_jobs = {s["job_id"] for s in b7["steps"] if s["status"] in STARTED and s["job_id"]}
    movable = lambda p: [s for s in p["steps"] if s["job_id"] not in started_jobs and s["status"] not in STARTED]  # noqa: E731
    used = [s["equipment_id"] for s in movable(b7) if s["task_type"] == "AM_PREP" and s["equipment_id"] in printers]
    victim = used[0] if used else printers[-1]
    mes.call("POST", f"/config/equipment/{victim}/status", {"status_id": down, "reason": "demo"})
    b8, waited = wait_solved(mes, "BOUND", b7["scheduler_solved_at"], 60)
    left = [s["key"] for s in movable(b8) if s["equipment_id"] == victim]
    kept = [s["key"] for s in b8["steps"] if s["equipment_id"] == victim and s["job_id"] in started_jobs]
    if left:  # for a look offline: the problem the bridge planned from
        sched = Mes()
        sched.login(os.environ.get("SCHEDULER_USERNAME", "scheduler"), env["MES_SCHEDULER_PASSWORD"])
        (HERE / "scenario_problem.json").write_text(json.dumps(sched.call("GET", "/planning/problem")), "utf-8")
        print("victim", victim, "left", left)
    check("8 printer DOWN: no print that has not started is planned on it", used and not left,
          f"{waited:.0f} s, {len(used)} print(s) moved off; still on it: {left[:3]}; started job kept: {len(kept)}")  # fmt: skip

    # 9 bridge offline
    settings = mes.call("GET", "/planning/settings")
    mes.call("PUT", "/planning/settings", {"day_start": settings["day_start"], "scheduler_stale_minutes": 1})
    return b8


def _free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main():
    keep = "--keep" in sys.argv
    busy = [p for p in (8091, 8766) if not _free(p)]
    if busy:
        sys.exit(f"port(s) {busy} in use: stop the old MES / bridge first")
    sys.path.insert(0, str(HERE))
    from demo_db import drop, setup  # noqa: PLC0415

    setup(DB)
    env = secrets_env()
    env["POSTGRESQL_DB_NAME"] = DB
    state = HERE / "scenario_state"
    mes_proc = start_servers(env)
    bridge = start_bridge(env, state)
    mes = Mes()
    mes.login()
    try:
        scenario(mes, env, state)
        bridge.terminate()
        bridge.wait(30)
        p, waited = wait_for(lambda: (p := mes.plan("BOUND"))["scheduler"] == "OFFLINE" and p, 150, "OFFLINE")
        check("9 bridge stopped: plan OFFLINE after the staleness setting", True,
              f"{waited:.0f} s, last schedule {p['scheduler_solved_at']}")  # fmt: skip
        srcs = {s["source"] for s in p["steps"]}
        check("9 OFFLINE: the MES fill serves every step", "SCHEDULER" not in srcs, str(srcs))
    except Exception as e:  # noqa: BLE001
        check("scenario aborted", False, f"{type(e).__name__}: {e}")
    finally:
        if keep:
            print("kept running: MES 8091, database", DB, "(bridge stopped in step 9; restart it from DEMO.md)")
            mes_proc.wait()
        bridge.terminate()
        mes_proc.terminate()
        mes_proc.wait(30)
        drop(DB)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} / {len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
