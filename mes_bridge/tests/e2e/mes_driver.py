"""End-to-end test, MES side (task 2.4). Not run by the bridge's tests: it needs a running MES and a running bridge.

Runs in the MES backend's environment (it uses the MES's own services, like the MES's `scripts/seed_intern_order.py`
whose helpers it reuses), from `backend/`, against a scratch database (`POSTGRESQL_DB_NAME`), never the dev database:

    uv run python <this file> seed [--both]
    uv run python <this file> act <anchor.json of the running bridge>
    uv run python <this file> demo

`demo` seeds the showcase of `mes_bridge/DEMO.md`: five telescope orders (n primary crowns, one secondary bridge),
each on its own print: two in the pipeline (urgent and relaxed), three arrived today; one printer and one mill; Timo, Lukas and Quirin as the only workers
(08:00-17:30, overtime until 19:30). `second-printer` adds a printer (the scenario's machine-down step).

`seed` creates an intern order of two telescopes and drives it through pre-planning and DATA_PREP_SECONDARY (with
the plate quadrant), so it has arrived for the scheduler; it makes every machine plannable. `act` performs three
real task transitions through the MES's services (start the mill data prep, finish it, start and hand off the
print with an entered run of 2000 min, far longer than planned, so the repair must move its successors). With
`SCHEDULER_URL` and `SCHEDULER_EVENTS_TOKEN` set, every commit posts its event to the bridge (the
MES's after-commit listener); after each transition `act` waits until the bridge has run a step (its
`anchor.json` is rewritten) and reports the publications so far. Exit code 0: every transition woke the bridge,
and at least one led to a new publication. The thesis repair keeps planned gaps,
so a step started early or finished early moves nothing by itself; the overrun of the print does. The procedure is in `mes_bridge/PLAN.md` (task 2.4).
"""

import sys
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path

from scripts.seed_intern_order import Fixtures, _complete_extra, _drive_preplanning
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.initial_data import seed_intern_customer
from app.models.config.hardware import AmSystem, EEquipmentStatus, Equipment, Mill
from app.schemas.hardware import EquipmentTypeEnum
from app.models.config.worker import Worker
from app.models.orders.order import OrderPart
from app.models.orders.planning import PlanningSetting
from app.models.orders.schedule import Schedule
from app.models.orders.work_task import WorkTask
from app.schemas.lookup import OrderPriorityEnum
from app.schemas.order import CompositionEnum, InternOrderCreate
from app.schemas.process_engine import AcceptTaskInput, AmJobSubmit, CompleteTaskInput, HandoffTaskInput, TaskPartResult
from app.schemas.process_lookup import TaskOutcomeEnum, TaskTypeEnum
from app.services.intern_order import create_intern_order
from app.services.order_planning import plan_order, sign_ready_for_data_check
from app.services.planning import scheduler_events  # noqa: F401  (the after-commit listener, as in app/main.py)
from app.services.process import ready_work
from app.services.process import task as task_service
from app.services.process.seed_routes import seed_routes

T = TaskTypeEnum
DEMO_WORKERS = {"Timo", "Lukas", "Quirin"}


def _proposable(db, order_id, task_type):
    rw = ready_work.compute_ready_work(db, order_id=order_id)
    return next((pt for pt in rw.proposable if pt.task_type == task_type), None)


def _accept_start(db, fx, pt):
    job_id = pt.subject_id if pt.subject_type.value == "JOB" else None
    task = task_service.accept(
        db,
        AcceptTaskInput(
            task_type=pt.task_type,
            subject_type=pt.subject_type,
            subject_id=pt.subject_id,
            order_part_ids=pt.order_part_ids,
            resulting_status=pt.resulting_status,
            job_id=job_id,
        ),
    )
    return task_service.start(db, task.id, worker_id=fx.worker.id)


def _ok(part_ids):
    return [TaskPartResult(order_part_id=p, outcome=TaskOutcomeEnum.OK) for p in part_ids]


def machines(db) -> None:
    """One plannable printer and one plannable mill (idempotent); the dev seed has no equipment."""
    idle = db.scalar(select(EEquipmentStatus.id).where(EEquipmentStatus.status == "IDLE"))
    have = {e.equipment_type for e in db.execute(select(Equipment)).scalars()}
    if EquipmentTypeEnum.AM_SYSTEM.value not in have:
        db.add(
            AmSystem(
                equipment_type=EquipmentTypeEnum.AM_SYSTEM,
                name="E2E-AM",
                manufacturer="E2E",
                serial_number="E2E-AM-1",
                status_id=idle,
                max_build_plate_slots=4,
                plannable=True,
            )
        )
    if EquipmentTypeEnum.MILL.value not in have:
        db.add(
            Mill(
                equipment_type=EquipmentTypeEnum.MILL,
                name="E2E-Mill",
                manufacturer="E2E",
                serial_number="E2E-MILL-1",
                status_id=idle,
                plannable=True,
            )
        )
    for e in db.execute(select(Equipment)).scalars():
        e.plannable = True
    db.commit()


def seed(
    composition: CompositionEnum = CompositionEnum.SECONDARY_ONLY,
    *,
    teeth: tuple[int, ...] = (11, 12),
    print_no: str = "E2E1",
    due_in_days: int | None = None,
    priority: OrderPriorityEnum = OrderPriorityEnum.NORMAL,
    name: str | None = None,
    arrive: bool = True,
) -> None:
    """An intern order driven through pre-planning (the three general tasks: data check, design, geometry) and, with
    `arrive`, planned (parts and routes) and through DATA_PREP_SECONDARY (the nesting on the plate), which is its
    arrival for the scheduler. Without `arrive` it stays READY_FOR_PLANNING (the Planning page's list)."""
    with SessionLocal() as db:
        seed_intern_customer(db)
        seed_routes(db)
        machines(db)
        order = create_intern_order(
            db,
            obj_in=InternOrderCreate(
                name=name,
                tooth_list=list(teeth),
                composition=composition,
                is_multimat=False,
                primary_target=None,
                secondary_target=None,
                priority=priority,
            ),
        )
        if due_in_days is not None:
            order.due_date = date.today() + timedelta(days=due_in_days)
            db.commit()
        sign_ready_for_data_check(db, order)
        fx = Fixtures(db)
        _drive_preplanning(db, order, fx)
        db.refresh(order)
        if not arrive:  # READY_FOR_PLANNING: on the Planning page's list, not planned, so not nested either
            print(f"seeded order {order.short_id} ({order.id}), ready for planning")
            return
        plan_order(db, order)
        db.refresh(order)
        for _ in range(20):  # the route up to the arrival (DATA_PREP_SECONDARY), with the plate quadrant
            pt = _proposable(db, order.id, T.DATA_PREP_SECONDARY)
            if pt is None:
                rw = ready_work.compute_ready_work(db, order_id=order.id)
                if not rw.proposable:
                    raise RuntimeError("DATA_PREP_SECONDARY never became proposable")
                pt = rw.proposable[0]
                if pt.task_type != T.DATA_PREP_SECONDARY:
                    raise RuntimeError(f"unexpected step before the arrival: {pt.task_type}")
            task = _accept_start(db, fx, pt)
            extra = dict(_complete_extra(T.DATA_PREP_SECONDARY.value, fx))
            # the MES seed script's own print number ("SEED-xxxxxx") overflows am_job.print_job_no (VARCHAR(4))
            extra["am_job"] = AmJobSubmit(
                print_job_no=print_no, print_version=1, est_non_precious_powder_kg=Decimal("0.020")
            )
            extra["part_quadrant_assignments"] = dict.fromkeys(pt.order_part_ids, "1")
            task_service.complete(db, task.id, CompleteTaskInput(results=_ok(pt.order_part_ids), **extra))
            break
        print(f"seeded order {order.short_id} ({order.id}), arrived")


def demo() -> None:
    """The showcase scene (`mes_bridge/DEMO.md`). Every order is telescope work: n primary crowns (milled) and one
    secondary bridge over the same n teeth (printed), so both lanes and the QM join show.
    - in the pipeline: the three general tasks done, ready for planning (and so for nesting), not in the plan yet:
      one urgent (due tomorrow, HIGH), one relaxed (due in 8 days, LOW)
    - arrived today (nested), NORMAL, due in 3, 4 and 5 days: 4, 6 and 3 telescopes, each on its own print"""
    seed(CompositionEnum.BOTH, teeth=(14, 13, 23), due_in_days=1,
         priority=OrderPriorityEnum.HIGH, name="Pipeline, urgent", arrive=False)  # fmt: skip
    seed(CompositionEnum.BOTH, teeth=(33, 43), due_in_days=8,
         priority=OrderPriorityEnum.LOW, name="Pipeline, relaxed", arrive=False)  # fmt: skip
    seed(CompositionEnum.BOTH, teeth=(13, 12, 22, 23), print_no="D004", due_in_days=3, name="4 telescopes")
    seed(CompositionEnum.BOTH, teeth=(15, 14, 13, 23, 24, 25), print_no="D006", due_in_days=4, name="6 telescopes")
    seed(CompositionEnum.BOTH, teeth=(34, 33, 43), print_no="D003", due_in_days=5, name="3 telescopes")
    with SessionLocal() as db:
        # the factory's day: 08:00-17:30 (8.5 h + the 1 h break), overtime until 19:30
        setting = db.get(PlanningSetting, 1)
        setting.day_start = dt_time(8, 0)
        if hasattr(setting, "max_overtime_minutes"):  # the MES has the setting from 2026-11-23 on
            setting.max_overtime_minutes = 120
        # three workers plan: Timo, Lukas, Quirin; the others are retired (the planning export skips them)
        now = datetime.now(UTC)
        for w in db.scalars(select(Worker)):
            if w.first_name in DEMO_WORKERS:
                w.daily_minutes = 510
            elif w.retired_at is None:
                w.retired_at = now
        # one printer, one mill, named for the demo
        for e in db.scalars(select(Equipment)):
            e.name = {"E2E-AM": "Printer 1", "E2E-Mill": "Mill 1"}.get(e.name, e.name)
        db.commit()


def second_printer() -> None:
    """A second printer, so a machine going down has somewhere to move the prints (`demo_scenario.py`, step 8)."""
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(AmSystem)) < 2:
            idle = db.scalar(select(EEquipmentStatus.id).where(EEquipmentStatus.status == "IDLE"))
            db.add(
                AmSystem(
                    equipment_type=EquipmentTypeEnum.AM_SYSTEM,
                    name="Demo-AM-2",
                    manufacturer="Demo",
                    serial_number="DEMO-AM-2",
                    status_id=idle,
                    max_build_plate_slots=4,
                    plannable=True,
                )
            )
            db.commit()


def _wait_for_step(anchor: Path, since: float, timeout: float = 90) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if anchor.exists() and anchor.stat().st_mtime > since:
            return time.time() - t0
        time.sleep(0.5)
    raise RuntimeError(f"the bridge ran no step within {timeout} s")


def act(anchor: Path) -> int:
    with SessionLocal() as db:
        fx = Fixtures(db)
        order_id = db.scalar(select(OrderPart.order_id).order_by(OrderPart.created_at.desc()).limit(1))
        publications = lambda: db.scalar(select(func.count()).select_from(Schedule))  # noqa: E731
        _wait_for_step(anchor, 0)  # the bridge's first step after its start
        counts = [publications()]
        steps = []

        def transition(name, do):
            since = anchor.stat().st_mtime
            do()
            waited = _wait_for_step(anchor, since)
            db.expire_all()
            counts.append(publications())
            steps.append((name, waited, counts[-1]))
            print(f"{name}: bridge stepped after {waited:.1f} s, publications {counts[-1]}")

        pt = _proposable(db, order_id, T.DATA_PREP_SEC_MILL)
        task = None

        def start_mill_prep():
            nonlocal task
            task = _accept_start(db, fx, pt)

        def finish_mill_prep():
            extra = _complete_extra(T.DATA_PREP_SEC_MILL.value, fx)
            task_service.complete(db, task.id, CompleteTaskInput(results=_ok(pt.order_part_ids), **extra))

        def hand_off_print():
            am = _proposable(db, order_id, T.AM_PREP)
            started = _accept_start(db, fx, am)
            plates = dict.fromkeys(am.order_part_ids, fx.build_plate.component_id)
            task_service.handoff(
                db,
                started.id,
                HandoffTaskInput(
                    results=_ok(am.order_part_ids), part_plate_assignments=plates, est_unattended_minutes=2000
                ),
            )

        transition("start mill data prep", start_mill_prep)
        transition("finish mill data prep", finish_mill_prep)
        transition("start and hand off the print", hand_off_print)
        db.expire_all()
        running = db.scalars(select(WorkTask).where(WorkTask.task_type == T.AM_PREP.value)).all()
        print(f"print task status: {[t.status for t in running]}; publications {counts}")
        ok = len(steps) == 3 and counts[-1] > counts[0]
        print("E2E OK" if ok else "E2E FAILED: no new publication")
        return 0 if ok else 1


def nest(db, fx, order_ids, print_no: str):
    """One nesting (DATA_PREP_SECONDARY) putting the secondary parts of `order_ids` on one print, plate i per order."""
    pts = [_proposable(db, o, T.DATA_PREP_SECONDARY) for o in order_ids]
    if any(pt is None for pt in pts):
        raise RuntimeError("DATA_PREP_SECONDARY is not proposable for every order")
    parts = [p for pt in pts for p in pt.order_part_ids]
    task = _accept_start(db, fx, pts[0].model_copy(update={"order_part_ids": parts}))
    extra = dict(_complete_extra(T.DATA_PREP_SECONDARY.value, fx))
    extra["am_job"] = AmJobSubmit(print_job_no=print_no, print_version=1, est_non_precious_powder_kg=Decimal("0.020"))
    extra["part_quadrant_assignments"] = {p: str(i) for i, pt in enumerate(pts, start=1) for p in pt.order_part_ids}
    task_service.complete(db, task.id, CompleteTaskInput(results=_ok(parts), **extra))


def record_nesting(out: Path) -> None:
    """Recordings for task 7.4 (`tests/data/problem_before_nesting.json`, `..._after_nesting.json`): three orders
    planned in the planned nesting flow (no plates yet), then two of them nested onto one print."""
    from app.services.planning import problem as problem_service  # noqa: PLC0415

    ids = []
    for teeth, due in (((13, 12, 22), 2), ((34, 33), 3), ((15, 14), 5)):
        seed(CompositionEnum.BOTH, teeth=teeth, due_in_days=due, arrive=False)
    with SessionLocal() as db:
        row = db.get(PlanningSetting, 1) or PlanningSetting(id=1)
        row.nesting_flow = "PLANNED"
        db.add(row)
        db.commit()
        from app.models.orders.order import ProductionOrder  # noqa: PLC0415

        for order in db.scalars(select(ProductionOrder).order_by(ProductionOrder.due_date)):
            plan_order(db, order)
            ids.append(order.id)

        def record(name):
            db.expire_all()
            now = db.scalar(select(func.now()))
            p = problem_service.build_problem(db, now=now)
            (out / name).write_text(p.model_dump_json(indent=1), encoding="utf-8")
            print(f"recorded {name}: {len(p.instance.operations)} operations")

        record("problem_before_nesting.json")
        nest(db, Fixtures(db), ids[:2], "N001")
        record("problem_after_nesting.json")


if __name__ == "__main__":
    if sys.argv[1:2] == ["record-nesting"]:
        record_nesting(Path(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:2] == ["seed"]:
        seed(CompositionEnum.BOTH if "--both" in sys.argv else CompositionEnum.SECONDARY_ONLY)
    elif sys.argv[1:2] == ["demo"]:
        demo()
    elif sys.argv[1:2] == ["second-printer"]:
        second_printer()
    elif sys.argv[1:2] == ["machines"]:
        with SessionLocal() as session:
            machines(session)
    elif sys.argv[1:2] == ["act"]:
        sys.exit(act(Path(sys.argv[2])))
    else:
        print(__doc__)
        sys.exit(2)
