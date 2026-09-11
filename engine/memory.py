"""Memory model: one contiguous address range tiled by free and allocated blocks.

This is the heap mechanism shared by every allocator (frozen spec §12, §20):
allocation at the low end of the chosen block, the residual split off at the
high end, immediate coalescing with both address neighbours on free, and the
UNBOUNDED extension rule. Placement *policy* lives in ``engine.algorithms``.
"""
from bisect import bisect_left, bisect_right, insort
from enum import Enum
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple


class Mode(Enum):
    FIXED = "fixed"          # arena [0, capacity); requests that do not fit FAIL
    UNBOUNDED = "unbounded"  # heap grows on demand; the end E is a high-water mark


class Block(NamedTuple):
    """The half-open address interval [addr, addr + size)."""
    addr: int
    size: int

    @property
    def end(self) -> int:
        return self.addr + self.size


class BlockView(NamedTuple):
    """One entry of a memory-state snapshot."""
    addr: int
    size: int
    free: bool
    alloc_id: Optional[int]


def is_int(x) -> bool:
    """True for real integers; bool is rejected even though it subclasses int."""
    return isinstance(x, int) and not isinstance(x, bool)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class Heap:
    def __init__(self, mode: Mode, capacity: Optional[int] = None):
        if mode is Mode.FIXED:
            if not is_int(capacity) or capacity < 1:
                raise ValueError(f"FIXED heap needs an integer capacity >= 1, got {capacity!r}")
        elif mode is Mode.UNBOUNDED:
            if capacity is not None:
                raise ValueError("UNBOUNDED heap takes no capacity")
        else:
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode
        self.capacity = capacity
        self._end = 0
        # Free blocks, indexed three ways: by address, in address order, in (size, addr) order.
        self._free_size_at: Dict[int, int] = {}
        self._free_addrs: List[int] = []
        self._free_by_size: List[Tuple[int, int]] = []
        # Allocated blocks, indexed by allocation id and by address.
        self._alloc_by_id: Dict[int, Block] = {}
        self._alloc_id_at: Dict[int, int] = {}
        self._total_free = 0
        self._live = 0
        if mode is Mode.FIXED:
            self._insert_free(0, capacity)
            self._end = capacity

    # ------------------------------------------------------------------ state

    @property
    def end(self) -> int:
        """E: the heap end (FIXED: capacity; UNBOUNDED: high-water mark)."""
        return self._end

    @property
    def total_free(self) -> int:
        return self._total_free

    @property
    def live_size(self) -> int:
        return self._live

    @property
    def free_count(self) -> int:
        return len(self._free_addrs)

    @property
    def allocated_count(self) -> int:
        return len(self._alloc_by_id)

    @property
    def largest_free(self) -> int:
        """Size of the largest free block (0 when there is none)."""
        return self._free_by_size[-1][0] if self._free_by_size else 0

    def iter_free_blocks(self) -> Iterator[Block]:
        """Free blocks in increasing address order. Do not mutate the heap while iterating."""
        for addr in self._free_addrs:
            yield Block(addr, self._free_size_at[addr])

    def free_blocks(self) -> List[Block]:
        return list(self.iter_free_blocks())

    def iter_free_blocks_from(self, addr: int) -> Iterator[Block]:
        """Every free block once, in address order starting at the first block whose
        end is > addr, wrapping around. Do not mutate the heap while iterating."""
        n = len(self._free_addrs)
        start = bisect_right(self._free_addrs, addr) - 1   # last block starting at or before addr
        if start < 0 or self._free_addrs[start] + self._free_size_at[self._free_addrs[start]] <= addr:
            start += 1
        for k in range(n):
            a = self._free_addrs[(start + k) % n]
            yield Block(a, self._free_size_at[a])

    def allocation(self, alloc_id: int) -> Optional[Block]:
        return self._alloc_by_id.get(alloc_id)

    def is_allocated(self, alloc_id: int) -> bool:
        return alloc_id in self._alloc_by_id

    def snapshot(self) -> List[BlockView]:
        """Every block, free and allocated, in increasing address order."""
        views = [BlockView(a, s, True, None) for a, s in self._free_size_at.items()]
        views += [BlockView(b.addr, b.size, False, i) for i, b in self._alloc_by_id.items()]
        views.sort(key=lambda v: v.addr)
        return views

    # ---------------------------------------------------------- size queries

    def smallest_fitting(self, size: int) -> Optional[Block]:
        """Smallest free block with block.size >= size; lowest address among equal sizes."""
        return self._first_by_size_from(size)

    def smallest_size_above(self, size: int) -> Optional[Block]:
        """Lowest-address block of the smallest free size strictly greater than `size`."""
        return self._first_by_size_from(size + 1)

    def largest_free_block(self) -> Optional[Block]:
        """Largest free block; lowest address among equal sizes."""
        if not self._free_by_size:
            return None
        return self._first_by_size_from(self._free_by_size[-1][0])

    def top_free_block(self) -> Optional[Block]:
        """The free block ending exactly at E, if any."""
        if self._free_addrs:
            addr = self._free_addrs[-1]
            size = self._free_size_at[addr]
            if addr + size == self._end:
                return Block(addr, size)
        return None

    def _first_by_size_from(self, size: int) -> Optional[Block]:
        # Addresses are >= 0, so (size, -1) sorts before every entry of that size.
        i = bisect_left(self._free_by_size, (size, -1))
        if i == len(self._free_by_size):
            return None
        s, a = self._free_by_size[i]
        return Block(a, s)

    # ------------------------------------------------------------- mutation

    def place(self, block: Block, alloc_id: int, size: int) -> Block:
        """Allocate `size` units at the low end of free `block`; the rest stays free."""
        if self._free_size_at.get(block.addr) != block.size:
            raise ValueError(f"{block} is not a free block")
        if not is_int(size) or not 1 <= size <= block.size:
            raise ValueError(f"cannot place size {size!r} in {block}")
        if alloc_id in self._alloc_by_id:
            raise ValueError(f"allocation id {alloc_id!r} is already allocated")
        self._remove_free(block.addr)
        if block.size > size:
            self._insert_free(block.addr + size, block.size - size)
        return self._record_alloc(alloc_id, block.addr, size)

    def extend(self, alloc_id: int, size: int) -> Block:
        """UNBOUNDED no-fit path (spec §12): grow the top free block, else append at E."""
        if self.mode is not Mode.UNBOUNDED:
            raise ValueError("only an UNBOUNDED heap can extend")
        if not is_int(size) or size < 1:
            raise ValueError(f"invalid size {size!r}")
        if alloc_id in self._alloc_by_id:
            raise ValueError(f"allocation id {alloc_id!r} is already allocated")
        if self.largest_free >= size:
            raise ValueError("extend() called while a free block fits the request")
        top = self.top_free_block()
        if top is not None:
            self._remove_free(top.addr)
            addr = top.addr
        else:
            addr = self._end
        self._end = addr + size
        return self._record_alloc(alloc_id, addr, size)

    def release(self, alloc_id: int) -> Block:
        """Free an allocation and coalesce with free address neighbours. Returns the merged block."""
        block = self._alloc_by_id.pop(alloc_id, None)
        if block is None:
            raise ValueError(f"allocation id {alloc_id!r} is not allocated")
        del self._alloc_id_at[block.addr]
        self._live -= block.size
        addr, size = block
        i = bisect_left(self._free_addrs, addr)
        if i > 0:
            left = self._free_addrs[i - 1]
            left_size = self._free_size_at[left]
            if left + left_size == addr:
                self._remove_free(left)
                addr, size = left, size + left_size
        right_size = self._free_size_at.get(block.end)
        if right_size is not None:
            self._remove_free(block.end)
            size += right_size
        self._insert_free(addr, size)
        return Block(addr, size)

    def _record_alloc(self, alloc_id: int, addr: int, size: int) -> Block:
        block = Block(addr, size)
        self._alloc_by_id[alloc_id] = block
        self._alloc_id_at[addr] = alloc_id
        self._live += size
        return block

    def _insert_free(self, addr: int, size: int) -> None:
        self._free_size_at[addr] = size
        insort(self._free_addrs, addr)
        insort(self._free_by_size, (size, addr))
        self._total_free += size

    def _remove_free(self, addr: int) -> None:
        size = self._free_size_at.pop(addr)
        del self._free_addrs[bisect_left(self._free_addrs, addr)]
        del self._free_by_size[bisect_left(self._free_by_size, (size, addr))]
        self._total_free -= size

    # ----------------------------------------------------------- invariants

    def check_invariants(self) -> None:
        """Raise AssertionError if the heap state is inconsistent."""
        _check(self._free_addrs == sorted(self._free_size_at), "address index out of sync")
        _check(self._free_by_size == sorted((s, a) for a, s in self._free_size_at.items()),
               "size index out of sync")
        _check(len(self._alloc_id_at) == len(self._alloc_by_id)
               and all(self._alloc_id_at.get(b.addr) == i for i, b in self._alloc_by_id.items()),
               "allocation index out of sync")
        cursor, prev_free = 0, False
        for view in self.snapshot():
            _check(view.size >= 1, f"non-positive block size at {view.addr}")
            _check(view.addr == cursor, f"gap or overlap at address {cursor} (next block at {view.addr})")
            _check(not (view.free and prev_free), f"adjacent free blocks not coalesced at {view.addr}")
            prev_free, cursor = view.free, view.addr + view.size
        _check(cursor == self._end, f"blocks end at {cursor} but heap end is {self._end}")
        if self.mode is Mode.FIXED:
            _check(self._end == self.capacity, "FIXED heap end differs from capacity")
        _check(self._total_free == sum(self._free_size_at.values()), "total_free counter out of sync")
        _check(self._live == sum(b.size for b in self._alloc_by_id.values()), "live counter out of sync")
