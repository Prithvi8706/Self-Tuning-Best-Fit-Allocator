"""Integer-valued random laws for request sizes and object lifetimes.

Every law returns integers >= 1 and draws only from the ``random.Random`` it is
given, so a trace is a pure function of (workload, seed, n_events, alloc_prob).
"""
import math
import random
from typing import List, Optional, Sequence, Tuple


class Law:
    def sample(self, rng: random.Random) -> int:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


def _positive_int(x, what: str) -> int:
    if not isinstance(x, int) or isinstance(x, bool) or x < 1:
        raise ValueError(f"{what} must be an integer >= 1, got {x!r}")
    return x


def _positive(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not x > 0:
        raise ValueError(f"{what} must be > 0, got {x!r}")
    return x


class Constant(Law):
    def __init__(self, value: int):
        self.value = _positive_int(value, "value")

    def sample(self, rng):
        return self.value

    def describe(self):
        return f"const({self.value})"


class Uniform(Law):
    """Discrete uniform on {lo, ..., hi}."""

    def __init__(self, lo: int, hi: int):
        self.lo, self.hi = _positive_int(lo, "lo"), _positive_int(hi, "hi")
        if hi < lo:
            raise ValueError(f"uniform needs lo <= hi, got {lo}, {hi}")

    def sample(self, rng):
        return rng.randint(self.lo, self.hi)

    def describe(self):
        return f"uniform({self.lo},{self.hi})"


class Geometric(Law):
    """Trials up to the first success of Bernoulli(1/mean): support {1, 2, ...}, mean `mean`."""

    def __init__(self, mean: float):
        if _positive(mean, "mean") < 1:
            raise ValueError(f"geometric mean must be >= 1, got {mean!r}")
        self.mean = mean

    def sample(self, rng):
        if self.mean == 1:
            return 1
        u = 1.0 - rng.random()                                   # (0, 1]
        return 1 + int(math.log(u) / math.log(1.0 - 1.0 / self.mean))

    def describe(self):
        return f"geometric({self.mean})"


class LogNormal(Law):
    """round(median · exp(sigma · Z)), Z ~ N(0, 1), floored at 1."""

    def __init__(self, median: float, sigma: float):
        self.median, self.sigma = _positive(median, "median"), _positive(sigma, "sigma")

    def sample(self, rng):
        return max(1, math.floor(self.median * math.exp(self.sigma * rng.gauss(0.0, 1.0)) + 0.5))

    def describe(self):
        return f"lognormal({self.median},{self.sigma})"


class LogUniform(Law):
    """Log-uniform on {lo, ..., hi}: floor(lo · ((hi+1)/lo)^U), U ~ U[0, 1)."""

    def __init__(self, lo: int, hi: int):
        self.lo, self.hi = _positive_int(lo, "lo"), _positive_int(hi, "hi")
        if hi < lo:
            raise ValueError(f"loguniform needs lo <= hi, got {lo}, {hi}")

    def sample(self, rng):
        return min(self.hi, math.floor(self.lo * ((self.hi + 1) / self.lo) ** rng.random()))

    def describe(self):
        return f"loguniform({self.lo},{self.hi})"


class Exponential(Law):
    """1 + floor(X), X ~ Exp(mean)."""

    def __init__(self, mean: float):
        self.mean = _positive(mean, "mean")

    def sample(self, rng):
        return 1 + math.floor(rng.expovariate(1.0 / self.mean))

    def describe(self):
        return f"exp({self.mean})"


class Mixture(Law):
    """Pick a component law with probability proportional to its weight, then sample it."""

    def __init__(self, parts: Sequence[Tuple[float, Law]]):
        if not parts:
            raise ValueError("mixture needs at least one component")
        self._weights = [_positive(w, "weight") for w, _ in parts]
        self._laws = [law for _, law in parts]

    def sample(self, rng):
        return rng.choices(self._laws, weights=self._weights)[0].sample(rng)

    def describe(self):
        return "mix(" + ",".join(f"{w}:{law.describe()}" for w, law in zip(self._weights, self._laws)) + ")"


def choice(values: Sequence[int], weights: Optional[Sequence[float]] = None) -> Mixture:
    weights = [1] * len(values) if weights is None else list(weights)
    if len(weights) != len(values):
        raise ValueError("choice needs one weight per value")
    return Mixture([(w, Constant(v)) for v, w in zip(values, weights)])


def parse_law(spec: str) -> Law:
    """Parse 'const:v', 'uniform:a:b', 'geometric:mean', 'lognormal:median:sigma',
    'loguniform:a:b', 'exp:mean', 'choice:v1,v2,...' or 'weighted:v1=w1,v2=w2,...'."""
    kind, _, rest = spec.partition(":")
    args: List[str] = rest.split(":") if rest else []
    try:
        if kind == "const" and len(args) == 1:
            return Constant(int(args[0]))
        if kind == "uniform" and len(args) == 2:
            return Uniform(int(args[0]), int(args[1]))
        if kind == "geometric" and len(args) == 1:
            return Geometric(float(args[0]))
        if kind == "lognormal" and len(args) == 2:
            return LogNormal(float(args[0]), float(args[1]))
        if kind == "loguniform" and len(args) == 2:
            return LogUniform(int(args[0]), int(args[1]))
        if kind == "exp" and len(args) == 1:
            return Exponential(float(args[0]))
        if kind == "choice" and len(args) == 1:
            return choice([int(v) for v in args[0].split(",")])
        if kind == "weighted" and len(args) == 1:
            pairs = [p.split("=") for p in args[0].split(",")]
            return choice([int(v) for v, _ in pairs], [float(w) for _, w in pairs])
    except ValueError as exc:
        raise ValueError(f"bad law spec {spec!r}: {exc}") from None
    raise ValueError(f"unknown law spec {spec!r}")
