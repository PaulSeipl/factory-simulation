"""End-to-end test, MES side (task 2.4). Not run by the bridge's tests: it needs a running MES and a running bridge.

Runs in the MES backend's environment (it uses the MES's own services, like the MES's `scripts/seed_intern_order.py`
whose helpers it reuses), from `backend/`, against a scratch database (`POSTGRESQL_DB_NAME`), never the dev database:

    uv run python <this file> seed
    uv run python <this file> act <anchor.json of the running bridge>

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
from decimal import Decimal
from pathlib import Path

from scripts.seed_intern_order import Fixtures, _complete_extra, _drive_preplanning
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.initial_data import seed_intern_customer
from app.models.config.hardware import AmSystem, EEquipmentStatus, Equipment, Mill
from app.schemas.hardware import EquipmentTypeEnum
from app.models.orders.order import OrderPart
from app.models.orders.schedule import Schedule
from app.models.orders.work_task import WorkTask
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


def seed() -> None:
    with SessionLocal() as db:
        seed_intern_customer(db)
        seed_routes(db)
        machines(db)
        order = create_intern_order(
            db,
            obj_in=InternOrderCreate(
                tooth_list=[11, 12],
                composition=CompositionEnum.SECONDARY_ONLY,
                is_multimat=False,
                primary_target=None,
                secondary_target=None,
            ),
        )
        sign_ready_for_data_check(db, order)
        fx = Fixtures(db)
        _drive_preplanning(db, order, fx)
        db.refresh(order)
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
                print_job_no="E2E1", print_version=1, est_non_precious_powder_kg=Decimal("0.020")
            )
            extra["part_quadrant_assignments"] = dict.fromkeys(pt.order_part_ids, "1")
            task_service.complete(db, task.id, CompleteTaskInput(results=_ok(pt.order_part_ids), **extra))
            break
        print(f"seeded order {order.short_id} ({order.id}), arrived")


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


if __name__ == "__main__":
    if sys.argv[1:2] == ["seed"]:
        seed()
    elif sys.argv[1:2] == ["machines"]:
        with SessionLocal() as session:
            machines(session)
    elif sys.argv[1:2] == ["act"]:
        sys.exit(act(Path(sys.argv[2])))
    else:
        print(__doc__)
        sys.exit(2)
