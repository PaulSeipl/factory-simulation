"""The scheduler's state on disk (decision 22): no database, one folder per variant.

- `anchor.json`: the epoch, the anchor (plan of the last complete rescheduling, its time and breaks), the plan last
  published and the id of that publication. Written atomically after every step.
- `decisions.jsonl`: every REPAIR / REPLAN record of the planning tool, one JSON object per line, with the wall time.

On restart (`resume`) the bridge continues from `anchor.json` only if the MES's current schedule of the variant is the
publication recorded there and the epoch is still the one of this week; otherwise it starts with a complete
rescheduling (a mismatch means someone else published, the MES lost the row, or time moved on).
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from simulation.control.rescheduling import Anchor
from simulation.model.schedule import Assignment, Break

from mes_bridge.api import ScheduleOut


@dataclass(frozen=True)
class Saved:
    epoch: datetime
    anchor: Anchor
    plan: list[Assignment]  # the plan last published
    breaks: tuple[Break, ...]
    publication: UUID | None  # id of that publication in the MES


def _plan(xs) -> list[dict]:
    return [x.model_dump() for x in xs]


class Store:
    def __init__(self, root: Path, variant: str):
        self.dir = Path(root) / variant
        self.dir.mkdir(parents=True, exist_ok=True)
        self.anchor_file, self.decisions_file = self.dir / "anchor.json", self.dir / "decisions.jsonl"

    def save(self, saved: Saved) -> None:
        body = {
            "epoch": saved.epoch.isoformat(),
            "anchor": {"t": saved.anchor.t, "plan": _plan(saved.anchor.plan), "breaks": _plan(saved.anchor.breaks)},
            "plan": _plan(saved.plan),
            "breaks": _plan(saved.breaks),
            "publication": None if saved.publication is None else str(saved.publication),
        }
        tmp = self.anchor_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(body), encoding="utf-8")
        os.replace(tmp, self.anchor_file)  # atomic: a crash leaves the old file or the new one

    def load(self) -> Saved | None:
        """The saved state, None if there is none or it cannot be read (then the bridge starts fresh)."""
        try:
            body = json.loads(self.anchor_file.read_text(encoding="utf-8"))
            a = body["anchor"]
            return Saved(
                epoch=datetime.fromisoformat(body["epoch"]),
                anchor=Anchor([Assignment(**x) for x in a["plan"]], a["t"], tuple(Break(**x) for x in a["breaks"])),
                plan=[Assignment(**x) for x in body["plan"]],
                breaks=tuple(Break(**x) for x in body["breaks"]),
                publication=None if body["publication"] is None else UUID(body["publication"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def append_decisions(self, records: list[dict], at: datetime) -> None:
        with self.decisions_file.open("a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps({"at": at.isoformat(), **r}, default=str) + "\n")


def resumable(saved: Saved | None, current: list[ScheduleOut], variant: str, epoch: datetime) -> bool:
    """Decision 22: resume only from the publication the MES still has as current, in the same epoch."""
    if saved is None or saved.publication is None or saved.epoch != epoch:
        return False
    latest = next((s for s in current if s.variant == variant), None)
    return latest is not None and latest.id == saved.publication
