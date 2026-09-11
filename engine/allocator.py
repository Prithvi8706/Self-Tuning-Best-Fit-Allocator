"""Allocator interface: the ALLOC/FREE protocol of frozen spec §12/§20.

The protocol (validation, FAIL handling, UNBOUNDED extension, the post-decision
hook) is identical for every allocator; a placement policy only implements
``select``. Allocators receive nothing but (id, size) per event (spec §13).
"""
from abc import ABC, abstractmethod
from typing import ClassVar, Optional, Set

from engine.memory import Block, Heap, Mode, is_int


class InvalidRequest(ValueError):
    """The event violates the trace protocol; spec §12 says abort the run."""


class Allocator(ABC):
    name: ClassVar[str]

    def __init__(self, heap: Heap):
        self.heap = heap
        # Ids whose ALLOC failed and that have not been freed yet (spec: Live[id] = FAILED).
        self._failed: Set[int] = set()

    def is_live(self, alloc_id: int) -> bool:
        return self.heap.is_allocated(alloc_id) or alloc_id in self._failed

    def alloc(self, alloc_id: int, size: int) -> Optional[Block]:
        """ALLOC(id, R). Returns the placed block, or None on FAIL (FIXED mode only)."""
        if not is_int(size) or size < 1:
            raise InvalidRequest(f"request size must be an integer >= 1, got {size!r}")
        if not is_int(alloc_id):
            raise InvalidRequest(f"allocation id must be an integer, got {alloc_id!r}")
        if self.is_live(alloc_id):
            raise InvalidRequest(f"allocation id {alloc_id} is already live")
        chosen = self.select(size)
        if chosen is not None:
            placed = self.heap.place(chosen, alloc_id, size)
        elif self.heap.mode is Mode.FIXED:
            self._failed.add(alloc_id)
            placed = None
        else:
            placed = self.heap.extend(alloc_id, size)
        self._after_alloc(size, placed)
        return placed

    def free(self, alloc_id: int) -> Optional[Block]:
        """FREE(id). Returns the coalesced free block; freeing an id whose ALLOC failed
        is a no-op and returns None."""
        if not is_int(alloc_id) or not self.is_live(alloc_id):
            raise InvalidRequest(f"FREE of unknown allocation id {alloc_id!r}")
        if alloc_id in self._failed:
            self._failed.remove(alloc_id)
            return None
        return self.heap.release(alloc_id)

    @abstractmethod
    def select(self, size: int) -> Optional[Block]:
        """Return a free block with block.size >= size, or None only if no free block fits."""

    def _after_alloc(self, size: int, placed: Optional[Block]) -> None:
        """Runs after every ALLOC decision, including FAILs (placed is None)."""
