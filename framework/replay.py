"""Replay one allocator over one pre-generated trace and measure it.

The allocator receives the events strictly one at a time, as (id, size) or (id);
it never holds a reference to the trace (frozen spec §13). All metrics are
sampled after every event, so time averages are event-weighted.
"""
import time
from typing import Dict, List, Optional, Sequence, Type

from engine.algorithms import ARBF
from engine.allocator import Allocator
from engine.memory import Block, Heap, Mode
from engine.metrics import PeakTracker, external_fragmentation, is_fragmentation_failure
from engine.trace import Event, Op


class CountingHeap(Heap):
    """Heap that counts the free blocks handed to a placement policy ("blocks inspected").

    Every block returned by a size query, or yielded by a free-list iterator,
    counts as one inspection. Replay takes the difference around each ALLOC, so
    only the policy's own queries are counted.
    """

    def __init__(self, mode: Mode, capacity: Optional[int] = None):
        super().__init__(mode, capacity)
        self.inspections = 0

    def _count(self, block: Optional[Block]) -> Optional[Block]:
        self.inspections += block is not None
        return block

    def smallest_fitting(self, size):
        return self._count(super().smallest_fitting(size))

    def smallest_size_above(self, size):
        return self._count(super().smallest_size_above(size))

    def largest_free_block(self):
        return self._count(super().largest_free_block())

    def iter_free_blocks(self):
        for block in super().iter_free_blocks():
            self.inspections += 1
            yield block

    def iter_free_blocks_from(self, addr):
        for block in super().iter_free_blocks_from(addr):
            self.inspections += 1
            yield block


class _Series:
    """Event-weighted mean over the full run and over its second half, plus the peak."""

    def __init__(self, half_start: int):
        self.half_start = half_start
        self.total = self.count = self.half_total = self.half_count = 0
        self.peak = None
        self.undefined = 0
        self.last = None

    def add(self, index: int, value) -> None:
        self.last = value
        if value is None:
            self.undefined += 1
            return
        self.total += value
        self.count += 1
        if index >= self.half_start:
            self.half_total += value
            self.half_count += 1
        self.peak = value if self.peak is None else max(self.peak, value)

    def mean(self):
        return self.total / self.count if self.count else None

    def half_mean(self):
        return self.half_total / self.half_count if self.half_count else None


class _ResidualFates:
    """Fate of every leftover created by an ARBF deviation (chosen block != b₀):
    USED (a later ALLOC is placed in it), MERGED (coalesced first) or SURVIVED."""

    def __init__(self):
        self.pending: Dict[int, int] = {}      # addr -> size of still-untouched leftovers
        self.deviations = self.used = self.merged = 0

    def after_alloc(self, decision, size: int, placed: Optional[Block]) -> None:
        if placed is None:
            return
        if self.pending.pop(placed.addr, None) is not None:
            self.used += 1
        if decision.chosen != decision.best_fit:
            self.deviations += 1
            self.pending[placed.end] = decision.chosen.size - size

    def after_free(self, freed: Block, merged: Block) -> None:
        if merged.addr < freed.addr and self.pending.pop(merged.addr, None) is not None:
            self.merged += 1
        if merged.end > freed.end and self.pending.pop(freed.end, None) is not None:
            self.merged += 1


def replay(cls: Type[Allocator], events: Sequence[Event], mode: Mode,
           capacity: Optional[int] = None, check_invariants: bool = False) -> dict:
    """Run `cls` on a fresh heap over `events`; return the measurement fields of a result record."""
    heap = CountingHeap(mode, capacity)
    allocator = cls(heap)
    half = len(events) // 2
    ef, util, n_free, largest = (_Series(half) for _ in range(4))
    peaks = PeakTracker()
    fates = _ResidualFates() if isinstance(allocator, ARBF) else None
    ok = failed = frag = cap = inspected = count_queries = n_alloc = 0
    first_frag: Optional[int] = None
    failed_events: List[int] = []
    alloc_seconds = 0.0
    clock = time.perf_counter
    start = clock()
    for i, event in enumerate(events):
        if event.op is Op.ALLOC:
            before = heap.inspections
            t0 = clock()
            placed = allocator.alloc(event.alloc_id, event.size)
            alloc_seconds += clock() - t0
            inspected += heap.inspections - before
            if placed is None:
                failed += 1
                failed_events.append(i)
                if is_fragmentation_failure(heap, event.size):
                    frag += 1
                    first_frag = n_alloc if first_frag is None else first_frag
                else:
                    cap += 1
            else:
                ok += 1
            if fates is not None:
                count_queries += allocator.last_decision.count_queries
                fates.after_alloc(allocator.last_decision, event.size, placed)
            n_alloc += 1
        else:
            freed = heap.allocation(event.alloc_id)            # None if this id's ALLOC failed
            t0 = clock()
            merged = allocator.free(event.alloc_id)
            alloc_seconds += clock() - t0
            if fates is not None and freed is not None:
                fates.after_free(freed, merged)
        if check_invariants:
            heap.check_invariants()
        peaks.observe(heap)
        ef.add(i, external_fragmentation(heap))
        util.add(i, heap.live_size / heap.end if heap.end else None)
        n_free.add(i, heap.free_count)
        largest.add(i, heap.largest_free)
    replay_seconds = clock() - start

    return {
        "operation_count": len(events),
        "alloc_requests": n_alloc,
        "successful_allocations": ok,
        "failed_allocations": failed,
        "fragmentation_failures": frag,
        "capacity_failures": cap,
        "first_fragmentation_failure": first_frag,      # ALLOC ordinal (0-based); None = censored
        "failed_event_indices": failed_events,
        "ef_mean": ef.mean(),
        "ef_mean_second_half": ef.half_mean(),
        "ef_peak": ef.peak,
        "ef_undefined_events": ef.undefined,
        "utilization_mean": util.mean(),
        "utilization_mean_second_half": util.half_mean(),
        "utilization_peak": util.peak,
        "free_blocks_mean": n_free.mean(),
        "free_blocks_final": n_free.last,
        "largest_free_mean": largest.mean(),
        "largest_free_final": largest.last,
        "peak_end": peaks.max_end,
        "peak_live": peaks.max_live,
        "phi": peaks.phi(),
        "blocks_inspected_total": inspected,
        "blocks_inspected_mean": inspected / n_alloc if n_alloc else None,
        "arbf": None if fates is None else {
            "deviations": fates.deviations,
            "divergence_rate": fates.deviations / n_alloc if n_alloc else None,
            "count_queries_total": count_queries,
            "residual_used": fates.used,
            "residual_merged": fates.merged,
            "residual_survived": len(fates.pending),
        },
        "timing": {"allocator_seconds": alloc_seconds, "replay_seconds": replay_seconds},
    }
