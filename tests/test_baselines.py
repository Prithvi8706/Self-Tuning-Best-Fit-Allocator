import pytest

from engine.algorithms import BestFit, FirstFit, NextFit, WorstFit
from engine.memory import Block, Heap, Mode
from helpers import build_fixed_layout

# F30@0 A@30 F10@31 A@41 F50@42 A@92 F20@93 A@113
LAYOUT = [("F", 30), ("A", 1), ("F", 10), ("A", 1), ("F", 50), ("A", 1), ("F", 20), ("A", 1)]


@pytest.mark.parametrize("algo, size, expected_addr", [
    (FirstFit, 15, 0), (BestFit, 15, 93), (WorstFit, 15, 42), (NextFit, 15, 0),
    (FirstFit, 10, 0), (BestFit, 10, 31), (WorstFit, 10, 42), (NextFit, 10, 0),
    (FirstFit, 31, 42), (BestFit, 31, 42), (WorstFit, 31, 42), (NextFit, 31, 42),
    (FirstFit, 50, 42), (BestFit, 50, 42), (WorstFit, 50, 42), (NextFit, 50, 42),
    (FirstFit, 51, None), (BestFit, 51, None), (WorstFit, 51, None), (NextFit, 51, None),
])
def test_selection_on_fixed_layout(algo, size, expected_addr):
    heap, _ = build_fixed_layout(LAYOUT)
    placed = algo(heap).alloc(1, size)
    if expected_addr is None:
        assert placed is None
    else:
        assert placed == Block(expected_addr, size)
    heap.check_invariants()


def test_residual_stays_at_high_end_of_chosen_block():
    heap, _ = build_fixed_layout(LAYOUT)
    BestFit(heap).alloc(1, 15)                         # takes F20@93
    assert Block(108, 5) in heap.free_blocks()


def test_best_fit_prefers_exact_fit_over_earlier_larger_block():
    heap, _ = build_fixed_layout([("F", 20), ("A", 1), ("F", 15), ("A", 1)])
    assert BestFit(heap).alloc(1, 15) == Block(21, 15)


def test_best_fit_tie_is_lowest_address():
    heap, _ = build_fixed_layout([("F", 20), ("A", 1), ("F", 20), ("A", 1)])
    assert BestFit(heap).alloc(1, 15) == Block(0, 15)


def test_worst_fit_tie_is_lowest_address():
    heap, _ = build_fixed_layout([("F", 30), ("A", 1), ("F", 30), ("A", 1)])
    assert WorstFit(heap).alloc(1, 5) == Block(0, 5)


# ------------------------------------------------------------------ Next Fit

def test_next_fit_rover_starts_at_zero_and_follows_last_allocation():
    heap, _ = build_fixed_layout([("F", 20), ("A", 1), ("F", 20), ("A", 1)])
    nf = NextFit(heap)
    assert nf.rover == 0
    assert nf.alloc(1, 15) == Block(0, 15) and nf.rover == 15
    assert nf.alloc(2, 10) == Block(21, 10) and nf.rover == 31   # [15,20) too small
    nf.free(1)                                                   # free [0, 20)
    assert nf.alloc(3, 5) == Block(31, 5)                        # First Fit would take 0


def test_next_fit_searches_block_coalesced_across_rover_first():
    heap, _ = build_fixed_layout([("F", 20), ("A", 1), ("F", 100), ("A", 1)])
    nf = NextFit(heap)
    nf.alloc(1, 5)                                     # [0,5), rover 5, residual [5,20)
    nf.free(1)                                         # merged [0,20) contains the rover
    assert nf.alloc(2, 18) == Block(0, 18)             # strict-start semantics would pick 21


def test_next_fit_wraps_around():
    heap, _ = build_fixed_layout([("F", 10), ("A", 1), ("F", 10), ("A", 1)])
    nf = NextFit(heap)
    nf.alloc(1, 10)                                    # exact fit at 0, rover 10
    assert nf.alloc(2, 10) == Block(11, 10) and nf.rover == 21
    nf.free(1)
    assert nf.alloc(3, 10) == Block(0, 10)             # nothing after rover 21: wrap


def test_next_fit_fail_leaves_rover_unchanged():
    heap, _ = build_fixed_layout([("F", 10), ("A", 1), ("F", 10), ("A", 1)])
    nf = NextFit(heap)
    nf.alloc(1, 3)
    assert nf.alloc(2, 50) is None
    assert nf.rover == 3


def test_next_fit_rover_moves_to_new_end_after_extension():
    nf = NextFit(Heap(Mode.UNBOUNDED))
    nf.alloc(1, 10)
    nf.alloc(2, 5)
    assert nf.rover == 15 == nf.heap.end
