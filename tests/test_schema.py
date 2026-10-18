"""Guards the stored JSON Schema of Instance against silent model changes.

Regenerate with: uv run python tests/test_schema.py
If only a pydantic upgrade changed the output (data format unchanged), rerun with --force.
"""

import json
import sys
from pathlib import Path
from typing import get_args

from simulation.model.instance import Instance

VERSION = get_args(Instance.model_fields["schema_version"].annotation)[0]
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / f"instance-{VERSION}.json"
REGENERATE = "uv run python tests/test_schema.py"


def stored_schema() -> dict | None:
    if not SCHEMA_PATH.exists():
        return None
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_stored_schema_matches_model():
    stored = stored_schema()
    assert stored is not None, f"{SCHEMA_PATH.name} missing (new schema version?). Run: {REGENERATE}"
    # compare parsed JSON, not text: immune to whitespace and CRLF conversion
    assert stored == Instance.model_json_schema(), (
        f"Instance model changed but {SCHEMA_PATH.name} did not. "
        f"Bump schema_version in instance.py, then run: {REGENERATE} "
        "(if only a pydantic upgrade changed the output, rerun with --force instead)"
    )


if __name__ == "__main__":
    schema = Instance.model_json_schema()
    stored = stored_schema()
    # refuse to rewrite a published version: a changed model needs a new version
    if stored is not None and stored != schema and "--force" not in sys.argv:
        sys.exit(f"{SCHEMA_PATH.name} exists and differs. Bump schema_version, or pass --force.")
    SCHEMA_PATH.parent.mkdir(exist_ok=True)
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
