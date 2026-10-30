import csv
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel


def read_model[M: BaseModel](path: str | Path, model: type[M]) -> M:
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_model(obj: BaseModel, path: str | Path) -> None:
    Path(path).write_text(obj.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_jsonl(records: Iterable[dict], path: str | Path) -> None:
    """One JSON object per line (event logs)."""
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def write_csv(rows: Iterable[dict], path: str | Path) -> None:
    """Results: one row per dict, columns from the keys of the first row."""
    rows = list(rows)
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
