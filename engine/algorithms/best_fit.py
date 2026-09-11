from typing import Optional

from engine.allocator import Allocator
from engine.memory import Block


class BestFit(Allocator):
    """Smallest free block that fits; lowest address among equal sizes (b₀ in the spec)."""
    name = "best_fit"

    def select(self, size: int) -> Optional[Block]:
        return self.heap.smallest_fitting(size)
