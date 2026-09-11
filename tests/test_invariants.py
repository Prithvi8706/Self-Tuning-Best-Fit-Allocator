"""Randomised differential + invariant tests for every allocator.

Each allocator replays seeded random traces. Before every ALLOC its choice is
compared with an independent brute-force reference (tests/helpers.py); after
every event the heap invariants and the allocator's bookkeeping are checked.
All allocators see the same trace for a given (distribution, seed).
"""
import random

import pytest

from engine.algorithms import ALGORITHMS, ARBF, BestFit, FirstFit, NextFit, WorstFit
from engine.algorithms.arbf import W
from engine.memory import Block, Heap, Mode
from engine.trace import Op
from helpers import (random_trace, ref_arbf, ref_best_fit, ref_first_fit, ref_next_fit,
                     ref_worst_fit)

DISTRIBUTIONS = {
    "concentrated": lambda rng: rng.choice((4, 6, 9, 14, 30, 45)),
    "uniform": lambda rng: rng.randint(1, 64),
    "rare_large": lambda rng: 200 if rng.random() < 0.03 else rng.choice((8, 12, 20)),
}
SEEDS = range(4)
N_EVENTS = 1500
FIXED_CAPACITY = 1500


def reference_choice(cls, blocks, size, rover, history):
    if cls is FirstFit:
        return ref_first_fit(blocks, size)
    if cls is BestFit:
        return ref_best_fit(blocks, size)
    if cls is WorstFit:
        return ref_worst_fit(blocks, size)
    if cls is NextFit:
        return ref_next_fit(blocks, size, rover)
    if cls is ARBF:
        return ref_arbf(blocks, size, history)
    raise AssertionError(f"no reference for {cls}")


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("dist", sorted(DISTRIBUTIONS))
@pytest.mark.parametrize("mode", [Mode.FIXED, Mode.UNBOUNDED], ids=lambda m: m.value)
@pytest.mark.parametrize("cls", ALGORITHMS, ids=lambda c: c.name)
def test_matches_reference_and_preserves_invariants(cls, mode, dist, seed):
    trace = random_trace(random.Random(f"{dist}-{seed}"), N_EVENTS, DISTRIBUTIONS[dist], 0.45)
    heap = Heap(mode, FIXED_CAPACITY if mode is Mode.FIXED else None)
    allocator = cls(heap)
    rover, history, requested = 0, [], {}
    prev_end = heap.end
    for event in trace:
        if event.op is Op.ALLOC:
            size = event.size
            expected = reference_choice(cls, heap.free_blocks(), size, rover, history)
            top, end = heap.top_free_block(), heap.end
            placed = allocator.alloc(event.alloc_id, size)
            if expected is not None:
                assert placed == Block(expected.addr, size)
            elif mode is Mode.FIXED:
                assert placed is None
            else:
                assert placed == Block(top.addr if top else end, size)
            if placed is not None:
                rover = placed.end
                requested[event.alloc_id] = size
            history = (history + [size])[-W:]
            if cls is ARBF:
                assert allocator.history == tuple(history)
        else:
            allocator.free(event.alloc_id)
            requested.pop(event.alloc_id, None)
            assert not allocator.is_live(event.alloc_id)
        heap.check_invariants()
        assert all(heap.allocation(i) is not None and heap.allocation(i).size == s
                   for i, s in requested.items())
        assert heap.allocated_count == len(requested)
        assert heap.live_size == sum(requested.values())
        assert heap.end >= prev_end
        prev_end = heap.end
