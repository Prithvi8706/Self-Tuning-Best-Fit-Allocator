"""Implementation-bug hunt: differential fuzzing of the frozen ARBF against the spec.

The reference below is written from the spec formula alone: scan *every* fitting
free block (no P2/P4/P5 shortcuts, no size index), take the lexicographic minimum
of (K(r), size, addr) with K(r) = r·(2(n+1) − c(r)), history = the last W request
sizes including FAILs. Any disagreement, or any violated per-decision property,
is an implementation bug. Traces are chosen to stress the corners: K ties,
long scan windows, histories that wrap the window many times, FIXED arenas small
enough to fail often, and UNBOUNDED extension.
"""
import random
from collections import deque
from multiprocessing import Pool
from typing import Callable, Dict, List

from engine.algorithms import ARBF
from engine.algorithms.arbf import W
from engine.memory import Block, Heap, Mode
from engine.trace import Op, alloc, free, make_trace

SIZE_DRAWS: Dict[str, Callable[[random.Random], int]] = {
    "tiny": lambda r: r.randint(1, 6),                                   # tiny residuals, P4 window <= 1
    "tie-prone": lambda r: r.choice((2, 3, 4, 6, 8, 12)),                # many equal-K candidates
    "concentrated": lambda r: r.choice((4, 6, 9, 14, 30, 45)),
    "uniform": lambda r: r.randint(1, 300),
    "rare-large": lambda r: 140 if r.random() < 0.02 else r.choice((40, 100)),
    "heavy-tail": lambda r: min(5000, int(8 / (1.0 - r.random()) ** 0.9)),
    "phase": None,                                                       # two disjoint sets, switching
}


def _trace(rng: random.Random, dist: str, n_events: int, free_prob: float):
    live, events, next_id = [], [], 0
    for t in range(n_events):
        if live and rng.random() < free_prob:
            events.append(free(live.pop(rng.randrange(len(live)))))
            continue
        if dist == "phase":
            size = rng.choice((5, 11, 23) if (t // 900) % 2 else (7, 17, 40))
        else:
            size = SIZE_DRAWS[dist](rng)
        events.append(alloc(next_id, size))
        live.append(next_id)
        next_id += 1
    return make_trace(events)


def reference(blocks: List[Block], size: int, history) -> Block:
    fitting = [b for b in blocks if b.size >= size]
    if not fitting:
        return None
    n = len(history)

    def key(b):
        r = b.size - size
        c = sum(1 for s in history if s <= r)
        return (r * (2 * (n + 1) - c), b.size, b.addr)

    return min(fitting, key=key)


def check_one(job) -> dict:
    """Replay one random-free trace, comparing every decision with the reference."""
    dist, seed, mode_name, capacity, n_events, free_prob = job
    rng = random.Random(f"fuzz:{dist}:{seed}:{mode_name}")
    return check_trace(_trace(rng, dist, n_events, free_prob), Mode(mode_name), capacity, list(job))


def check_family(job) -> dict:
    """Same check on a tick-model trace from a study family (deviation-heavy workloads)."""
    from adversarial.families import get
    from adversarial.measure import mode_and_capacity
    from framework.generator import generate_trace
    name, seed, pressure, n_events = job
    gt = generate_trace(get(name), seed, n_events)
    mode, capacity = mode_and_capacity(pressure, gt.peak_live)
    return check_trace(gt.events, mode, capacity, list(job))


def check_trace(trace, mode: Mode, capacity, job) -> dict:
    heap = Heap(mode, capacity if mode is Mode.FIXED else None)
    a = ARBF(heap)
    history = deque(maxlen=W)
    stats = {"decisions": 0, "deviations": 0, "fails": 0, "scan": 0, "mismatch": 0, "violations": [],
             "job": job}
    for i, e in enumerate(trace):
        if e.op is Op.FREE:
            a.free(e.alloc_id)
            continue
        blocks = heap.free_blocks()
        expect = reference(blocks, e.size, history)
        b0 = min((b for b in blocks if b.size >= e.size), key=lambda b: (b.size, b.addr), default=None)
        n = len(history)
        placed = a.alloc(e.alloc_id, e.size)
        d = a.last_decision
        stats["decisions"] += 1
        stats["scan"] += d.path == "scan"
        problems = []
        if expect is None:
            stats["fails"] += 1
            if d.chosen is not None:
                problems.append("chose a block although none fits")
        else:
            if d.chosen != expect:
                stats["mismatch"] += 1
                problems.append(f"chose {d.chosen}, reference {expect}")
            if placed != Block(expect.addr, e.size):
                problems.append(f"placed {placed}, expected {Block(expect.addr, e.size)}")
            if d.best_fit != b0:
                problems.append(f"b0 {d.best_fit} != best fit {b0}")
            rbf, r = b0.size - e.size, d.chosen.size - e.size
            if n == 0 and d.chosen != b0:
                problems.append("P1: cold start deviated from Best Fit")
            if rbf == 0 and d.chosen != b0:
                problems.append("P2: exact fit not taken")
            if r * (n + 2) > 2 * (n + 1) * rbf:
                problems.append("P3: residual bound violated")
            if d.chosen != b0:
                stats["deviations"] += 1
                if not r < 2 * rbf:
                    problems.append("P4: deviation outside r < 2·r_BF")
        history.append(e.size)
        if tuple(history) != a.history:
            problems.append("history is not the last W requests (FAILs included)")
        if problems and len(stats["violations"]) < 5:
            stats["violations"].append({"event": i, "size": e.size, "problems": problems})
    heap.check_invariants()
    return stats


def jobs(seeds: int = 24, n_events: int = 5000):
    out = []
    for dist in SIZE_DRAWS:
        for seed in range(seeds):
            out.append((dist, seed, "fixed", {"tiny": 400, "tie-prone": 600}.get(dist, 4000 if dist != "heavy-tail"
                                                                                   else 60000), n_events, 0.47))
            out.append((dist, seed, "unbounded", None, n_events, 0.47))
    return out


DEVIATION_HEAVY = ("F5", "F6", "F4-s0.02", "F4-s0.10", "F12", "F7-L369", "rep-3", "trap-5", "stale-trap",
                   "poison-trap", "alt-trap", "tiny-mixed")


def family_jobs(seeds: int = 6, n_events: int = 6000):
    return [(name, 7000 + seed, pressure, n_events) for name in DEVIATION_HEAVY for seed in range(seeds)
            for pressure in (0.0, 0.10, "unbounded")]


def run(seeds: int = 24, n_events: int = 5000, processes: int = 20, families: bool = False) -> dict:
    with Pool(processes) as pool:
        if families:
            results = pool.map(check_family, family_jobs(seeds, n_events), chunksize=1)
        else:
            results = pool.map(check_one, jobs(seeds, n_events), chunksize=1)
    total = {k: sum(r[k] for r in results) for k in ("decisions", "deviations", "fails", "scan", "mismatch")}
    total["traces"] = len(results)
    total["violations"] = [v for r in results for v in ([{"job": r["job"], **x} for x in r["violations"]])]
    return total
