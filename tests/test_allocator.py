"""The shared ALLOC/FREE protocol (spec §12), checked for every allocator."""
import random

import pytest

from engine.algorithms import ALGORITHMS, ARBF
from engine.allocator import InvalidRequest
from engine.memory import Block, Heap, Mode
from helpers import build_fixed_layout


@pytest.fixture(params=ALGORITHMS, ids=lambda cls: cls.name)
def algo(request):
    return request.param


@pytest.mark.parametrize("size", [0, -1, 2.0, True, "4", None])
def test_invalid_size_is_rejected_without_side_effects(algo, size):
    a = algo(Heap(Mode.FIXED, 100))
    with pytest.raises(InvalidRequest):
        a.alloc(1, size)
    assert a.heap.free_blocks() == [Block(0, 100)]
    assert not a.is_live(1)
    if isinstance(a, ARBF):
        assert a.history == ()


@pytest.mark.parametrize("alloc_id", ["x", 1.0, True, None])
def test_non_integer_id_is_rejected(algo, alloc_id):
    with pytest.raises(InvalidRequest):
        algo(Heap(Mode.FIXED, 100)).alloc(alloc_id, 5)


def test_duplicate_live_id_is_rejected(algo):
    a = algo(Heap(Mode.FIXED, 100))
    a.alloc(1, 5)
    with pytest.raises(InvalidRequest):
        a.alloc(1, 5)


def test_free_of_unknown_or_already_freed_id_is_rejected(algo):
    a = algo(Heap(Mode.FIXED, 100))
    with pytest.raises(InvalidRequest):
        a.free(1)
    a.alloc(1, 5)
    a.free(1)
    with pytest.raises(InvalidRequest):
        a.free(1)


def test_id_can_be_reused_after_free(algo):
    a = algo(Heap(Mode.FIXED, 100))
    a.alloc(1, 5)
    a.free(1)
    assert a.alloc(1, 7) is not None


def test_fixed_mode_fail_marks_id_failed_until_freed(algo):
    a = algo(Heap(Mode.FIXED, 10))
    assert a.alloc(1, 11) is None
    assert a.is_live(1)
    with pytest.raises(InvalidRequest):
        a.alloc(1, 5)                                  # a FAILED id is still live
    a.free(1)                                          # no-op
    assert a.heap.free_blocks() == [Block(0, 10)]
    assert not a.is_live(1)
    assert a.alloc(1, 5) == Block(0, 5)


def test_fixed_mode_fail_leaves_heap_unchanged(algo):
    heap, _ = build_fixed_layout([("F", 30), ("A", 1), ("F", 30), ("A", 1)])
    a = algo(heap)
    before = heap.snapshot()
    assert a.alloc(1, 40) is None                      # 60 units free, no block fits
    assert heap.snapshot() == before


def test_unbounded_first_allocation_starts_at_zero(algo):
    a = algo(Heap(Mode.UNBOUNDED))
    assert a.alloc(1, 10) == Block(0, 10)
    assert a.heap.end == 10


def test_unbounded_extension_absorbs_top_free_block(algo):
    a = algo(Heap(Mode.UNBOUNDED))
    a.alloc(1, 10)
    a.alloc(2, 4)
    a.free(2)                                          # top free block [10, 14)
    assert a.alloc(3, 9) == Block(10, 9)
    assert a.heap.end == 19 and a.heap.free_blocks() == []


def test_unbounded_extension_appends_when_top_is_allocated(algo):
    a = algo(Heap(Mode.UNBOUNDED))
    a.alloc(1, 4)
    a.alloc(2, 10)
    a.free(1)                                          # free [0, 4) is not at the top
    assert a.alloc(3, 6) == Block(14, 6)
    assert a.heap.end == 20


def test_unbounded_top_free_block_is_an_ordinary_candidate(algo):
    a = algo(Heap(Mode.UNBOUNDED))
    a.alloc(1, 10)
    a.alloc(2, 1)
    a.alloc(3, 30)
    a.free(3)                                          # top free [11, 41)
    a.free(1)                                          # free [0, 10)
    assert a.alloc(4, 20) == Block(11, 20)             # only the top block fits; no growth
    assert a.heap.end == 41


@pytest.mark.parametrize("mode", [Mode.FIXED, Mode.UNBOUNDED])
def test_alloc_everything_then_free_everything_restores_one_block(algo, mode):
    sizes = [7, 3, 12, 1, 9, 4, 4, 20, 2]
    a = algo(Heap(mode, sum(sizes) if mode is Mode.FIXED else None))
    for i, s in enumerate(sizes):
        assert a.alloc(i, s) is not None
        a.heap.check_invariants()
    order = list(range(len(sizes)))
    random.Random(7).shuffle(order)
    for i in order:
        a.free(i)
        a.heap.check_invariants()
    assert a.heap.free_blocks() == [Block(0, sum(sizes))]
    assert a.heap.live_size == 0
