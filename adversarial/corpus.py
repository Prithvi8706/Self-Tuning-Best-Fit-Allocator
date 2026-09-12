"""Preserved failures: reproducible traces with their expected outcomes.

Each entry of corpus/manifest.json names its source (a construction, a family and
seed, or a search genome and seed), the exact arena, the SHA-256 of the stored
trace (canonical line format of framework.generator), the exact metrics both
policies must reproduce, the classification and the causal explanation.
Traces are stored gzipped; a generated trace may be a prefix of the generator's
output (the arena size is stored explicitly, so the prefix replays identically).
"""
import gzip
import json
import os
from typing import Dict, List, Optional, Tuple

from adversarial import constructions, search
from adversarial.families import get
from adversarial.measure import compare
from engine.memory import Mode
from engine.trace import Op, alloc, free, make_trace
from framework.generator import generate_trace, trace_sha256

HERE = os.path.join(os.path.dirname(__file__), "corpus")
MANIFEST = os.path.join(HERE, "manifest.json")
EXPECT_KEYS = ("failed_allocations", "fragmentation_failures", "peak_end", "first_fragmentation_failure")


def load_manifest() -> List[dict]:
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(entries: List[dict]) -> None:
    os.makedirs(HERE, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entries, f, indent=1, sort_keys=True)
        f.write("\n")


def write_trace(name: str, events) -> str:
    os.makedirs(HERE, exist_ok=True)
    path = os.path.join(HERE, f"{name}.trace.gz")
    with gzip.GzipFile(path, "wb", mtime=0) as f:                   # mtime=0: byte-stable files
        for e in events:
            f.write((f"A {e.alloc_id} {e.size}\n" if e.op is Op.ALLOC else f"F {e.alloc_id}\n").encode("ascii"))
    return os.path.basename(path)


def read_trace(filename: str):
    with gzip.open(os.path.join(HERE, filename), "rt", encoding="ascii") as f:
        events = [alloc(int(p[1]), int(p[2])) if p[0] == "A" else free(int(p[1]))
                  for p in (line.split() for line in f)]
    return make_trace(events)


def regenerate(entry: dict):
    """Rebuild the trace from its source description (independent of the stored file)."""
    src = entry["source"]
    if src["kind"] == "construction":
        return constructions.CONSTRUCTIONS[src["name"]]().events
    fam = get(src["family"]) if src["kind"] == "family" else search.family(src["genome"])
    return generate_trace(fam, src["seed"], src["n_events"]).events[:entry["prefix"]]


def outcome(events, mode: Mode, capacity: Optional[int]) -> Dict[str, dict]:
    res = compare(events, mode, capacity)
    return {name: {k: r[k] for k in EXPECT_KEYS} for name, r in res.items()}


def make_entry(name: str, source: dict, events, mode: Mode, capacity: Optional[int], classification: str,
               explanation: str, prefix: Optional[int] = None, extra: Optional[dict] = None) -> dict:
    return {"name": name, "source": source, "trace_file": write_trace(name, events), "sha256": trace_sha256(events),
            "n_events": len(events), "prefix": prefix if prefix is not None else len(events),
            "mode": mode.value, "memory": capacity, "classification": classification,
            "expected": outcome(events, mode, capacity), "explanation": explanation, **(extra or {})}


def verify(entry: dict) -> Tuple[bool, str]:
    events = read_trace(entry["trace_file"])
    if trace_sha256(events) != entry["sha256"]:
        return False, "stored trace does not match its hash"
    got = outcome(events, Mode(entry["mode"]), entry["memory"])
    if got != entry["expected"]:
        return False, f"outcome differs: {got} != {entry['expected']}"
    return True, "ok"


def best_prefix(events, mode: Mode, capacity: Optional[int]) -> int:
    """Shortest prefix that keeps the full-trace ARBF-minus-Best-Fit failure gap (FIXED),
    or that contains ARBF's peak heap end (UNBOUNDED). A prefix replays identically."""
    res = compare(events, mode, capacity)
    if mode is Mode.UNBOUNDED:
        from engine.algorithms import ARBF
        from engine.memory import Heap
        a, peak, at = ARBF(Heap(mode)), 0, 0
        for i, e in enumerate(events):
            a.alloc(e.alloc_id, e.size) if e.op is Op.ALLOC else a.free(e.alloc_id)
            if a.heap.end > peak:
                peak, at = a.heap.end, i
        return at + 1
    fa, fb = res["arbf"]["failed_event_indices"], res["best_fit"]["failed_event_indices"]
    marks = sorted([(i, +1) for i in fa] + [(i, -1) for i in fb])
    gap, best, best_at = 0, 0, len(events) - 1
    for i, step in marks:
        gap += step
        if gap > best:
            best, best_at = gap, i
    return best_at + 1
