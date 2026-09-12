"""Control policies for calibrating the study. They are NOT contenders and not ARBF.

Allocation outcomes are chaotic: any placement difference changes the whole
future heap. A single trace on which ARBF fails more than Best Fit therefore
proves little by itself. These controls measure how large ARBF-vs-BF gaps get
from perturbation alone, and whether ARBF's *history-informed* deviations do
better or worse than uninformed ones.
"""
import random
from bisect import bisect_left
from typing import Optional

from engine.allocator import Allocator
from engine.memory import Block


class BestFitHigh(Allocator):
    """Best Fit with the opposite tie-break: highest address among the smallest fitting
    size. Same policy quality as Best Fit; differs only on ties (noise floor)."""
    name = "best_fit_high"

    def select(self, size: int) -> Optional[Block]:
        b0 = self.heap.smallest_fitting(size)
        if b0 is None:
            return None
        by_size = self.heap._free_by_size          # read-only peek at the (size, addr) index
        s, a = by_size[bisect_left(by_size, (b0.size + 1, -1)) - 1]
        return Block(a, s)


class RandomWindow(Allocator):
    """History-blind deviator: when blocks with residual in (r_BF, 2·r_BF) exist, with
    probability `p` pick one of their distinct sizes uniformly; otherwise Best Fit.
    It deviates inside exactly ARBF's P4 window, but ignores the request history."""
    name = "random_window"
    p = 0.0
    seed = 0

    def __init__(self, heap):
        super().__init__(heap)
        self.rng = random.Random(f"random-window:{self.seed}")
        self.opportunities = self.deviations = 0

    def select(self, size: int) -> Optional[Block]:
        b0 = self.heap.smallest_fitting(size)
        if b0 is None or b0.size == size:
            return b0
        rbf = b0.size - size
        first = self.heap.smallest_size_above(b0.size)
        if first is None or first.size - size >= 2 * rbf:
            return b0
        self.opportunities += 1
        if self.rng.random() >= self.p:
            return b0                       # the window is only enumerated when we deviate
        window, b = [], first
        while b is not None and b.size - size < 2 * rbf:
            window.append(b)
            b = self.heap.smallest_size_above(b.size)
        self.deviations += 1
        return self.rng.choice(window)


def random_window(p: float, seed: int = 0):
    return type("RandomWindow", (RandomWindow,), {"p": p, "seed": seed})
