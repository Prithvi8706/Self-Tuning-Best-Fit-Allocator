"""Paired measurement of ARBF against Best Fit on one trace, plus mechanism probes.

Headline metrics come from the frozen replay (framework.replay.replay), so every
number here is directly comparable with the benchmark. `probe` and `blame` are
separate instrumented replays used only to explain *why* a result happened.
"""
import math
from fractions import Fraction
from typing import Dict, List, NamedTuple, Optional, Sequence, Type, Union

from engine.algorithms import ARBF, BestFit
from engine.algorithms.arbf import W
from engine.allocator import Allocator
from engine.memory import Heap, Mode
from engine.trace import Event, Op
from framework.replay import replay

Pressure = Union[float, str]              # FIXED heap margin, or "unbounded"
PRESSURES = (0.0, 0.02, 0.05, 0.10, 0.25, "unbounded")
KEYS = ("alloc_requests", "failed_allocations", "fragmentation_failures", "capacity_failures",
        "first_fragmentation_failure", "failed_event_indices", "ef_mean", "utilization_mean",
        "largest_free_mean", "peak_end", "peak_live", "phi", "blocks_inspected_mean", "arbf")


def capacity_for(peak_live: int, margin: float) -> int:
    """Same rule as the frozen experiment: H = ceil((1 + margin) · trace peak live)."""
    return max(1, math.ceil((1 + Fraction(str(margin))) * peak_live))


def mode_and_capacity(pressure: Pressure, peak_live: int):
    if pressure == "unbounded":
        return Mode.UNBOUNDED, None
    return Mode.FIXED, capacity_for(peak_live, pressure)


def run(cls: Type[Allocator], events: Sequence[Event], mode: Mode, capacity: Optional[int]) -> dict:
    r = replay(cls, events, mode, capacity)
    out = {k: r[k] for k in KEYS}
    out["allocator_seconds"] = r["timing"]["allocator_seconds"]
    return out


def compare(events: Sequence[Event], mode: Mode, capacity: Optional[int],
            algorithms: Sequence[Type[Allocator]] = (BestFit, ARBF)) -> Dict[str, dict]:
    return {cls.name: run(cls, events, mode, capacity) for cls in algorithms}


# ------------------------------------------------------------------ probes

class Deviation(NamedTuple):
    ordinal: int          # ALLOC ordinal (0-based)
    event: int            # event index in the trace
    size: int             # request R
    b0: int               # Best Fit's block size
    chosen: int           # ARBF's block size
    n: int                # history length at decision time
    c_rbf: int            # history count <= r_BF
    c_r: int              # history count <= r (the chosen residual)


class Failure(NamedTuple):
    ordinal: int
    event: int
    size: int
    total_free: int
    largest_free: int


class ProbeResult(NamedTuple):
    deviations: List[Deviation]
    fates: List[Optional[str]]      # per deviation: "used" | "merged" | None (survived)
    failures: List[Failure]
    paths: Dict[str, int]


def probe(events: Sequence[Event], mode: Mode, capacity: Optional[int],
          cls: Type[ARBF] = ARBF) -> ProbeResult:
    """Replay ARBF recording every deviation (chosen != b0), each deviation's residual
    fate, and every failed ALLOC with the free-memory state at that moment."""
    heap = Heap(mode, capacity)
    a = cls(heap)
    deviations: List[Deviation] = []
    fates: List[Optional[str]] = []
    failures: List[Failure] = []
    pending: Dict[int, int] = {}                    # residual addr -> deviation index
    paths = {"none": 0, "exact": 0, "shortcut": 0, "scan": 0}
    ordinal = 0
    for i, e in enumerate(events):
        if e.op is Op.ALLOC:
            n = len(a._hist)
            evicted = a._hist[0] if n == W else None      # dropped from the window by this request
            placed = a.alloc(e.alloc_id, e.size)
            d = a.last_decision
            paths[d.path] += 1
            if placed is None:
                failures.append(Failure(ordinal, i, e.size, heap.total_free, heap.largest_free))
            else:
                k = pending.pop(placed.addr, None)
                if k is not None:
                    fates[k] = "used"
                if d.chosen != d.best_fit:
                    rbf, r = d.best_fit.size - e.size, d.chosen.size - e.size
                    pending[placed.end] = len(deviations)
                    deviations.append(Deviation(ordinal, i, e.size, d.best_fit.size, d.chosen.size, n,
                                                _count_before(a, rbf, e.size, evicted),
                                                _count_before(a, r, e.size, evicted)))
                    fates.append(None)
            ordinal += 1
        else:
            freed = heap.allocation(e.alloc_id)
            merged = a.free(e.alloc_id)
            if freed is not None:
                if merged.addr < freed.addr:
                    k = pending.pop(merged.addr, None)
                    if k is not None:
                        fates[k] = "merged"
                if merged.end > freed.end:
                    k = pending.pop(freed.end, None)
                    if k is not None:
                        fates[k] = "merged"
    return ProbeResult(deviations, fates, failures, paths)


def _count_before(a: ARBF, x: int, recorded: int, evicted: Optional[int]) -> int:
    """History count <= x as it was at decision time: undo the request recorded after
    the decision and restore the entry it evicted from the window."""
    return a._count_le(x) - (recorded <= x) + (evicted is not None and evicted <= x)


class _ForceBestFitAt(ARBF):
    """Analysis-only: ARBF except that ALLOC ordinal `force` takes Best Fit's b0.
    The history is still updated exactly as ARBF would (the request is recorded)."""
    force = -1

    def __init__(self, heap):
        super().__init__(heap)
        self._k = 0

    def select(self, size):
        chosen = super().select(size)
        k, self._k = self._k, self._k + 1
        return self.last_decision.best_fit if k == self.force else chosen


def _succeeds(cls: Type[Allocator], events: Sequence[Event], mode: Mode, capacity: Optional[int],
              target: int) -> bool:
    a = cls(Heap(mode, capacity))
    for e in events[:target]:
        if e.op is Op.ALLOC:
            a.alloc(e.alloc_id, e.size)
        else:
            a.free(e.alloc_id)
    return a.alloc(events[target].alloc_id, events[target].size) is not None


def blame(events: Sequence[Event], mode: Mode, capacity: Optional[int], target: int,
          deviations: Sequence[Deviation], max_candidates: int = 40) -> List[dict]:
    """Single-deviation counterfactuals for the failed ALLOC at event index `target`:
    for each of the last `max_candidates` deviations before it, replay with only that
    decision replaced by Best Fit's and report whether the ALLOC now succeeds."""
    size = events[target].size
    out = []
    for d in [d for d in deviations if d.event < target][-max_candidates:]:
        forced = type("Forced", (_ForceBestFitAt,), {"force": d.ordinal})
        out.append({"deviation": d._asdict(), "fixes_failure": _succeeds(forced, events, mode, capacity, target),
                    "sacrificed_fitting_block": d.b0 < size <= d.chosen})
    return out
