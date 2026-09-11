import pytest

from engine.algorithms import BestFit
from engine.memory import Block, Heap, Mode
from engine.metrics import (HeapStats, PeakTracker, external_fragmentation, heap_stats,
                            is_fragmentation_failure)
from helpers import build_fixed_layout

LAYOUT = [("F", 30), ("A", 1), ("F", 10), ("A", 1), ("F", 50), ("A", 1), ("F", 20), ("A", 1)]


def test_external_fragmentation_formula():
    heap, _ = build_fixed_layout(LAYOUT)
    assert external_fragmentation(heap) == pytest.approx(1 - 50 / 110)


def test_external_fragmentation_is_zero_with_one_free_block():
    assert external_fragmentation(Heap(Mode.FIXED, 10)) == 0


def test_external_fragmentation_undefined_without_free_memory():
    heap = Heap(Mode.FIXED, 10)
    heap.place(Block(0, 10), 1, 10)
    assert external_fragmentation(heap) is None
    assert external_fragmentation(Heap(Mode.UNBOUNDED)) is None


def test_heap_stats_snapshot():
    heap, _ = build_fixed_layout(LAYOUT)
    stats = heap_stats(heap)
    assert stats[:6] == (114, 4, 110, 50, 4, 4)
    assert isinstance(stats, HeapStats)


def test_failure_classification():
    heap, _ = build_fixed_layout([("F", 30), ("A", 1), ("F", 30), ("A", 1)])
    bf = BestFit(heap)
    assert bf.alloc(1, 40) is None and is_fragmentation_failure(heap, 40)      # T=60 >= 40
    assert bf.alloc(2, 70) is None and not is_fragmentation_failure(heap, 70)  # T=60 < 70


def test_peak_tracker_phi():
    heap = Heap(Mode.UNBOUNDED)
    bf, peaks = BestFit(heap), PeakTracker()
    assert peaks.phi() is None
    bf.alloc(1, 10); peaks.observe(heap)               # E=10 Live=10
    bf.alloc(2, 5); peaks.observe(heap)                # E=15 Live=15
    bf.free(1); peaks.observe(heap)                    # E=15 Live=5
    bf.alloc(3, 12); peaks.observe(heap)               # no fit, top allocated: E=27 Live=17
    assert (peaks.max_end, peaks.max_live) == (27, 17)
    assert peaks.phi() == pytest.approx(27 / 17)
