"""ARBF Version 1, exactly as in the frozen specification (2026-09-11).

    K(r) = r · (2(n+1) − c(r))      (n+1)·J(r) with J(r) = r·(2 − Ĝ(r)), β = 1, κ = 1

where n is the number of remembered requests (at most W) and c(r) is how many of
them are <= r. The allocator picks the lexicographic minimum of (K, size, addr)
over fitting blocks, using the exact P2 (exact fit), P5 (shortcut) and
P4 (pruning to r < 2·r_BF) steps of spec §9/§20. The request history is updated
after every decision, including FAILs. No other state, heuristic or parameter.
"""
from bisect import bisect_left, bisect_right, insort
from collections import deque
from typing import Deque, List, NamedTuple, Optional, Tuple

from engine.allocator import Allocator
from engine.memory import Block, Heap

W = 738  # history window (spec §19); β = 1 and κ = 1 are built into cost()


class Decision(NamedTuple):
    """Read-only record of the latest select() call, for diagnostics and tests."""
    path: str                 # "none" | "exact" | "shortcut" | "scan"
    best_fit: Optional[Block]  # b₀
    chosen: Optional[Block]
    count_queries: int        # history count_le() calls made by this decision


class ARBF(Allocator):
    name = "arbf"

    def __init__(self, heap: Heap):
        super().__init__(heap)
        self._hist: Deque[int] = deque()  # last <= W request sizes, oldest first
        self._cnt: List[int] = []         # the same sizes, sorted (multiset for count_le)
        self.last_decision: Optional[Decision] = None

    @property
    def history(self) -> Tuple[int, ...]:
        return tuple(self._hist)

    def _count_le(self, x: int) -> int:
        return bisect_right(self._cnt, x)

    def cost(self, r: int) -> int:
        """K(r) = r · (2(n+1) − c(r)), exact integer arithmetic."""
        n = len(self._hist)
        return r * (2 * (n + 1) - self._count_le(r))

    def select(self, size: int) -> Optional[Block]:
        b0 = self.heap.smallest_fitting(size)
        if b0 is None:
            return self._decide("none", None, None, 0)
        rbf = b0.size - size
        if rbf == 0:
            return self._decide("exact", b0, b0, 0)                    # P2
        if self._count_le(2 * rbf - 1) == self._count_le(rbf):
            return self._decide("shortcut", b0, b0, 2)                 # P5
        best, best_k = b0, self.cost(rbf)
        queries = 3                                                    # two P5 queries + cost(rbf)
        b = self.heap.smallest_size_above(b0.size)                     # next distinct size
        while b is not None and b.size - size <= 2 * rbf - 1:          # P4
            k = self.cost(b.size - size)
            queries += 1
            if k < best_k:  # strict: the earlier block has the smaller size / lower address
                best, best_k = b, k
            b = self.heap.smallest_size_above(b.size)                  # skip same-size duplicates
        return self._decide("scan", b0, best, queries)

    def _decide(self, path: str, b0: Optional[Block], chosen: Optional[Block],
                count_queries: int) -> Optional[Block]:
        self.last_decision = Decision(path, b0, chosen, count_queries)
        return chosen

    def _after_alloc(self, size: int, placed: Optional[Block]) -> None:
        self._record_request(size)

    def _record_request(self, size: int) -> None:
        self._hist.append(size)
        insort(self._cnt, size)
        if len(self._hist) > W:
            oldest = self._hist.popleft()
            del self._cnt[bisect_left(self._cnt, oldest)]
