from typing import Optional

from engine.allocator import Allocator
from engine.memory import Block


class FirstFit(Allocator):
    """Lowest-address free block that fits."""
    name = "first_fit"

    def select(self, size: int) -> Optional[Block]:
        for block in self.heap.iter_free_blocks():
            if block.size >= size:
                return block
        return None
