"""The thesis package never imports the bridge (simulation CLAUDE.md, spec decision 1)."""

import ast
from pathlib import Path

import simulation

SIMULATION_SRC = Path(simulation.__file__).parent


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def imports_bridge(source: str) -> bool:
    return any(m == "mes_bridge" or m.startswith("mes_bridge.") for m in imported_modules(source))


def test_simulation_never_imports_mes_bridge() -> None:
    files = sorted(SIMULATION_SRC.rglob("*.py"))
    assert files, f"no sources found under {SIMULATION_SRC}"
    offenders = [str(f.relative_to(SIMULATION_SRC)) for f in files if imports_bridge(f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_detector_finds_bridge_imports() -> None:
    assert imports_bridge("import mes_bridge")
    assert imports_bridge("from mes_bridge.problem import to_instance")
    assert imports_bridge("def f():\n    import mes_bridge.client as c\n")
    assert not imports_bridge("import mes_bridge_like\nfrom simulation import model")
