"""Workload family registry for the ARBF-V1 benchmark.

Parameters were fixed a priori on 2026-09-12, before any benchmark run, from the
family descriptions agreed in the design phase. They must not be changed after
evaluation results are seen (frozen spec §19).

Sizes are in allocation units (16-byte granules, frozen spec §4). Lifetimes are
in ticks of the trace generator. Roles follow frozen spec §18:
  P        predicted effect (primary H1 tests)
  boundary predicted effect -> 0 (trend only)
  N        predicted ≈ Best Fit (equivalence check)
  X        risk / exploratory
"""
import random
from typing import Callable, Dict, List, NamedTuple, Tuple

from framework.laws import (Exponential, Geometric, Law, LogNormal, LogUniform, Mixture, Uniform,
                            choice)

K_SIZES = 8                     # size-set cardinality for F5-style workloads
ZIPF_WEIGHTS = [1 / k for k in range(1, K_SIZES + 1)]   # Zipf(1) over the set, in draw order
EXP1000 = Exponential(1000)     # default lifetime law
BURST_ENTER = 0.001             # F6: P(normal -> burst) per allocation (mean normal run 1000)
BURST_EXIT = 0.02               # F6: P(burst -> normal) per allocation (mean burst 50)
BURST_LIFE = Exponential(20)    # F6: short lifetimes inside a burst
W_ARBF = 738                    # used only to set F7 phase lengths to W/2 and 10W


class Process:
    """Per-trace source of (size, lifetime) pairs, built once per trace from its RNG."""

    def draw(self, tick: int, rng: random.Random) -> Tuple[int, int]:
        raise NotImplementedError


class Static(Process):
    def __init__(self, size_law: Law, life_law: Law):
        self.size_law, self.life_law = size_law, life_law

    def draw(self, tick, rng):
        return self.size_law.sample(rng), self.life_law.sample(rng)


class Classes(Process):
    """Size and lifetime drawn jointly from one of several (weight, size law, lifetime law) classes."""

    def __init__(self, classes: List[Tuple[float, Law, Law]]):
        self.weights = [w for w, _, _ in classes]
        self.pairs = [(s, l) for _, s, l in classes]

    def draw(self, tick, rng):
        size_law, life_law = rng.choices(self.pairs, weights=self.weights)[0]
        return size_law.sample(rng), life_law.sample(rng)


def zipf_size_set(rng: random.Random) -> Tuple[List[int], Law]:
    """K distinct sizes from U{1..1024} with Zipf(1) frequencies (rank = draw order)."""
    sizes = rng.sample(range(1, 1025), K_SIZES)
    return sizes, choice(sizes, ZIPF_WEIGHTS)


class Bursty(Process):
    """F5 process interrupted by bursts of one size with short lifetimes.

    Two-state Markov chain stepped once per allocation: NORMAL -> BURST with
    probability BURST_ENTER (burst size drawn uniformly from the F5 size set),
    BURST -> NORMAL with probability BURST_EXIT.
    """

    def __init__(self, rng: random.Random):
        self.sizes, self.size_law = zipf_size_set(rng)
        self.burst_size = None

    def draw(self, tick, rng):
        if self.burst_size is None:
            if rng.random() < BURST_ENTER:
                self.burst_size = rng.choice(self.sizes)
        elif rng.random() < BURST_EXIT:
            self.burst_size = None
        if self.burst_size is None:
            return self.size_law.sample(rng), EXP1000.sample(rng)
        return self.burst_size, BURST_LIFE.sample(rng)


class Phased(Process):
    """A fresh F5 size set for every phase of `phase_len` ticks; lifetimes Exp(1000)."""

    def __init__(self, phase_len: int):
        self.phase_len = phase_len
        self.phase = -1
        self.size_law: Law = None

    def draw(self, tick, rng):
        phase = tick // self.phase_len
        if phase != self.phase:
            self.phase = phase
            _, self.size_law = zipf_size_set(rng)
        return self.size_law.sample(rng), EXP1000.sample(rng)


class Family(NamedTuple):
    name: str
    role: str
    description: str
    build: Callable[[random.Random], Process]


def _static(size_law: Law, life_law: Law) -> Callable[[random.Random], Process]:
    return lambda rng: Static(size_law, life_law)


def _zipf(life_law: Law) -> Callable[[random.Random], Process]:
    return lambda rng: Static(zipf_size_set(rng)[1], life_law)


def _bimodal(sigma: float) -> Family:
    role = "P" if sigma <= 0.10 else "boundary"
    law = Mixture([(0.5, LogNormal(24, sigma)), (0.5, LogNormal(400, sigma))])
    return Family(f"F4-s{sigma:.2f}", role,
                  f"bimodal: 50% lognormal(24,{sigma}), 50% lognormal(400,{sigma}); lifetimes exp(1000)",
                  _static(law, EXP1000))


def _phased(phase_len: int) -> Family:
    return Family(f"F7-L{phase_len}", "X",
                  f"phase-changing: new K={K_SIZES} Zipf(1) size set from U{{1..1024}} every "
                  f"{phase_len} ticks; lifetimes exp(1000)",
                  lambda rng: Phased(phase_len))


_FAMILY_LIST = [
    Family("F1", "N", "uniform: U{1..1024}; lifetimes exp(1000)", _static(Uniform(1, 1024), EXP1000)),
    Family("F2", "N", "small-object dominant: 90% geometric(16), 10% U{33..1024}; lifetimes exp(1000)",
           _static(Mixture([(0.9, Geometric(16)), (0.1, Uniform(33, 1024))]), EXP1000)),
    Family("F3", "N", "large-object dominant: 90% U{512..4096}, 10% U{1..64}; lifetimes exp(1000)",
           _static(Mixture([(0.9, Uniform(512, 4096)), (0.1, Uniform(1, 64))]), EXP1000)),
    *[_bimodal(s) for s in (0.02, 0.05, 0.10, 0.20, 0.40)],
    Family("F5", "P", f"repetitive: K={K_SIZES} sizes from U{{1..1024}} per seed, Zipf(1); "
                      "lifetimes exp(1000)", _zipf(EXP1000)),
    Family("F6", "P", f"bursty: F5 plus Markov bursts (enter {BURST_ENTER}, exit {BURST_EXIT} per "
                      "allocation) of one F5 size with lifetimes exp(20)", lambda rng: Bursty(rng)),
    _phased(W_ARBF // 2),
    _phased(10 * W_ARBF),
    Family("F8", "X", "high churn: F5 sizes; lifetimes 90% exp(10), 10% exp(10000)",
           _zipf(Mixture([(0.9, Exponential(10)), (0.1, Exponential(10000))]))),
    Family("F9", "N", "low churn: F5 sizes; lifetimes exp(20000)", _zipf(Exponential(20000))),
    Family("F10", "N", "high entropy: sizes loguniform(1,4096); lifetimes loguniform(1,10000)",
           _static(LogUniform(1, 4096), LogUniform(1, 10000))),
    Family("F11", "X", "fragmentation pressure: 49.5% small U{1..16} long-lived exp(20000), "
                       "49.5% large U{256..1024} short-lived exp(100), 1% huge U{2048..4096} exp(100)",
           lambda rng: Classes([(0.495, Uniform(1, 16), Exponential(20000)),
                                (0.495, Uniform(256, 1024), Exponential(100)),
                                (0.01, Uniform(2048, 4096), Exponential(100))])),
    Family("F12", "X", "adversarial rare-large: 49% size 40, 49% size 100, 2% size 140; "
                       "lifetimes exp(1000)",
           _static(choice([40, 100, 140], [49, 49, 2]), EXP1000)),
]

FAMILIES: Dict[str, Family] = {f.name: f for f in _FAMILY_LIST}


def get_family(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError:
        raise ValueError(f"unknown workload {name!r}; known: {', '.join(FAMILIES)}") from None


def custom_family(size_law: Law, life_law: Law) -> Family:
    return Family("custom", "custom", f"custom: sizes {size_law.describe()}; lifetimes {life_law.describe()}",
                  _static(size_law, life_law))
