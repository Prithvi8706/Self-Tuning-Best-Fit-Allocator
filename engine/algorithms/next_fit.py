from typing import Optional

from engine.allocator import Allocator
from engine.memory import Block, Heap


class NextFit(Allocator):
    """Roving-pointer First Fit.

    The rover is an address, initially 0. After each successful ALLOC it is set
    to placed.addr + R. A search starts at the first free block whose end is
    greater than the rover (so a block that coalesced across the rover is
    searched first), proceeds in increasing address order, wraps around once,
    and takes the first block that fits. A FAIL leaves the rover unchanged.
    """
    name = "next_fit"

    def __init__(self, heap: Heap):
        super().__init__(heap)
        self.rover = 0

    def select(self, size: int) -> Optional[Block]:
        for block in self.heap.iter_free_blocks_from(self.rover):
            if block.size >= size:
                return block
        return None

    def _after_alloc(self, size: int, placed: Optional[Block]) -> None:
        if placed is not None:
            self.rover = placed.end
