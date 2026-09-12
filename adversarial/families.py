"""Adversarial workload families (not part of the frozen registry in framework/workloads.py).

Every family plugs into the frozen tick-model generator (framework.generator), so
traces are pure functions of (family, seed, n_events) and hash-verifiable. Each
family is tagged with the stress category it probes. Parameters were chosen
before any run of this study, from the mechanism each family targets.
"""
import random
from typing import Dict, List, Sequence, Tuple

from framework.laws import (Constant, Exponential, Geometric, Law, LogNormal, LogUniform, Mixture,
                            Uniform, choice)
from framework.workloads import FAMILIES as FROZEN, Classes, Family, Process, Static, zipf_size_set

W = 738                          # ARBF history window; used only to size phases relative to it
EXP1000 = Exponential(1000)
TRANSIENT = Constant(1)          # dies at the next tick: an ALLOC immediately followed by its FREE


class Pareto(Law):
    """Heavy tail: floor(scale · U^(−1/alpha)), U ~ U(0, 1], capped at `cap`."""

    def __init__(self, scale: int, alpha: float, cap: int):
        self.scale, self.alpha, self.cap = scale, alpha, cap

    def sample(self, rng):
        u = 1.0 - rng.random()
        return min(self.cap, max(1, int(self.scale * u ** (-1.0 / self.alpha))))

    def describe(self):
        return f"pareto({self.scale},{self.alpha},cap={self.cap})"


class Schedule(Process):
    """Piecewise process: phases of (length in ticks, process). The last phase persists
    unless `repeat`, in which case the phase list cycles forever."""

    def __init__(self, phases: Sequence[Tuple[int, Process]], repeat: bool = False):
        self.phases = list(phases)
        self.repeat = repeat
        self.period = sum(length for length, _ in self.phases)

    def draw(self, tick, rng):
        t = tick % self.period if self.repeat else tick
        for length, process in self.phases:
            if t < length:
                return process.draw(tick, rng)
            t -= length
        return self.phases[-1][1].draw(tick, rng)


def static(size_law: Law, life_law: Law = EXP1000):
    return lambda rng: Static(size_law, life_law)


def classes(*parts: Tuple[float, Law, Law]):
    return lambda rng: Classes(list(parts))


def shift(first: Law, second: Law, at: int = 10 * W, life: Law = EXP1000):
    """Sudden, permanent distribution change after `at` allocations."""
    return lambda rng: Schedule([(at, Static(first, life)), (1, Static(second, life))])


def alternate_random_sets(period: int):
    """Two per-seed Zipf(1) size sets (as in frozen F5), alternating every `period` ticks."""
    def build(rng):
        _, a = zipf_size_set(rng)
        _, b = zipf_size_set(rng)
        return Schedule([(period, Static(a, EXP1000)), (period, Static(b, EXP1000))], repeat=True)
    return build


def alternate(first: Law, second: Law, period: int):
    return lambda rng: Schedule([(period, Static(first, EXP1000)), (period, Static(second, EXP1000))],
                                repeat=True)


def trap(small: int, medium: int, large: int, p_large: float):
    """Spec counterexample shape: large = medium + small, so a medium placed in a
    `large` hole leaves a residual that exactly fits `small`."""
    half = (1 - p_large) / 2
    return static(choice([small, medium, large], [half, half, p_large]))


_ADVERSARIAL: List[Tuple[str, str, str, object]] = [
    # (name, category, description, build)
    ("shift-up", "distribution change", "{24,40} for 10W ticks, then U{64..512} forever",
     shift(choice([24, 40]), Uniform(64, 512))),
    ("shift-down", "distribution change", "U{64..512} for 10W ticks, then {24,40} forever",
     shift(Uniform(64, 512), choice([24, 40]))),
    ("shift-disjoint", "distribution change", "{40,100} for 10W ticks, then {130,260} forever",
     shift(choice([40, 100]), choice([130, 260]))),
    ("stale-trap", "stale history", "{40,100} for 10W ticks, then {100,140} forever (140 = 100+40)",
     shift(choice([40, 100]), choice([100, 140]))),
    ("poison-50", "stale history", "50% transient size-40 requests (lifetime 1); 50% U{1..1024} exp(1000)",
     classes((0.5, Constant(40), TRANSIENT), (0.5, Uniform(1, 1024), EXP1000))),
    ("poison-90", "stale history", "90% transient size-40 requests (lifetime 1); 10% U{1..1024} exp(1000)",
     classes((0.9, Constant(40), TRANSIENT), (0.1, Uniform(1, 1024), EXP1000))),
    ("poison-trap", "stale history", "60% transient 40s; 38% size 100, 2% size 140, both exp(1000)",
     classes((0.6, Constant(40), TRANSIENT), (0.38, Constant(100), EXP1000), (0.02, Constant(140), EXP1000))),
    ("rand-wide", "random sizes", "sizes loguniform(1,65536); lifetimes exp(1000)",
     static(LogUniform(1, 65536))),
    ("rand-uniform", "random sizes", "sizes U{1..8192}; lifetimes exp(1000)", static(Uniform(1, 8192))),
    ("pareto", "random sizes", "sizes pareto(16, alpha 1.1, cap 65536); lifetimes exp(1000)",
     static(Pareto(16, 1.1, 65536))),
    ("bimodal-rare-1", "bimodal", "99% lognormal(32,0.1), 1% lognormal(2048,0.1); lifetimes exp(1000)",
     static(Mixture([(0.99, LogNormal(32, 0.1)), (0.01, LogNormal(2048, 0.1))]))),
    ("bimodal-rare-5", "bimodal", "95% lognormal(32,0.1), 5% lognormal(2048,0.1); lifetimes exp(1000)",
     static(Mixture([(0.95, LogNormal(32, 0.1)), (0.05, LogNormal(2048, 0.1))]))),
    ("bimodal-const", "bimodal", "50% size 16, 50% size 1000; lifetimes exp(1000)", static(choice([16, 1000]))),
    ("trap-0.5", "bimodal", "{40,100,140} with 140 at 0.5%; lifetimes exp(1000)", trap(40, 100, 140, 0.005)),
    ("trap-5", "bimodal", "{40,100,140} with 140 at 5%; lifetimes exp(1000)", trap(40, 100, 140, 0.05)),
    ("trap-x10", "bimodal", "{400,1000,1400} with 1400 at 2%; lifetimes exp(1000)", trap(400, 1000, 1400, 0.02)),
    ("tiny", "tiny fragments", "sizes U{1..4}; lifetimes exp(1000)", static(Uniform(1, 4))),
    ("tiny-geo", "tiny fragments", "sizes geometric(2); lifetimes exp(1000)", static(Geometric(2))),
    ("tiny-mixed", "tiny fragments", "90% U{1..3}, 10% U{8..16}; lifetimes exp(1000)",
     static(Mixture([(0.9, Uniform(1, 3)), (0.1, Uniform(8, 16))]))),
    ("huge", "very large blocks", "sizes loguniform(1024,131072); lifetimes exp(20)",
     static(LogUniform(1024, 131072), Exponential(20))),
    ("huge-few", "very large blocks", "sizes U{10000..50000}; lifetimes exp(5)",
     static(Uniform(10000, 50000), Exponential(5))),
    ("rep-2", "repetitive", "sizes {100,164} 50/50; lifetimes exp(1000)", static(choice([100, 164]))),
    ("rep-3", "repetitive", "sizes {40,100,140} equal weights; lifetimes exp(1000)",
     static(choice([40, 100, 140]))),
    ("rep-adjacent", "repetitive", "sizes U{100..107}; lifetimes exp(1000)", static(Uniform(100, 107))),
    ("churn", "rapid alloc/free", "sizes U{1..1024}; lifetimes exp(3)", static(Uniform(1, 1024), Exponential(3))),
    ("churn-mixed", "rapid alloc/free", "sizes U{1..1024}; lifetimes 95% exp(2), 5% exp(50000)",
     static(Uniform(1, 1024), Mixture([(0.95, Exponential(2)), (0.05, Exponential(50000))]))),
    ("longlived-mixed", "long-lived", "sizes U{1..1024}; lifetimes 50% exp(100000), 50% exp(200)",
     static(Uniform(1, 1024), Mixture([(0.5, Exponential(100000)), (0.5, Exponential(200))]))),
    ("longlived-set", "long-lived", "frozen-F5 size sets; lifetimes exp(50000)",
     lambda rng: Static(zipf_size_set(rng)[1], Exponential(50000))),
    ("alt-W/4", "alternating", "two per-seed F5 size sets alternating every W/4 ticks",
     alternate_random_sets(W // 4)),
    ("alt-W", "alternating", "two per-seed F5 size sets alternating every W ticks", alternate_random_sets(W)),
    ("alt-4W", "alternating", "two per-seed F5 size sets alternating every 4W ticks",
     alternate_random_sets(4 * W)),
    ("alt-trap", "alternating", "{40,100} and {100,140} alternating every W ticks",
     alternate(choice([40, 100]), choice([100, 140]), W)),
]

ADVERSARIAL: Dict[str, Family] = {name: Family(name, category, desc, build)
                                  for name, category, desc, build in _ADVERSARIAL}

# Frozen-registry families keep their own names (F1 ... F12); category "frozen:<role>".
ALL: Dict[str, Family] = {**{n: f._replace(role=f"frozen:{f.role}") for n, f in FROZEN.items()},
                          **ADVERSARIAL}


def get(name: str) -> Family:
    try:
        return ALL[name]
    except KeyError:
        raise ValueError(f"unknown family {name!r}; known: {', '.join(ALL)}") from None
