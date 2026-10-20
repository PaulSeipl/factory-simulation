from pathlib import Path

import pytest

from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model
from simulation.model.instance import Instance

FIXTURES = Path(__file__).parent / "fixtures"
BRANDIMARTE = sorted((Path(__file__).parents[1] / "data" / "benchmarks" / "brandimarte").glob("*.fjs"))


def test_toy_fjs_equals_toy_json(toy_path):
    # toy JSON uses the loader's step names (op1, ...), so whole-model equality applies
    assert load_fjs(FIXTURES / "toy-3x3.fjs") == read_model(toy_path, Instance)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", r"unexpected end of file, expected number of jobs"),
        ("1 2", r"unexpected end of file, expected header"),
        ("1 2 1\n2  1 1 3", r"unexpected end of file, expected machine count of job 1, op 2"),
        ("1 2 1\n1  1 1", r"unexpected end of file, expected duration of job 1, op 1"),
        ("1 2 1\n1  1 3 4", r"job 1, op 1: machine index 3 outside 1\.\.2"),
        ("1 2 1\n1  1 0 4", r"job 1, op 1: machine index 0 outside 1\.\.2"),
        ("1 2 1\n1  2 1 4 1 5", r"job 1, op 1: machine 1 listed twice"),
        ("1 2 1\n1  1 1 4  7", r"unexpected trailing token '7' after job 1"),
        ("1 2 1\n1  1 1 x", r"expected integer duration of job 1, op 1, got 'x'"),
    ],
)
def test_malformed_fjs_rejected(tmp_path, content, message):
    path = tmp_path / "bad.fjs"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_fjs(path)


def test_zero_duration_rejected_by_model(tmp_path):
    path = tmp_path / "zero.fjs"
    path.write_text("1 1 1\n1  1 1 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="greater than 0"):
        load_fjs(path)


@pytest.mark.parametrize("path", BRANDIMARTE, ids=lambda p: p.stem)
def test_brandimarte_matches_file_lines(path):
    # independent of the token stream: catches a short job line borrowing tokens from the next
    header, *job_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    n_jobs, n_machines = map(int, header.split()[:2])
    inst = load_fjs(path)
    assert len(inst.orders) == n_jobs == len(job_lines)
    assert len(inst.machines) == n_machines
    for order, line in zip(inst.orders, job_lines, strict=True):
        assert len(order.operations) == int(line.split()[0])
