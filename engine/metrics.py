"""Metrics (frozen spec §7, §18). Measurement only: no allocator reads these."""
from typing import NamedTuple, Optional

from engine.memory import Heap


def external_fragmentation(heap: Heap) -> Optional[float]:
    """EF = 1 − L/T, defined only when total free memory T > 0."""
    if heap.total_free == 0:
        return None
    return 1 - heap.largest_free / heap.total_free


class HeapStats(NamedTuple):
    end: int
    live: int
    total_free: int
    largest_free: int
    free_blocks: int
    allocated_blocks: int
    external_fragmentation: Optional[float]


def heap_stats(heap: Heap) -> HeapStats:
    return HeapStats(heap.end, heap.live_size, heap.total_free, heap.largest_free,
                     heap.free_count, heap.allocated_count, external_fragmentation(heap))


def is_fragmentation_failure(heap: Heap, size: int) -> bool:
    """For an ALLOC(size) that just failed (a FAIL leaves the heap unchanged):
    True if enough memory was free in total (T >= R) but no single block fit;
    False for a capacity failure (T < R)."""
    return heap.total_free >= size


class PeakTracker:
    """Peak footprint ratio Φ = max_t E(t) / max_t Live(t). Call observe() after every event."""

    def __init__(self):
        self.max_end = 0
        self.max_live = 0

    def observe(self, heap: Heap) -> None:
        self.max_end = max(self.max_end, heap.end)
        self.max_live = max(self.max_live, heap.live_size)

    def phi(self) -> Optional[float]:
        """None until some memory has been live."""
        return self.max_end / self.max_live if self.max_live else None
