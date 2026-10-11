"""Workload sources for the simulator: a generated family trace, a hand-written
text trace, or a preserved trace from the adversarial corpus.

Every source resolves to one validated, immutable engine trace plus a FIXED arena
size, built once before any allocator runs — so every policy sees the same events.
"""
import math
import re
from fractions import Fraction
from typing import Dict, List, NamedTuple, Optional, Tuple

from engine.trace import Op, Trace, alloc, free, make_trace
from framework.generator import generate_trace, trace_peak_live, trace_sha256
from framework.workloads import FAMILIES, get_family

MAX_EVENTS = 50_000          # keeps per-event timelines small enough to ship to the browser
MAX_MEMORY = 1_000_000_000
LABEL_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")


class WorkloadError(ValueError):
    pass


class Workload(NamedTuple):
    kind: str                   # "family" | "trace" | "corpus"
    name: str                   # human-readable source name
    description: str
    events: Trace
    labels: Dict[int, str]      # engine allocation id -> display label
    capacity: int               # FIXED arena size in units
    sha256: str
    peak_live: int
    params: dict                # the request fields that produced this workload

    def info(self) -> dict:
        allocs = sum(e.op is Op.ALLOC for e in self.events)
        return {"kind": self.kind, "name": self.name, "description": self.description,
                "n_events": len(self.events), "alloc_events": allocs, "free_events": len(self.events) - allocs,
                "capacity": self.capacity, "sha256": self.sha256, "peak_live": self.peak_live,
                "params": self.params}

    def event_list(self) -> List[list]:
        """Compact per-event list for the browser: [op, id, label, size]."""
        return [["A" if e.op is Op.ALLOC else "F", e.alloc_id, self.labels[e.alloc_id], e.size]
                for e in self.events]


# --------------------------------------------------------------- text traces

class TraceIssue(NamedTuple):
    line: int
    message: str


def parse_trace_text(text: str) -> Tuple[Optional[Trace], Dict[int, str], List[TraceIssue]]:
    """Parse lines of ``ALLOC <label> <size>`` / ``FREE <label>`` ('#' starts a comment).

    Each ALLOC gets a fresh engine id, so a label may be reused once it has been freed.
    Returns (trace or None, id -> label, issues); the trace is None when there are issues.
    """
    issues: List[TraceIssue] = []
    events = []
    labels: Dict[int, str] = {}
    live: Dict[str, int] = {}                                   # label -> engine id
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        op = parts[0].upper()
        if op == "ALLOC":
            if len(parts) != 3:
                issues.append(TraceIssue(lineno, "expected: ALLOC <id> <size>"))
                continue
            label, size_text = parts[1], parts[2]
            if not LABEL_RE.match(label):
                issues.append(TraceIssue(lineno, f"invalid id '{label}' (letters, digits, _ . - only)"))
                continue
            if not size_text.isdigit() or int(size_text) < 1:
                issues.append(TraceIssue(lineno, f"size must be a whole number >= 1, got '{size_text}'"))
                continue
            if label in live:
                issues.append(TraceIssue(lineno, f"'{label}' is already allocated (FREE it first)"))
                continue
            alloc_id = len(labels)
            labels[alloc_id] = label
            live[label] = alloc_id
            events.append(alloc(alloc_id, int(size_text)))
        elif op == "FREE":
            if len(parts) != 2:
                issues.append(TraceIssue(lineno, "expected: FREE <id>"))
                continue
            label = parts[1]
            if label not in live:
                issues.append(TraceIssue(lineno, f"FREE of '{label}', which is not currently allocated"))
                continue
            events.append(free(live.pop(label)))
        else:
            issues.append(TraceIssue(lineno, f"unknown operation '{parts[0]}' (use ALLOC or FREE)"))
    if not issues and not events:
        issues.append(TraceIssue(0, "the trace is empty"))
    if len(events) > MAX_EVENTS:
        issues.append(TraceIssue(0, f"at most {MAX_EVENTS:,} operations are supported"))
    if issues:
        return None, labels, issues
    return make_trace(events), labels, issues   # make_trace re-checks the protocol in the engine


# ------------------------------------------------------------------ builders

def int_field(spec: dict, key: str, lo: int, hi: int) -> int:
    """spec[key] as an integer in [lo, hi] (bool rejected), else WorkloadError."""
    value = spec.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise WorkloadError(f"{key} must be an integer in [{lo:,}, {hi:,}], got {value!r}")
    return value


def margin_field(spec: dict) -> float:
    """spec["margin"] as a number in [0, 10], else WorkloadError."""
    margin = spec.get("margin")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin <= 10:
        raise WorkloadError(f"give either memory (units) or margin in [0, 10], got margin={margin!r}")
    return margin


def _capacity(spec: dict, peak_live: int) -> Tuple[int, dict]:
    """FIXED arena: explicit `memory`, or `margin` as in framework.experiment.resolve_memory."""
    if "memory" in spec:
        memory = int_field(spec, "memory", 1, MAX_MEMORY)
        return memory, {"memory": memory}
    margin = margin_field(spec)
    return max(1, math.ceil((1 + Fraction(str(margin))) * peak_live)), {"margin": margin}


def build_workload(spec: dict) -> Workload:
    kind = spec.get("kind")
    if kind == "family":
        family = get_family(str(spec.get("family")))
        seed = int_field(spec, "seed", 0, 2**31 - 1)
        n_events = int_field(spec, "n_events", 1, MAX_EVENTS)
        gt = generate_trace(family, seed, n_events)
        capacity, memory_params = _capacity(spec, gt.peak_live)
        labels = {e.alloc_id: f"A{e.alloc_id}" for e in gt.events if e.op is Op.ALLOC}
        return Workload("family", f"{family.name} · seed {seed}", family.description, gt.events, labels,
                        capacity, gt.sha256, gt.peak_live,
                        {"family": family.name, "seed": seed, "n_events": n_events, **memory_params})
    if kind == "trace":
        trace, labels, issues = parse_trace_text(str(spec.get("text", "")))
        if issues:
            raise WorkloadError("; ".join(f"line {i.line}: {i.message}" if i.line else i.message
                                          for i in issues[:5]))
        memory = int_field(spec, "memory", 1, MAX_MEMORY)
        return Workload("trace", "Custom trace", "hand-written ALLOC/FREE trace", trace, labels, memory,
                        trace_sha256(trace), trace_peak_live(trace), {"memory": memory})
    if kind == "corpus":
        entry = corpus_entry(str(spec.get("name")))
        from adversarial.corpus import read_trace
        trace = read_trace(entry["trace_file"])
        if trace_sha256(trace) != entry["sha256"]:
            raise WorkloadError(f"corpus trace {entry['name']} does not match its recorded hash")
        labels = {e.alloc_id: f"A{e.alloc_id}" for e in trace if e.op is Op.ALLOC}
        return Workload("corpus", entry["name"], entry["classification"], trace, labels, entry["memory"],
                        entry["sha256"], trace_peak_live(trace), {"name": entry["name"]})
    raise WorkloadError(f"unknown workload kind {kind!r}")


# --------------------------------------------------------------- catalogues

def corpus_entries() -> List[dict]:
    """Preserved study traces that run in a FIXED arena (the simulator's mode)."""
    from adversarial.corpus import load_manifest
    return [e for e in load_manifest() if e["mode"] == "fixed" and e["n_events"] <= MAX_EVENTS]


def corpus_entry(name: str) -> dict:
    for e in corpus_entries():
        if e["name"] == name:
            return e
    raise WorkloadError(f"unknown corpus trace {name!r}")


def catalogue() -> dict:
    return {
        "families": [{"name": f.name, "role": f.role, "description": f.description} for f in FAMILIES.values()],
        "corpus": [{"name": e["name"], "classification": e["classification"], "n_events": e["n_events"],
                    "memory": e["memory"], "explanation": e["explanation"],
                    "expected": {k: v["failed_allocations"] for k, v in e["expected"].items()}}
                   for e in corpus_entries()],
        "max_events": MAX_EVENTS,
    }

