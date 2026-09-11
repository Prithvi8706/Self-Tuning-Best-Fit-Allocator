import random

import pytest

from framework.laws import (Constant, Exponential, Geometric, LogNormal, LogUniform, Mixture, Uniform,
                            choice, parse_law)

LAWS = [Constant(7), Uniform(3, 9), Geometric(16), Geometric(1), LogNormal(24, 0.05),
        LogUniform(1, 4096), Exponential(10), choice([40, 100, 140], [49, 49, 2]),
        Mixture([(0.9, Geometric(16)), (0.1, Uniform(33, 1024))])]


@pytest.mark.parametrize("law", LAWS, ids=lambda law: law.describe())
def test_samples_are_positive_integers_and_deterministic(law):
    def draws():
        rng = random.Random(5)
        return [law.sample(rng) for _ in range(2000)]
    a = draws()
    assert a == draws()
    assert all(isinstance(x, int) and not isinstance(x, bool) and x >= 1 for x in a)


def test_bounded_laws_stay_in_support():
    rng = random.Random(1)
    assert {Uniform(3, 9).sample(rng) for _ in range(3000)} == set(range(3, 10))
    lu = [LogUniform(1, 4096).sample(rng) for _ in range(20000)]
    assert min(lu) == 1 and max(lu) <= 4096 and max(lu) > 3000
    assert {choice([40, 100, 140]).sample(rng) for _ in range(500)} == {40, 100, 140}


def test_geometric_and_exponential_means():
    rng = random.Random(2)
    geo = [Geometric(16).sample(rng) for _ in range(40000)]
    assert 15.5 < sum(geo) / len(geo) < 16.5
    assert all(Geometric(1).sample(rng) == 1 for _ in range(100))
    ex = [Exponential(1000).sample(rng) for _ in range(40000)]
    assert 980 < sum(ex) / len(ex) < 1030                   # 1 + floor(X): mean ≈ mean + 0.5


def test_weighted_choice_frequencies():
    rng = random.Random(3)
    draws = [choice([40, 100, 140], [49, 49, 2]).sample(rng) for _ in range(50000)]
    assert 0.01 < draws.count(140) / len(draws) < 0.03


def test_lognormal_concentrates_around_median():
    rng = random.Random(4)
    draws = [LogNormal(400, 0.02).sample(rng) for _ in range(5000)]
    assert all(360 <= d <= 440 for d in draws)


@pytest.mark.parametrize("spec, described", [
    ("const:5", "const(5)"), ("uniform:1:1024", "uniform(1,1024)"), ("geometric:16", "geometric(16.0)"),
    ("lognormal:24:0.1", "lognormal(24.0,0.1)"), ("loguniform:1:4096", "loguniform(1,4096)"),
    ("exp:1000", "exp(1000.0)"), ("choice:4,6", "mix(1:const(4),1:const(6))"),
    ("weighted:40=49,140=2", "mix(49.0:const(40),2.0:const(140))"),
])
def test_parse_law(spec, described):
    assert parse_law(spec).describe() == described


@pytest.mark.parametrize("spec", ["", "uniform:5", "uniform:9:3", "uniform:0:4", "exp:-1", "geometric:0.5",
                                  "choice:", "weighted:4", "gamma:2", "const:x"])
def test_parse_law_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        parse_law(spec)
