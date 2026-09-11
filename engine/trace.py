"""Workload/trace representation.

A trace is a fully materialised, validated, immutable sequence of events that
exists before any allocator runs. ``run_trace`` hands it to an allocator one
event at a time, passing only (id, size) — the online restriction of spec §13.
"""
from enum import Enum
from typing import Callable, Iterable, NamedTuple, Optional, Tuple

from engine.allocator import Allocator
from engine.memory import Block, is_int


class Op(Enum):
    ALLOC = "alloc"
    FREE = "free"


class Event(NamedTuple):
    op: Op
    alloc_id: int
    size: Optional[int] = None  # ALLOC only


def alloc(alloc_id: int, size: int) -> Event:
    return Event(Op.ALLOC, alloc_id, size)


def free(alloc_id: int) -> Event:
    return Event(Op.FREE, alloc_id)


Trace = Tuple[Event, ...]


class TraceError(ValueError):
    pass


def make_trace(events: Iterable[Event]) -> Trace:
    """Validate the ALLOC/FREE protocol and freeze the events into a tuple."""
    trace = tuple(events)
    live = set()
    for i, e in enumerate(trace):
        if not isinstance(e, Event) or not is_int(e.alloc_id):
            raise TraceError(f"event {i}: malformed event {e!r}")
        if e.op is Op.ALLOC:
            if not is_int(e.size) or e.size < 1:
                raise TraceError(f"event {i}: ALLOC size must be an integer >= 1, got {e.size!r}")
            if e.alloc_id in live:
                raise TraceError(f"event {i}: ALLOC of live id {e.alloc_id}")
            live.add(e.alloc_id)
        elif e.op is Op.FREE:
            if e.size is not None:
                raise TraceError(f"event {i}: FREE carries a size")
            if e.alloc_id not in live:
                raise TraceError(f"event {i}: FREE of id {e.alloc_id} that is not live")
            live.remove(e.alloc_id)
        else:
            raise TraceError(f"event {i}: unknown op {e.op!r}")
    return trace


Observer = Callable[[int, Event, Optional[Block]], None]


def run_trace(allocator: Allocator, trace: Trace, observer: Optional[Observer] = None) -> int:
    """Replay `trace` event by event; return the number of failed ALLOCs.

    `observer(index, event, placed)` runs after each event; `placed` is the
    placed block for a successful ALLOC and None for FREE or a FAIL.
    """
    failures = 0
    for i, event in enumerate(trace):
        placed = None
        if event.op is Op.ALLOC:
            placed = allocator.alloc(event.alloc_id, event.size)
            failures += placed is None
        else:
            allocator.free(event.alloc_id)
        if observer is not None:
            observer(i, event, placed)
    return failures
