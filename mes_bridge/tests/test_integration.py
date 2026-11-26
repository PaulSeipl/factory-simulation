"""Against a running MES (task 1.6). Skipped unless `MES_IT_URL` and `MES_SCHEDULER_PASSWORD` are set.

Use an MES of this branch with its own database, never the dev database: e.g. a scratch database migrated with
`alembic upgrade head`, `app/initial_data.py`, and the scheduler user from
`scripts/create_user.py --username scheduler --password ... --allow-no-worker`.
"""

import os
from datetime import UTC, datetime

import pytest

from mes_bridge import once
from mes_bridge.client import MesClient, http

URL = os.environ.get("MES_IT_URL")
PASSWORD = os.environ.get("MES_SCHEDULER_PASSWORD")
pytestmark = pytest.mark.skipif(not (URL and PASSWORD), reason="no MES to test against (MES_IT_URL)")


def test_fetch_plan_check_publish_round_trip():
    client = MesClient(http(URL))
    client.login(os.environ.get("MES_SCHEDULER_USERNAME", "scheduler"), PASSWORD)
    outcome = once.run(client, now=datetime.now(UTC))
    assert outcome.violations == [] and outcome.schedule is not None
    (bound,) = [s for s in client.schedules() if s.variant == "BOUND"]
    assert bound.snapshot_as_of == outcome.schedule.snapshot_as_of
    assert [st.key for st in bound.steps] == [st.key for st in outcome.schedule.steps]
