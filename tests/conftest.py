import json
from pathlib import Path

import pytest

DATA = Path(__file__).parents[1] / "data"


@pytest.fixture
def toy_path() -> Path:
    return DATA / "instances" / "toy-3x3.json"


@pytest.fixture
def toy_data(toy_path) -> dict:
    """Fresh, mutable copy of the toy instance as a plain dict."""
    return json.loads(toy_path.read_text(encoding="utf-8"))
