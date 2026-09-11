"""Trace generation: the tick model (approved 2026-09-12).

Each tick t = 0, 1, 2, ...: first FREE every live object whose death time is
<= t, in (death, id) order; then, with probability alloc_prob, ALLOC a new object
whose (size, lifetime) comes from the workload process; it dies at t + lifetime.
Generation stops the moment the trace holds exactly n_events events; objects
still live then are not freed (no drain phase). The whole trace is generated,
validated and hashed before any allocator sees it.
"""
import hashlib
import heapq
import json
import random
from typing import NamedTuple

from engine.memory import is_int
from engine.trace import Op, Trace, alloc, free, make_trace
from framework.workloads import Family


class GeneratedTrace(NamedTuple):
    workload: str
    seed: int
    alloc_prob: float
    events: Trace
    sha256: str
    peak_live: int     # max live units if every ALLOC succeeded (a property of the trace)
    alloc_count: int


def generate_trace(family: Family, seed: int, n_events: int, alloc_prob: float = 1.0) -> GeneratedTrace:
    if not is_int(seed):
        raise ValueError(f"seed must be an integer, got {seed!r}")
    if not is_int(n_events) or n_events < 1:
        raise ValueError(f"n_events must be an integer >= 1, got {n_events!r}")
    if isinstance(alloc_prob, bool) or not isinstance(alloc_prob, (int, float)) or not 0 < alloc_prob <= 1:
        raise ValueError(f"alloc_prob must be in (0, 1], got {alloc_prob!r}")
    rng = random.Random(f"arbf-bench:{family.name}:{seed}")   # str seeds hash via SHA-512: stable
    process = family.build(rng)
    deaths = []                                               # heap of (death tick, id)
    events = []
    tick = next_id = 0
    while len(events) < n_events:
        while deaths and deaths[0][0] <= tick and len(events) < n_events:
            events.append(free(heapq.heappop(deaths)[1]))
        if len(events) < n_events and rng.random() < alloc_prob:
            size, lifetime = process.draw(tick, rng)
            events.append(alloc(next_id, size))
            heapq.heappush(deaths, (tick + lifetime, next_id))
            next_id += 1
        tick += 1
    trace = make_trace(events)
    return GeneratedTrace(family.name, seed, float(alloc_prob), trace, trace_sha256(trace),
                          trace_peak_live(trace), next_id)


def _canonical_lines(trace: Trace):
    for e in trace:
        yield f"A {e.alloc_id} {e.size}\n" if e.op is Op.ALLOC else f"F {e.alloc_id}\n"


def trace_sha256(trace: Trace) -> str:
    h = hashlib.sha256()
    for line in _canonical_lines(trace):
        h.update(line.encode("ascii"))
    return h.hexdigest()


def trace_peak_live(trace: Trace) -> int:
    sizes, live, peak = {}, 0, 0
    for e in trace:
        if e.op is Op.ALLOC:
            sizes[e.alloc_id] = e.size
            live += e.size
            peak = max(peak, live)
        else:
            live -= sizes.pop(e.alloc_id)
    return peak


def save_trace(gt: GeneratedTrace, path: str) -> None:
    header = {"workload": gt.workload, "seed": gt.seed, "alloc_prob": gt.alloc_prob,
              "n_events": len(gt.events), "sha256": gt.sha256, "peak_live": gt.peak_live,
              "alloc_count": gt.alloc_count}
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(json.dumps(header, sort_keys=True) + "\n")
        f.writelines(_canonical_lines(gt.events))


def load_trace(path: str) -> GeneratedTrace:
    with open(path, encoding="ascii") as f:
        header = json.loads(f.readline())
        events = []
        for line in f:
            parts = line.split()
            events.append(alloc(int(parts[1]), int(parts[2])) if parts[0] == "A" else free(int(parts[1])))
    trace = make_trace(events)
    if trace_sha256(trace) != header["sha256"] or len(trace) != header["n_events"]:
        raise ValueError(f"{path}: trace does not match its header hash")
    return GeneratedTrace(header["workload"], header["seed"], header["alloc_prob"], trace,
                          header["sha256"], trace_peak_live(trace), header["alloc_count"])
