"""Loader for Brandimarte-style FJSP files (.fjs).

Brandimarte, P. (1993). Routing and scheduling in a flexible job shop by tabu search.
Annals of Operations Research 41, 157-183. https://doi.org/10.1007/BF02023073

Format: header "n_jobs n_machines avg_machines_per_op", then per job
"n_ops" followed per operation by "k (machine duration){k}"; machines are 1-based.
Operations of a job form a chain.
"""

from pathlib import Path

from simulation.model.instance import Instance


def load_fjs(path: str | Path) -> Instance:
    path = Path(path)
    # token stream instead of fixed columns/lines: robust against extra whitespace
    tokens = iter(path.read_text(encoding="utf-8").split())

    def next_int(what: str) -> int:
        tok = next(tokens, None)
        if tok is None:
            raise ValueError(f"{path.name}: unexpected end of file, expected {what}")
        try:
            return int(tok)
        except ValueError:
            raise ValueError(f"{path.name}: expected integer {what}, got {tok!r}") from None

    n_jobs = next_int("number of jobs")
    n_machines = next_int("number of machines")
    if next(tokens, None) is None:  # avg machines per op: informative only
        raise ValueError(f"{path.name}: unexpected end of file, expected header")

    orders = []
    for j in range(1, n_jobs + 1):
        operations = []
        for pos in range(1, next_int(f"number of operations of job {j}") + 1):
            where = f"job {j}, op {pos}"
            options = {}
            for _ in range(next_int(f"machine count of {where}")):
                m = next_int(f"machine index of {where}")
                if not 1 <= m <= n_machines:
                    raise ValueError(
                        f"{path.name}: {where}: machine index {m} outside 1..{n_machines}"
                    )
                if f"M{m}" in options:
                    raise ValueError(f"{path.name}: {where}: machine {m} listed twice")
                options[f"M{m}"] = next_int(f"duration of {where}")
            operations.append(
                {
                    "id": str(pos),
                    "step": f"op{pos}",  # Brandimarte has no step types
                    "options": options,
                    "predecessors": [str(pos - 1)] if pos > 1 else [],
                }
            )
        orders.append({"id": f"J{j}", "release": 0, "operations": operations})

    if (extra := next(tokens, None)) is not None:
        raise ValueError(f"{path.name}: unexpected trailing token {extra!r} after job {n_jobs}")

    return Instance.model_validate(
        {
            "schema_version": "0.2",
            "name": path.stem,
            "machines": [f"M{i}" for i in range(1, n_machines + 1)],
            "orders": orders,
        }
    )
