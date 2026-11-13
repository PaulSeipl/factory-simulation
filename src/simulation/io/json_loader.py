import csv
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ValidationInfo


def read_model[M: BaseModel](path: str | Path, model: type[M]) -> M:
    """Validate a JSON file; path references in it resolve relative to the file's folder (resolve_reference)."""
    path = Path(path)
    return model.model_validate_json(path.read_text(encoding="utf-8"), context={"dir": path.parent})


def resolve_reference(value, info: ValidationInfo):
    """Field validator (mode="before"): a string is the path of a JSON file holding the field's value, relative to
    the folder of the file being read (e.g. a route shared by generator parameters and experiment configurations)."""
    if not isinstance(value, str):
        return value
    folder = (info.context or {}).get("dir")
    if folder is None:
        raise ValueError(f"{info.field_name}: path reference {value!r} needs read_model (no folder to resolve it)")
    path = Path(folder) / value
    if not path.is_file():
        raise ValueError(f"{info.field_name}: referenced file {path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


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
