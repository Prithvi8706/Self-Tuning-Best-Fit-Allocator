"""Handcrafted pathological traces with provable ARBF behaviour.

Each construction is a deterministic function returning (events, mode, capacity).
They use only the public ALLOC/FREE protocol; history "priming" is done with
transient requests (ALLOC immediately followed by its FREE), which in this heap
model leaves the layout exactly as it was: the block goes to the low end of a
free block and freeing it coalesces with its own residual.

The arithmetic behind each construction is in its docstring and is asserted by
tests/test_adversarial.py.
"""
from typing import Callable, Dict, List, NamedTuple, Optional

from engine.memory import Mode
from engine.trace import Event, alloc, free, make_trace


class Construction(NamedTuple):
    name: str
    classification: str
    events: tuple
    mode: Mode
    capacity: Optional[int]
    claim: str


class Builder:
    def __init__(self):
        self.events: List[Event] = []
        self.next_id = 0

    def alloc(self, size: int) -> int:
        i = self.next_id
        self.next_id += 1
        self.events.append(alloc(i, size))
        return i

    def free(self, *ids: int) -> None:
        for i in ids:
            self.events.append(free(i))

    def transient(self, size: int, times: int = 1) -> None:
        for _ in range(times):
            self.free(self.alloc(size))

    def trace(self):
        return make_trace(self.events)


def minimal_counterexample() -> Construction:
    """Shortest possible trace on which ARBF fails and Best Fit does not (5 events).

    A 135, A 40, F(135) leaves holes {135, 140} in a 315-unit arena and history
    {135, 40}. For the 100 request: r_BF = 35, n = 2, c(35) = 0, c(40) = 1, so
    K(35) = 35·6 = 210 > K(40) = 40·5 = 200 and ARBF takes the 140-hole. The
    140 request then fits nowhere; Best Fit left {35, 140} and fits it.
    Shorter is impossible: a deviation needs two free blocks (>= 3 events), and
    a failure needs one more request after the deviating one."""
    b = Builder()
    x = b.alloc(135)
    b.alloc(40)
    b.free(x)
    b.alloc(100)
    b.alloc(140)
    return Construction("minimal-counterexample", "expected tradeoff (cold start: one sample in history)",
                        b.trace(), Mode.FIXED, 315, "ARBF 1 failure, Best Fit 0, after only 2 remembered requests")


def minimal_mirror() -> Construction:
    """Shortest trace on which Best Fit fails and ARBF does not (6 events).

    A 160, A 64, F(160) leaves holes {160, 170} and history {160, 64}. For the
    100: c(60) = 0, c(70) = 1, K(60) = 360 > K(70) = 350, so ARBF takes the
    170-hole (residual 70) while Best Fit takes the 160-hole (residual 60).
    The 64 then fits ARBF's residual but forces Best Fit into its 170-hole,
    and the 150 fits only ARBF's intact 160-hole. One request after the
    deviation can never suffice here: Best Fit keeps the larger hole intact,
    so any single request ARBF can place, Best Fit can place too."""
    b = Builder()
    x = b.alloc(160)
    b.alloc(64)
    b.free(x)
    b.alloc(100)
    b.alloc(64)
    b.alloc(150)
    return Construction("minimal-mirror", "design case (ARBF wins)", b.trace(), Mode.FIXED, 394,
                        "Best Fit 1 failure, ARBF 0; needs one more event than the ARBF counterexample")


def rare_large_trap(cycles: int = 200) -> Construction:
    """The spec counterexample made periodic: ARBF fails every cycle, Best Fit never.

    Arena [135 | 1 | 140 | 1] = 277. Each cycle: two transient 40s, then a
    100 and a 140, then both are freed (the layout is restored in both heaps).
    With 40s at >= 1/4 of the history, K(40) = 40(2(n+1) − c40) < 70(n+1) = K(35),
    so the 100 always goes into the 140-hole and the 140 always fails."""
    b = Builder()
    x1 = b.alloc(135)
    b.alloc(1)
    x2 = b.alloc(140)
    b.alloc(1)
    b.free(x1, x2)
    for _ in range(cycles):
        b.transient(40, 2)
        v, big = b.alloc(100), b.alloc(140)
        b.free(v, big)
    return Construction("rare-large-trap", "pathological workload (spec counterexample, periodic)",
                        b.trace(), Mode.FIXED, 277, f"ARBF {cycles} failures, Best Fit 0")


def stale_history_trap(prime_pairs: int = 369, cycles: int = 400) -> Construction:
    """Sudden workload change with a stale window: damage lasts ~W/4 decisions, then stops.

    History is first filled with alternating transient 40/100 requests (40s at
    ~50%). Then the workload changes for good to cycles of (100, 140) with no
    40s. ARBF keeps betting on 40-sized residuals, and failing the 140, while
    40s stay above (n+1)/4 of the window: after k cycles c40 = 369 − k, and
    40(1478 − c40) < 35·1478 ⇔ c40 >= 185 ⇔ k <= 184, i.e. exactly 185 failures."""
    b = Builder()
    x1 = b.alloc(135)
    b.alloc(1)
    x2 = b.alloc(140)
    b.alloc(1)
    b.free(x1, x2)
    for _ in range(prime_pairs):
        b.transient(40)
        b.transient(100)
    for _ in range(cycles):
        v, big = b.alloc(100), b.alloc(140)
        b.free(v, big)
    return Construction("stale-history-trap", "theoretical weakness (history lag, bounded by the window)",
                        b.trace(), Mode.FIXED, 277,
                        "ARBF fails the first 185 post-change cycles, then matches Best Fit")


def reverse_trap(cycles: int = 200) -> Construction:
    """Mirror image: Best Fit fails every cycle, ARBF never (the design case).

    Arena [160 | 1 | 170 | 1] = 332; each cycle: transient 64s, then 100, 64,
    150. ARBF puts the 100 into the 170-hole (residual 70 fits the 64) and
    keeps the 160-hole for the 150; Best Fit leaves 60 (useless), puts the 64
    into the 170-hole and cannot place the 150."""
    b = Builder()
    x1 = b.alloc(160)
    b.alloc(1)
    x2 = b.alloc(170)
    b.alloc(1)
    b.free(x1, x2)
    for _ in range(cycles):
        b.transient(64, 2)
        ids = [b.alloc(100), b.alloc(64), b.alloc(150)]
        b.free(*ids)
    return Construction("reverse-trap", "design case (ARBF wins)", b.trace(), Mode.FIXED, 332,
                        f"Best Fit {cycles} failures, ARBF 0")


def sliver_blind_spot(cycles: int = 300) -> Construction:
    """ARBF cannot avoid small slivers: it only trades r_BF for some r < 2·r_BF.

    Holes {11, 18} and a history full of 7s: a 10 request leaves a 1-unit
    sliver under both policies, although the 18-hole would leave a residual (8)
    that fits the common size. K(1) <= 2(n+1) < (n+2)·r <= K(r) for every r >= 2,
    so a 1-sliver always wins; in general a sliver below half the smallest common
    size is never avoided. ARBF is not worse here — it is simply Best Fit."""
    b = Builder()
    x1 = b.alloc(11)
    b.alloc(1)
    x2 = b.alloc(18)
    b.alloc(1)
    b.free(x1, x2)
    for _ in range(cycles):
        b.transient(7, 3)
        b.free(b.alloc(10))
    return Construction("sliver-blind-spot", "theoretical weakness (no benefit, not harm)",
                        b.trace(), Mode.FIXED, 31, "placements identical to Best Fit; every 10 leaves a 1-sliver")


def scan_cost_blowup(holes: int = 1000, requests: int = 2000) -> Construction:
    """Per-request search cost Θ(D), D = distinct free sizes in the P4 window.

    Holes of sizes 2002, 2004, …, 2000+2·holes separated by 1-unit guards.
    Requests alternate a transient 3001 (fits the 3002-hole with r_BF = 1: cheap)
    and a transient 1 (r_BF = 2001). The 3001s keep half the history inside the
    1's window (2001, 4001], so P5 never fires and every 1 costs one K(r)
    evaluation per distinct hole size (Best Fit: a single index lookup)."""
    b = Builder()
    ids = []
    for k in range(1, holes + 1):
        ids.append(b.alloc(2000 + 2 * k))
        b.alloc(1)
    b.free(*ids)
    for _ in range(requests // 2):
        b.transient(3001)
        b.transient(1)
    capacity = sum(2000 + 2 * k + 1 for k in range(1, holes + 1))
    return Construction("scan-cost-blowup", "expected tradeoff (search cost)", b.trace(), Mode.FIXED,
                        capacity, f"ARBF inspects ~{holes} blocks per request, Best Fit 1")


CONSTRUCTIONS: Dict[str, Callable[[], Construction]] = {
    "minimal-counterexample": minimal_counterexample,
    "minimal-mirror": minimal_mirror,
    "rare-large-trap": rare_large_trap,
    "stale-history-trap": stale_history_trap,
    "reverse-trap": reverse_trap,
    "sliver-blind-spot": sliver_blind_spot,
    "scan-cost-blowup": scan_cost_blowup,
}
