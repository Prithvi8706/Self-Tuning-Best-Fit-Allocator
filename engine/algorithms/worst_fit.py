from typing import Optional

from engine.allocator import Allocator
from engine.memory import Block


class WorstFit(Allocator):
    """Largest free block if it fits; lowest address among equal sizes."""
    name = "worst_fit"

    def select(self, size: int) -> Optional[Block]:
        block = self.heap.largest_free_block()
        return block if block is not None and block.size >= size else None
