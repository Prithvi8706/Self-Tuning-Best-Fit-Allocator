import pytest

from engine.memory import Block, BlockView, Heap, Mode
from helpers import build_fixed_layout


def test_fixed_heap_starts_as_one_free_block():
    heap = Heap(Mode.FIXED, 100)
    assert heap.free_blocks() == [Block(0, 100)]
    assert (heap.end, heap.total_free, heap.live_size, heap.largest_free) == (100, 100, 0, 100)
    heap.check_invariants()


def test_unbounded_heap_starts_empty():
    heap = Heap(Mode.UNBOUNDED)
    assert heap.free_blocks() == [] and heap.snapshot() == []
    assert (heap.end, heap.total_free, heap.largest_free) == (0, 0, 0)
    heap.check_invariants()


@pytest.mark.parametrize("capacity", [0, -5, None, 2.0, True, "10"])
def test_fixed_heap_rejects_invalid_capacity(capacity):
    with pytest.raises(ValueError):
        Heap(Mode.FIXED, capacity)


def test_unbounded_heap_rejects_capacity():
    with pytest.raises(ValueError):
        Heap(Mode.UNBOUNDED, 10)


def test_place_allocates_low_end_and_splits_residual_high():
    heap = Heap(Mode.FIXED, 100)
    assert heap.place(Block(0, 100), 1, 30) == Block(0, 30)
    assert heap.free_blocks() == [Block(30, 70)]
    assert heap.allocation(1) == Block(0, 30) and heap.is_allocated(1)
    assert (heap.live_size, heap.total_free) == (30, 70)
    heap.check_invariants()


def test_place_exact_fit_leaves_no_residual():
    heap = Heap(Mode.FIXED, 40)
    heap.place(Block(0, 40), 1, 40)
    assert heap.free_blocks() == [] and heap.total_free == 0
    heap.check_invariants()


def test_place_rejects_block_that_is_not_currently_free():
    heap = Heap(Mode.FIXED, 100)
    with pytest.raises(ValueError):
        heap.place(Block(0, 50), 1, 10)        # wrong size for the free block at 0
    heap.place(Block(0, 100), 1, 10)
    with pytest.raises(ValueError):
        heap.place(Block(0, 100), 2, 10)       # no longer free


@pytest.mark.parametrize("size", [0, 101, -1, 2.5, True])
def test_place_rejects_invalid_size(size):
    heap = Heap(Mode.FIXED, 100)
    with pytest.raises(ValueError):
        heap.place(Block(0, 100), 1, size)


def test_place_rejects_duplicate_id():
    heap = Heap(Mode.FIXED, 100)
    heap.place(Block(0, 100), 1, 10)
    with pytest.raises(ValueError):
        heap.place(Block(10, 90), 1, 10)


@pytest.mark.parametrize("release_order, expected_free", [
    (["b"], [Block(10, 10)]),                          # no free neighbour
    (["a", "b"], [Block(0, 20)]),                      # merge with left
    (["c", "b"], [Block(10, 20)]),                     # merge with right
    (["a", "c", "b"], [Block(0, 30)]),                 # merge with both
])
def test_release_coalesces_with_free_neighbours(release_order, expected_free):
    heap, ids = build_fixed_layout([("A", 10), ("A", 10), ("A", 10)])
    named = dict(zip("abc", ids))
    for name in release_order:
        heap.release(named[name])
        heap.check_invariants()
    assert heap.free_blocks() == expected_free


def test_release_returns_merged_block():
    heap, (a, b, c) = build_fixed_layout([("A", 10), ("A", 10), ("A", 10)])
    heap.release(a)
    heap.release(c)
    assert heap.release(b) == Block(0, 30)


def test_release_unknown_id_raises():
    heap = Heap(Mode.FIXED, 10)
    with pytest.raises(ValueError):
        heap.release(7)


def test_extend_appends_and_absorbs_top_free_block():
    heap = Heap(Mode.UNBOUNDED)
    assert heap.extend(1, 10) == Block(0, 10) and heap.end == 10
    assert heap.extend(2, 5) == Block(10, 5) and heap.end == 15
    heap.release(2)                                    # [10, 15) is now the top free block
    assert heap.top_free_block() == Block(10, 5)
    assert heap.extend(3, 8) == Block(10, 8) and heap.end == 18
    assert heap.free_blocks() == []
    heap.check_invariants()


def test_extend_appends_at_end_when_top_block_is_allocated():
    heap = Heap(Mode.UNBOUNDED)
    heap.extend(1, 10)
    heap.extend(2, 10)
    heap.release(1)                                    # free [0, 10) is not at the top
    assert heap.top_free_block() is None
    assert heap.extend(3, 20) == Block(20, 20) and heap.end == 40
    heap.check_invariants()


def test_extend_rejected_in_fixed_mode():
    with pytest.raises(ValueError):
        Heap(Mode.FIXED, 10).extend(1, 20)


def test_extend_rejected_while_a_free_block_fits():
    heap = Heap(Mode.UNBOUNDED)
    heap.extend(1, 10)
    heap.extend(2, 1)
    heap.release(1)
    with pytest.raises(ValueError):
        heap.extend(3, 10)


def test_size_queries_break_ties_by_lowest_address():
    # F20@0 A@20 F10@21 A@31 F20@32 A@52 F30@53 A@83
    heap, _ = build_fixed_layout([("F", 20), ("A", 1), ("F", 10), ("A", 1),
                                  ("F", 20), ("A", 1), ("F", 30), ("A", 1)])
    assert heap.smallest_fitting(15) == Block(0, 20)
    assert heap.smallest_fitting(10) == Block(21, 10)
    assert heap.smallest_fitting(31) is None
    assert heap.smallest_size_above(10) == Block(0, 20)
    assert heap.smallest_size_above(20) == Block(53, 30)
    assert heap.smallest_size_above(30) is None
    assert heap.largest_free_block() == Block(53, 30)
    assert heap.top_free_block() is None
    assert (heap.total_free, heap.largest_free, heap.free_count) == (80, 30, 4)


def test_largest_free_block_tie_is_lowest_address():
    heap, _ = build_fixed_layout([("F", 30), ("A", 1), ("F", 30), ("A", 1)])
    assert heap.largest_free_block() == Block(0, 30)


def test_snapshot_lists_every_block_in_address_order():
    heap, (x, y) = build_fixed_layout([("A", 5), ("F", 7), ("A", 3)])
    assert heap.snapshot() == [BlockView(0, 5, False, x), BlockView(5, 7, True, None),
                               BlockView(12, 3, False, y)]


# ------------------------------------------------- invariant checker catches corruption

def _corrupt_overlap(heap):
    heap._insert_free(2, 4)                            # [2,6) overlaps allocated [0,5)


def _corrupt_uncoalesced(heap):
    heap._alloc_by_id.pop(1)
    heap._alloc_id_at.pop(0)
    heap._live -= 5
    heap._insert_free(0, 5)                            # [0,5) next to free [5,10)


def _corrupt_gap(heap):
    heap._remove_free(5)


def _corrupt_counter(heap):
    heap._total_free += 1


def _corrupt_index(heap):
    heap._free_by_size.append((1, 99))


@pytest.mark.parametrize("corrupt, message", [
    (_corrupt_overlap, "gap or overlap"),
    (_corrupt_uncoalesced, "adjacent free blocks"),
    (_corrupt_gap, "gap or overlap|blocks end at"),
    (_corrupt_counter, "total_free"),
    (_corrupt_index, "size index"),
])
def test_check_invariants_detects_corruption(corrupt, message):
    heap = Heap(Mode.FIXED, 10)
    heap.place(Block(0, 10), 1, 5)                     # A[0,5) F[5,10)
    heap.check_invariants()
    corrupt(heap)
    with pytest.raises(AssertionError, match=message):
        heap.check_invariants()
