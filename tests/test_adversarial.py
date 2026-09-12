"""The adversarial study: frozen code untouched, constructions behave exactly as
claimed, the differential fuzz is clean, and every preserved failure reproduces."""
import hashlib
import os
import random

import pytest

from adversarial import constructions, corpus, fuzz
from adversarial.controls import BestFitHigh, random_window
from adversarial.measure import compare, probe
from engine.algorithms import ARBF, BestFit
from engine.algorithms.arbf import W
from engine.memory import Block, Heap, Mode
from engine.trace import Op
from helpers import build_fixed_layout, random_trace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SHA-256 (LF line endings) of the frozen Version-1 code as of commit 14ead70.
FROZEN = {
    "engine/algorithms/arbf.py": "903610c5ec8b365208e609874d52abf2aa2820608853221ec327799e5a0cf856",
    "engine/algorithms/best_fit.py": "f8c2a0191a5d2628c7d589848167e897fa50a7649fae3ae6571dd13dcdfebfbd",
    "engine/memory.py": "a198bc0a593a1effbeca51abd6619b9a160da7a4e0c7a2511a16019ce4a760a4",
    "engine/allocator.py": "0ea02c701132dae4d4700fbd5d8be009849d6aee247d50864fdc1372955a0dc3",
}


@pytest.mark.parametrize("path", sorted(FROZEN))
def test_frozen_version1_is_untouched(path):
    with open(os.path.join(ROOT, path), "rb") as f:
        assert hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest() == FROZEN[path]


# ------------------------------------------------------------- constructions

def outcome(c):
    r = compare(c.events, c.mode, c.capacity)
    return r["best_fit"], r["arbf"]


def test_minimal_counterexample_is_five_events_and_fails_only_arbf():
    c = constructions.minimal_counterexample()
    bf, a = outcome(c)
    assert len(c.events) == 5
    assert (bf["failed_allocations"], a["failed_allocations"]) == (0, 1)
    heap, _ = build_fixed_layout([("F", 135), ("A", 40), ("F", 140)])
    arbf = ARBF(heap)
    for s in (135, 40):
        arbf._record_request(s)
    assert (arbf.cost(35), arbf.cost(40)) == (210, 200)


def test_minimal_mirror_is_six_events_and_fails_only_best_fit():
    c = constructions.minimal_mirror()
    bf, a = outcome(c)
    assert len(c.events) == 6
    assert (bf["failed_allocations"], a["failed_allocations"]) == (1, 0)


def test_one_request_after_a_first_deviation_cannot_favour_arbf():
    """From a common heap, a deviation leaves Best Fit {b0-R, b} and ARBF {b0, b-R} with
    b > b0: Best Fit's largest block dominates, so no single next request separates them
    in ARBF's favour. Checked exhaustively on the minimal-mirror prefix."""
    c = constructions.minimal_mirror()
    prefix = c.events[:4]                                          # up to and including the deviation
    for size in range(1, c.capacity + 1):
        events = prefix + (c.events[4]._replace(size=size),)
        bf, a = outcome(c._replace(events=events))
        assert not (bf["failed_allocations"] > a["failed_allocations"]), size


def test_rare_large_trap_fails_every_cycle_under_arbf_only():
    bf, a = outcome(constructions.rare_large_trap(cycles=50))
    assert (bf["failed_allocations"], a["failed_allocations"]) == (0, 50)
    assert a["fragmentation_failures"] == 50                      # memory was there, just split


def test_stale_history_damage_is_exactly_185_cycles_then_stops():
    c = constructions.stale_history_trap(cycles=400)
    bf, a = outcome(c)
    assert (bf["failed_allocations"], a["failed_allocations"]) == (0, 185)
    fails = a["failed_event_indices"]
    change = 4 + 2 + 2 * 2 * 369                                  # layout + frees + priming transients
    cycle_of = [(i - change) // 4 for i in fails]
    assert cycle_of == list(range(185))                           # the first 185 cycles, none later


def test_reverse_trap_fails_every_cycle_under_best_fit_only():
    bf, a = outcome(constructions.reverse_trap(cycles=50))
    assert (bf["failed_allocations"], a["failed_allocations"]) == (50, 0)


def test_sliver_blind_spot_is_placement_identical_to_best_fit():
    c = constructions.sliver_blind_spot(cycles=100)
    assert len(probe(c.events, c.mode, c.capacity).deviations) == 0


def test_scan_cost_grows_with_distinct_free_sizes():
    c = constructions.scan_cost_blowup(holes=600, requests=200)     # holes 2002 … 3200
    bf, a = outcome(c)
    assert bf["blocks_inspected_mean"] <= 1 and bf["failed_allocations"] == 0
    ones = sum(1 for e in c.events if e.op is Op.ALLOC and e.size == 1) - 600   # minus the layout guards
    assert a["arbf"]["count_queries_total"] >= ones * 600


# ---------------------------------------------------------- fuzz and probes

@pytest.mark.parametrize("dist", sorted(fuzz.SIZE_DRAWS))
def test_differential_fuzz_finds_no_disagreement(dist):
    for mode, cap in (("fixed", 600 if dist in ("tiny", "tie-prone") else 4000), ("unbounded", None)):
        stats = fuzz.check_one((dist, 99, mode, cap, 1800, 0.47))
        assert stats["mismatch"] == 0 and stats["violations"] == [], stats["violations"]


@pytest.mark.parametrize("source", ["stale-history-trap", "F4-s0.02"])
def test_probe_history_counts_match_decision_time_history(source):
    if source in constructions.CONSTRUCTIONS:
        c = constructions.CONSTRUCTIONS[source]()
        trace, mode, cap = c.events, c.mode, c.capacity
    else:
        from adversarial.families import get
        from framework.generator import generate_trace
        gt = generate_trace(get(source), 7001, 20000)
        trace, mode, cap = gt.events, Mode.UNBOUNDED, None
    pr = probe(trace, mode, cap)
    assert len(pr.deviations) > 5
    sizes = [e.size for e in trace if e.op is Op.ALLOC]
    for d in pr.deviations:
        hist = sizes[max(0, d.ordinal - W):d.ordinal]
        rbf, r = d.b0 - d.size, d.chosen - d.size
        assert (d.n, d.c_rbf, d.c_r) == (len(hist), sum(s <= rbf for s in hist), sum(s <= r for s in hist))


# ------------------------------------------------------------------ controls

def test_best_fit_high_takes_highest_address_among_ties():
    heap, _ = build_fixed_layout([("F", 14), ("A", 1), ("F", 14), ("A", 1), ("F", 20), ("A", 1)])
    assert BestFitHigh(heap).select(10) == Block(15, 14)


def test_random_window_with_p_zero_is_best_fit():
    trace = random_trace(random.Random(3), 2000, lambda r: r.choice((4, 6, 9, 14, 30)), 0.45)
    r = compare(trace, Mode.FIXED, 1500, (BestFit, random_window(0.0)))
    assert r["best_fit"]["failed_event_indices"] == r["random_window"]["failed_event_indices"]
    assert r["best_fit"]["peak_end"] == r["random_window"]["peak_end"]


# -------------------------------------------------------------------- corpus

ENTRIES = corpus.load_manifest() if os.path.exists(corpus.MANIFEST) else []


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_preserved_failure_reproduces_exactly(entry):
    ok, why = corpus.verify(entry)
    assert ok, why


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_preserved_trace_regenerates_from_its_seed(entry):
    from framework.generator import trace_sha256
    assert trace_sha256(corpus.regenerate(entry)) == entry["sha256"]
