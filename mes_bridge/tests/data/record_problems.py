"""Records the problem responses in this folder. Not run by the bridge's tests.

Copy it into the MES worktree as `backend/tests/api/test_zz_record_problem.py`, run
`uv run pytest tests/api/test_zz_record_problem.py` from `backend/`, delete it again. It builds the state with the
helpers of the MES export tests (`tests/services/test_planning_problem.py`) and writes `GET /planning/problem`
next to this file. `as_of` is the database clock at recording time, the task times use the helpers' fixed NOW
(2026-11-23 09:00 UTC): record later than NOW + 45 minutes, or the print's handoff lies after `as_of`.
"""

import json
from datetime import timedelta
from pathlib import Path

from tests.services.test_planning_problem import NOW, _am, _mill_data_prep, _nest, _planned_order, _secondaries, _task

from app.models.config.hardware import EEquipmentStatus, Mill
from app.models.orders.production import MillJob
from app.models.orders.work_task import TaskPart, WorkTask
from app.schemas.hardware import EquipmentTypeEnum
from app.schemas.process_lookup import PartStatusEnum, PartTypeEnum
from app.schemas.process_lookup import TaskTypeEnum as T
from app.schemas.process_lookup import WorkTaskStatusEnum as S
from app.services.process.seed_routes import seed_routes

OUT = Path(
    r"C:\Users\pauls\code\fidentis\simulation\.claude\worktrees\planner-api-loop-design-e38416\mes_bridge\tests\data"
)


def _mill(db):
    m = Mill(
        equipment_type=EquipmentTypeEnum.MILL,
        name="Problem-Mill",
        manufacturer="imes",
        serial_number="PROB-MILL-1",
        status_id=db.query(EEquipmentStatus).filter_by(status="IDLE").one().id,
        plannable=True,
    )
    db.add(m)
    db.flush()
    return m


def _write(client, name):
    body = client.get("/api/v1/planning/problem").json()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_record(client, db_session, with_task_planning_params, worker):
    seed_routes(db_session)
    am = _am(db_session, plannable=True)
    _mill(db_session)
    a, b = _planned_order(db_session), _planned_order(db_session)
    job = _nest(db_session, [a, b], machine=am, quadrants=["1", "2"])
    # mill prep: a's mill data prep done (its mill job formed), then b's started by the same worker
    _mill_data_prep(db_session, a, worker)
    running = _task(
        db_session,
        T.DATA_PREP_SEC_MILL,
        _secondaries(db_session, b),
        S.IN_PROGRESS,
        worker_id=worker.id,
        started_at=NOW,
    )
    db_session.commit()
    _write(client, "problem_mill_prep.json")

    # printing: b's mill data prep done after a's, then the print set up and handed off (3000 minutes entered,
    # so its end lies after any recording time)
    db_session.query(TaskPart).filter_by(task_id=running.id).delete()
    db_session.query(WorkTask).filter_by(id=running.id).delete()
    db_session.flush()
    _mill_data_prep(db_session, b, worker, finished=NOW + timedelta(minutes=20))
    _task(
        db_session,
        T.AM_PREP,
        _secondaries(db_session, a) + _secondaries(db_session, b),
        S.UNATTENDED,
        job_id=job.id,
        worker_id=worker.id,
        equipment_id=am.id,
        started_at=NOW + timedelta(minutes=25),
        handoff_at=NOW + timedelta(minutes=45),
        est_unattended_minutes=3000,
    )
    db_session.commit()
    _write(client, "problem_printing.json")

    # blank: one worker's DATA_PREP_PRIMARY puts both orders' primary parts on one blank (one mill job)
    blank = MillJob()
    db_session.add(blank)
    db_session.flush()
    primary = [p for o in (a, b) for p in o.order_parts if p.part_type == PartTypeEnum.PRIMARY.value]
    done = _task(
        db_session,
        T.DATA_PREP_PRIMARY,
        primary,
        S.DONE,
        job_id=blank.id,
        worker_id=worker.id,
        started_at=NOW + timedelta(minutes=45),
        finished_at=NOW + timedelta(minutes=75),
    )
    for tp in db_session.query(TaskPart).filter_by(task_id=done.id):
        tp.resulting_status = PartStatusEnum.DATA_PREPPED.value
    for part in primary:
        part.current_status = PartStatusEnum.DATA_PREPPED.value
    db_session.commit()
    _write(client, "problem_blank.json")
