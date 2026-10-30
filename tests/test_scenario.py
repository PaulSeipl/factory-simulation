from statistics import mean

import pytest

from simulation.io.brandimarte_loader import load_fjs
from simulation.io.json_loader import read_model, write_model
from simulation.model.compiled import compile_instance
from simulation.sim.scenario import Scenario, factors_by_index, realized_duration, sample_scenario

MK10 = load_fjs("data/benchmarks/brandimarte/BrandimarteMk10.fjs")


def test_same_seed_same_factors_other_seed_other_factors():
    assert sample_scenario(MK10, 0.2, seed=1) == sample_scenario(MK10, 0.2, seed=1)
    assert sample_scenario(MK10, 0.2, seed=1) != sample_scenario(MK10, 0.2, seed=2)


def test_one_factor_per_operation_and_sigma_zero_gives_exactly_one():
    s = sample_scenario(MK10, 0.0, seed=1)
    assert len(s.factors) == sum(len(o.operations) for o in MK10.orders)
    assert {f.factor for f in s.factors} == {1.0}


def test_factors_have_mean_one():
    # 2400 draws with sigma 0.3: standard error of the mean ~ 0.006, tolerance ~ 5 standard errors
    factors = [f.factor for seed in range(10) for f in sample_scenario(MK10, 0.3, seed).factors]
    assert mean(factors) == pytest.approx(1.0, abs=0.03)


@pytest.mark.parametrize(("planned", "factor", "expected"), [(5, 1.0, 5), (5, 1.1, 6), (5, 0.9, 5), (4, 0.625, 3),
                                                             (2, 1.25, 3), (3, 0.1, 1)])
def test_realized_duration_rounds_halves_up_and_is_at_least_one(planned, factor, expected):
    # 4 * 0.625 = 2.5 -> 3 and 2 * 1.25 = 2.5 -> 3 (round() would give 2 for both)
    assert realized_duration(planned, factor) == expected


def test_factors_by_index_checks_the_scenario_against_the_instance():
    ci = compile_instance(MK10)
    s = sample_scenario(MK10, 0.2, seed=1)
    assert len(factors_by_index(ci, s)) == ci.n_ops
    with pytest.raises(ValueError, match="not 'BrandimarteMk10'"):
        factors_by_index(ci, s.model_copy(update={"instance": "other"}))
    with pytest.raises(ValueError, match="no factor for"):
        factors_by_index(ci, s.model_copy(update={"factors": s.factors[:-1]}))
    with pytest.raises(ValueError, match="duplicate"):
        factors_by_index(ci, s.model_copy(update={"factors": (*s.factors, s.factors[0])}))


def test_scenario_round_trips_as_json(tmp_path):
    s = sample_scenario(MK10, 0.2, seed=1, q=0.5, max_early=3, max_late=4)
    write_model(s, tmp_path / "scenario.json")
    assert read_model(tmp_path / "scenario.json", Scenario) == s


def test_start_offsets_do_not_change_the_factors_of_a_seed():
    plain = sample_scenario(MK10, 0.2, seed=3)
    with_offsets = sample_scenario(MK10, 0.2, seed=3, q=0.4, max_early=5, max_late=8)
    assert [f.factor for f in plain.factors] == [f.factor for f in with_offsets.factors]
    assert {f.start_offset for f in plain.factors} == {0}


def test_start_offsets_respect_q_and_range():
    offsets = [f.start_offset for seed in range(10)
               for f in sample_scenario(MK10, 0.2, seed, q=0.4, max_early=5, max_late=8).factors]
    assert min(offsets) >= -5 and max(offsets) <= 8
    # P(offset == 0) = q + (1 - q) / 14, since 0 is also one of the 14 uniform values; 2400 draws
    assert offsets.count(0) / len(offsets) == pytest.approx(0.4 + 0.6 / 14, abs=0.04)
