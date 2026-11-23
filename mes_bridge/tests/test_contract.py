"""The bridge's hand-written MES models against the checked-in copy of the MES `openapi.json` (decision 15).

Update `tests/data/openapi.json` on purpose (copy of the MES `frontend/openapi.json`), then the models.
Compared per field: name, required, and the type after dropping titles, descriptions, defaults and
constraints; an MES enum counts as a string (the bridge keeps enums as plain strings).
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from mes_bridge import api

DATA = Path(__file__).parent / "data"
SCHEMAS = json.loads((DATA / "openapi.json").read_text(encoding="utf-8"))["components"]["schemas"]
REQUESTS = {api.ScheduleIn, api.ScheduleStepIn, api.ScheduleBreakIn}  # validation mode, the rest are responses
MODELS = [m for m in vars(api).values() if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == api.__name__
          and not m.__name__.startswith("_")]


def _norm(s: dict, defs: dict) -> object:
    if "$ref" in s:
        name = s["$ref"].rsplit("/", 1)[1]
        return {"type": "string"} if "enum" in defs.get(name, {}) else {"ref": name}
    if "anyOf" in s:
        return {"anyOf": sorted((_norm(x, defs) for x in s["anyOf"]), key=json.dumps)}
    if "enum" in s:
        return {"type": "string"}
    out: dict = {k: s[k] for k in ("type", "format") if k in s}
    if "items" in s:
        out["items"] = _norm(s["items"], defs)
    return out


def _shape(schema: dict, defs: dict) -> tuple[dict, set[str]]:
    return {k: _norm(v, defs) for k, v in schema.get("properties", {}).items()}, set(schema.get("required", []))


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_model_matches_the_mes_schema(model):
    assert model.__name__ in SCHEMAS, f"{model.__name__} is not in the MES openapi.json"
    mine = model.model_json_schema(
        mode="validation" if model in REQUESTS else "serialization", ref_template="#/components/schemas/{model}"
    )
    assert _shape(mine, mine.get("$defs", {})) == _shape(SCHEMAS[model.__name__], SCHEMAS)


def test_every_problem_and_schedule_schema_has_a_model():
    """A new MES schema of these endpoints needs a model (or a deliberate exception here)."""
    unused = {"ScheduleVariantEnum"}
    wanted = {n for n in SCHEMAS if n.startswith(("Problem", "Schedule"))} - unused
    assert wanted == {m.__name__ for m in MODELS}


@pytest.mark.parametrize("name", ["problem_mill_prep.json", "problem_printing.json"])
def test_recorded_responses_parse(name):
    p = api.ProblemOut.model_validate_json((DATA / name).read_text(encoding="utf-8"))
    assert p.instance.carriers and p.instance.params and p.instance.operations


def test_the_detector_finds_a_drift():
    """Self-test: a field the copy lacks, and a type that differs, are both caught."""
    s = api.ProblemJobOut.model_json_schema(mode="serialization")
    mine = _shape(s, {})
    theirs = _shape(SCHEMAS["ProblemJobOut"], SCHEMAS)
    assert mine == theirs
    extra = dict(theirs[0], cost={"type": "number"})
    assert (extra, theirs[1]) != mine
    retyped = dict(theirs[0], kind={"type": "integer"})
    assert (retyped, theirs[1]) != mine
