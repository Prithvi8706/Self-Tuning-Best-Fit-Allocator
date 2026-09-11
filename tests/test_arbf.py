"""ARBF Version 1 against the frozen specification (§5 properties, §9–§12, worked examples)."""
import random

import pytest

from engine.algorithms import ARBF, BestFit
from engine.algorithms.arbf import W
from engine.memory import Block, Heap, Mode
from engine.trace import Op
from helpers import build_fixed_layout, random_trace


def primed(heap, history):
    """ARBF on `heap` whose request history is `history` (test-only priming of spec §3 Hist)."""
    a = ARBF(heap)
    for s in history:
        a._record_request(s)
    return a


BIMODAL = [64] * 369 + [100] * 369          # n = 738 = W
RARE_LARGE = [40] * 362 + [100] * 362 + [140] * 14


def test_window_constant_matches_spec():
    assert W == 738


# ------------------------------------------------------------------- cost K(r)

def test_cost_is_integer_form_of_spec_equation():
    a = primed(Heap(Mode.FIXED, 1), BIMODAL)
    assert a.cost(60) == 60 * 1478 == 88680
    assert a.cost(70) == 70 * (1478 - 369) == 77630
    assert a.cost(0) == 0


def test_cost_with_empty_history_is_twice_the_residual():
    a = ARBF(Heap(Mode.FIXED, 1))
    assert [a.cost(r) for r in (0, 1, 7, 100)] == [0, 2, 14, 200]


# ----------------------------------------------------------- spec properties

def test_worked_example_deviates_to_leave_a_usable_residual():
    heap, _ = build_fixed_layout([("F", 160), ("A", 1), ("F", 170), ("A", 1)])
    a = primed(heap, BIMODAL)
    assert a.alloc(1, 100) == Block(161, 100)          # K(70)=77630 < K(60)=88680
    assert a.last_decision.path == "scan"
    assert a.last_decision.best_fit == Block(0, 160)
    assert a.last_decision.chosen == Block(161, 170)


def test_p1_cold_start_is_best_fit():
    heap, _ = build_fixed_layout([("F", 160), ("A", 1), ("F", 170), ("A", 1)])
    assert ARBF(heap).alloc(1, 100) == Block(0, 100)


def test_p2_exact_fit_always_wins():
    heap, _ = build_fixed_layout([("F", 170), ("A", 1), ("F", 100), ("A", 1)])
    a = primed(heap, BIMODAL)
    assert a.alloc(1, 100) == Block(171, 100)
    assert a.last_decision.path == "exact"


def test_101_150_500_never_chooses_500():
    heap, _ = build_fixed_layout([("F", 101), ("A", 1), ("F", 150), ("A", 1), ("F", 500), ("A", 1)])
    a = primed(heap, [400] * W)
    assert a.alloc(1, 100) == Block(0, 100)
    assert a.last_decision.path == "shortcut"


def test_p5_shortcut_when_no_history_mass_in_window():
    heap, _ = build_fixed_layout([("F", 13), ("A", 1), ("F", 14), ("A", 1)])
    a = primed(heap, [50] * 10)                        # c(5) == c(3) == 0
    assert a.alloc(1, 10) == Block(0, 10)
    assert a.last_decision.path == "shortcut"


def test_p4_scan_never_costs_blocks_outside_window_or_duplicate_sizes():
    class SpyARBF(ARBF):
        def cost(self, r):
            self.costed.append(r)
            return super().cost(r)

    heap, _ = build_fixed_layout([("F", 13), ("A", 1), ("F", 14), ("A", 1), ("F", 14), ("A", 1),
                                  ("F", 16), ("A", 1), ("F", 40), ("A", 1)])
    a = SpyARBF(heap)
    a.costed = []
    a._record_request(4)                               # r_BF = 3 → window r <= 5
    a.alloc(1, 10)
    assert a.costed == [3, 4]                          # r = 6 and r = 30 pruned; one cost per size


def test_spec_counterexample_rare_large_request_fails_under_arbf_not_best_fit():
    layout = [("F", 135), ("A", 1), ("F", 140), ("A", 1)]
    heap, _ = build_fixed_layout(layout)
    a = primed(heap, RARE_LARGE)
    assert (a.cost(35), a.cost(40)) == (51730, 44640)
    assert a.alloc(1, 100) == Block(136, 100)          # leaves {135, 40}
    assert a.alloc(2, 140) is None
    heap_bf, _ = build_fixed_layout(layout)
    bf = BestFit(heap_bf)
    assert bf.alloc(1, 100) == Block(0, 100)           # leaves {35, 140}
    assert bf.alloc(2, 140) == Block(136, 140)


# ------------------------------------------------------------------ tie-breaking

def test_equal_cost_prefers_smaller_block():
    heap, _ = build_fixed_layout([("F", 14), ("A", 1), ("F", 13), ("A", 1)])
    a = primed(heap, [4])                              # K(3) = 12 = K(4)
    assert a.alloc(1, 10) == Block(15, 10)


def test_equal_size_prefers_lowest_address():
    heap, _ = build_fixed_layout([("F", 14), ("A", 1), ("F", 14), ("A", 1), ("F", 13), ("A", 1)])
    a = primed(heap, [4, 4])                           # K(3) = 18 > K(4) = 16
    assert a.alloc(1, 10) == Block(0, 10)


# ----------------------------------------------------------------------- history

def test_history_is_updated_after_the_decision():
    layout = [("F", 19), ("A", 1), ("F", 21), ("A", 1)]
    heap, _ = build_fixed_layout(layout)
    assert ARBF(heap).alloc(1, 10) == Block(0, 10)     # n = 0 at decision time → Best Fit
    heap, _ = build_fixed_layout(layout)
    assert primed(heap, [10]).alloc(1, 10) == Block(20, 10)   # what counting R first would do


def test_failed_requests_enter_history():
    a = ARBF(Heap(Mode.FIXED, 10))
    assert a.alloc(1, 50) is None
    assert a.last_decision.path == "none"
    assert a.history == (50,)


def test_free_does_not_touch_history():
    a = ARBF(Heap(Mode.FIXED, 100))
    a.alloc(1, 5)
    a.free(1)
    assert a.history == (5,)


def test_history_window_keeps_last_w_requests():
    a = ARBF(Heap(Mode.UNBOUNDED))
    sizes = [(i % 97) + 1 for i in range(W + 5)]
    for i, s in enumerate(sizes):
        a.alloc(i, s)
        a.free(i)
    assert a.history == tuple(sizes[-W:])
    assert a._cnt == sorted(a.history)


# ----------------------------------------------------- reductions to Best Fit

def _placements(cls, trace, mode, capacity=None):
    a = cls(Heap(mode, capacity))
    out = []
    for e in trace:
        out.append(a.alloc(e.alloc_id, e.size) if e.op is Op.ALLOC else a.free(e.alloc_id))
    return out


@pytest.mark.parametrize("seed", range(3))
def test_single_size_workload_is_identical_to_best_fit(seed):
    trace = random_trace(random.Random(seed), 2000, lambda rng: 8, free_prob=0.45)
    assert _placements(ARBF, trace, Mode.UNBOUNDED) == _placements(BestFit, trace, Mode.UNBOUNDED)


@pytest.mark.parametrize("seed", range(3))
def test_history_forced_to_zero_is_identical_to_best_fit(seed):
    class BlindARBF(ARBF):                             # Ĝ ≡ 0 (verification check V1)
        def _count_le(self, x):
            return 0

    trace = random_trace(random.Random(seed), 2000, lambda rng: rng.choice((4, 6, 9, 14, 30)), 0.45)
    assert _placements(BlindARBF, trace, Mode.FIXED, 1500) == _placements(BestFit, trace, Mode.FIXED, 1500)


# ------------------------------------------------------ per-decision guarantees

def test_every_decision_respects_p2_p3_p4_and_all_paths_are_exercised():
    paths = {"none": 0, "exact": 0, "shortcut": 0, "scan": 0}
    deviations = 0
    for seed in range(6):
        rng = random.Random(seed)
        trace = random_trace(rng, 3000, lambda r: r.choice((4, 6, 9, 14, 30, 45)), free_prob=0.45)
        a = ARBF(Heap(Mode.FIXED, 1500))
        for e in trace:
            if e.op is Op.FREE:
                a.free(e.alloc_id)
                continue
            n = len(a.history)
            placed = a.alloc(e.alloc_id, e.size)
            d = a.last_decision
            paths[d.path] += 1
            if d.path == "none":
                assert placed is None
                continue
            assert placed == Block(d.chosen.addr, e.size)
            rbf, r = d.best_fit.size - e.size, d.chosen.size - e.size
            assert r * (n + 2) <= 2 * (n + 1) * rbf                 # P3
            if d.path in ("exact", "shortcut"):
                assert d.chosen == d.best_fit                       # P2, P5
            if d.chosen != d.best_fit:
                deviations += 1
                assert d.path == "scan" and r < 2 * rbf             # P4
    assert all(count > 0 for count in paths.values()), paths
    assert deviations > 0
