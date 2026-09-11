"""Test infrastructure: layout builder, random traces, and brute-force reference
selectors written independently of the engine (no pruning, no shortcuts, no indexes)."""
import random
from collections import Counter
from typing import Callable, List, Optional, Sequence, Tuple

from engine.memory import Block, Heap, Mode
from engine.trace import Trace, alloc, free, make_trace


def build_fixed_layout(segments: Sequence[Tuple[str, int]], heap_cls=Heap) -> Tuple[Heap, List[int]]:
    """Build a FIXED heap from ('F', size) / ('A', size) segments laid out from address 0.

    Returns the heap and the ids of the 'A' segments (1000, 1001, ...) in address order.
    Adjacent 'F' segments coalesce, as they would in any real heap.
    """
    heap = heap_cls(Mode.FIXED, sum(size for _, size in segments))
    kept, dropped = [], []
    for i, (kind, size) in enumerate(segments):
        alloc_id = 1000 + len(kept) if kind == "A" else -1 - i
        heap.place(heap.top_free_block(), alloc_id, size)
        (kept if kind == "A" else dropped).append(alloc_id)
    for alloc_id in dropped:
        heap.release(alloc_id)
    heap.check_invariants()
    return heap, kept


def random_trace(rng: random.Random, n_events: int, draw_size: Callable[[random.Random], int],
                 free_prob: float) -> Trace:
    live: List[int] = []
    events = []
    next_id = 0
    for _ in range(n_events):
        if live and rng.random() < free_prob:
            events.append(free(live.pop(rng.randrange(len(live)))))
        else:
            events.append(alloc(next_id, draw_size(rng)))
            live.append(next_id)
            next_id += 1
    return make_trace(events)


# ---------------------------------------------------------------- references

def ref_first_fit(blocks: List[Block], size: int) -> Optional[Block]:
    fitting = [b for b in blocks if b.size >= size]
    return min(fitting, key=lambda b: b.addr) if fitting else None


def ref_best_fit(blocks: List[Block], size: int) -> Optional[Block]:
    fitting = [b for b in blocks if b.size >= size]
    return min(fitting, key=lambda b: (b.size, b.addr)) if fitting else None


def ref_worst_fit(blocks: List[Block], size: int) -> Optional[Block]:
    fitting = [b for b in blocks if b.size >= size]
    return min(fitting, key=lambda b: (-b.size, b.addr)) if fitting else None


def ref_next_fit(blocks: List[Block], size: int, rover: int) -> Optional[Block]:
    ordered = sorted(blocks, key=lambda b: b.addr)
    order = [b for b in ordered if b.end > rover] + [b for b in ordered if b.end <= rover]
    return next((b for b in order if b.size >= size), None)


def ref_arbf_cost(r: int, history: Sequence[int]) -> int:
    """(n+1)·J(r) with J(r) = r·(2 − c(r)/(n+1)), straight from spec §5."""
    n = len(history)
    c = sum(1 for s in history if s <= r)
    return r * (2 * (n + 1) - c)


def ref_arbf(blocks: List[Block], size: int, history: Sequence[int]) -> Optional[Block]:
    """Full scan of every fitting block: lexicographic min of (K, size, addr)."""
    fitting = [b for b in blocks if b.size >= size]
    if not fitting:
        return None
    n = len(history)
    counts = Counter(history)

    def key(b: Block):
        r = b.size - size
        c = sum(v for s, v in counts.items() if s <= r)
        return (r * (2 * (n + 1) - c), b.size, b.addr)

    return min(fitting, key=key)
