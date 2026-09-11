"""Replay layer: metric correctness, search-cost counting, identical traces for every
allocator, no access to future events, and memory invariants on every family."""
import inspect

import pytest

from engine.algorithms import ALGORITHMS, ARBF, BestFit, FirstFit, NextFit, WorstFit
from engine.memory import Mode
from engine.trace import Op, alloc, free, make_trace
from framework.generator import generate_trace
from framework.replay import CountingHeap, replay
from framework.workloads import FAMILIES
from helpers import build_fixed_layout


# ------------------------------------------------------------ metric values

def test_metrics_on_handcrafted_trace():
    # H=10: A0[0,4) | A1[4,7) | F0 -> free [0,4),[7,10) | A2(5) frag-FAIL | A3(8) capacity-FAIL
    trace = make_trace([alloc(0, 4), alloc(1, 3), free(0), alloc(2, 5), alloc(3, 8)])
    r = replay(BestFit, trace, Mode.FIXED, 10)
    assert (r["alloc_requests"], r["successful_allocations"], r["failed_allocations"]) == (4, 2, 2)
    assert (r["fragmentation_failures"], r["capacity_failures"]) == (1, 1)
    assert r["first_fragmentation_failure"] == 2 and r["failed_event_indices"] == [3, 4]
    assert r["ef_mean"] == pytest.approx((3 / 7) * 3 / 5)
    assert r["ef_peak"] == pytest.approx(3 / 7) and r["ef_mean_second_half"] == pytest.approx(3 / 7)
    assert r["utilization_mean"] == pytest.approx(0.4) and r["utilization_peak"] == pytest.approx(0.7)
    assert r["utilization_mean_second_half"] == pytest.approx(0.3)
    assert (r["free_blocks_mean"], r["free_blocks_final"]) == (pytest.approx(1.6), 2)
    assert (r["largest_free_mean"], r["largest_free_final"]) == (pytest.approx(4.2), 4)
    assert (r["peak_end"], r["peak_live"], r["phi"]) == (10, 7, pytest.approx(10 / 7))
    assert (r["blocks_inspected_total"], r["blocks_inspected_mean"]) == (2, 0.5)
    assert r["arbf"] is None and r["ef_undefined_events"] == 0


def test_ef_undefined_when_heap_is_full():
    r = replay(FirstFit, make_trace([alloc(0, 10), free(0)]), Mode.FIXED, 10)
    assert r["ef_undefined_events"] == 1 and r["ef_mean"] == 0.0


def test_unbounded_utilization_and_phi():
    trace = make_trace([alloc(0, 10), alloc(1, 5), free(0), alloc(2, 12)])
    r = replay(BestFit, trace, Mode.UNBOUNDED)
    assert (r["peak_end"], r["peak_live"]) == (27, 17) and r["phi"] == pytest.approx(27 / 17)
    assert r["utilization_peak"] == 1.0


# ---------------------------------------------------------- blocks inspected

LAYOUT = [("F", 30), ("A", 1), ("F", 10), ("A", 1), ("F", 50), ("A", 1), ("F", 20), ("A", 1)]


@pytest.mark.parametrize("cls, size, expected", [
    (FirstFit, 45, 3), (NextFit, 45, 3), (BestFit, 45, 1), (WorstFit, 45, 1), (ARBF, 45, 1),
    (FirstFit, 60, 4), (NextFit, 60, 4), (BestFit, 60, 0), (WorstFit, 60, 1), (ARBF, 60, 0),
])
def test_blocks_inspected_as_implemented(cls, size, expected):
    heap, _ = build_fixed_layout(LAYOUT, heap_cls=CountingHeap)
    heap.inspections = 0
    cls(heap).alloc(1, size)
    assert heap.inspections == expected


def test_arbf_scan_inspections_and_count_queries():
    heap, _ = build_fixed_layout([("F", 13), ("A", 1), ("F", 14), ("A", 1), ("F", 14), ("A", 1),
                                  ("F", 16), ("A", 1), ("F", 40), ("A", 1)], heap_cls=CountingHeap)
    a = ARBF(heap)
    a._record_request(4)
    heap.inspections = 0
    a.alloc(1, 10)
    assert heap.inspections == 3                       # b0=13, 14 (costed), 16 (ends the window)
    assert a.last_decision.path == "scan" and a.last_decision.count_queries == 4


def test_arbf_shortcut_uses_two_count_queries():
    heap, _ = build_fixed_layout(LAYOUT)
    a = ARBF(heap)
    a.alloc(1, 45)
    assert (a.last_decision.path, a.last_decision.count_queries) == ("shortcut", 2)


# --------------------------------------------------- residual-fate accounting

@pytest.mark.parametrize("name, mode", [("F5", Mode.FIXED), ("F12", Mode.FIXED), ("F4-s0.02", Mode.UNBOUNDED)])
def test_residual_fates_account_for_every_deviation(name, mode):
    gt = generate_trace(FAMILIES[name], seed=1001, n_events=8000)
    capacity = int(gt.peak_live * 1.1) if mode is Mode.FIXED else None
    deviations = []

    class Watch(ARBF):
        def alloc(self, alloc_id, size):
            placed = super().alloc(alloc_id, size)
            deviations.append(self.last_decision.chosen != self.last_decision.best_fit)
            return placed

    d = replay(Watch, gt.events, mode, capacity)["arbf"]
    assert d["deviations"] == sum(deviations)
    assert d["residual_used"] + d["residual_merged"] + d["residual_survived"] == d["deviations"]
    assert d["divergence_rate"] == pytest.approx(sum(deviations) / len(deviations))


@pytest.mark.parametrize("scenario", ["merged_left", "merged_right", "used"])
def test_residual_fate_classification(scenario):
    from framework.replay import _ResidualFates
    heap, (_, right_guard) = build_fixed_layout([("F", 160), ("A", 1), ("F", 170), ("A", 1)])
    a = ARBF(heap)
    for s in [64] * 369 + [100] * 369:
        a._record_request(s)
    fates = _ResidualFates()
    placed = a.alloc(1, 100)                            # deviates to the 170 block
    fates.after_alloc(a.last_decision, 100, placed)
    assert fates.pending == {261: 70}
    if scenario == "used":
        placed = a.alloc(2, 64)                          # lands in the 70 leftover
        fates.after_alloc(a.last_decision, 64, placed)
        assert placed.addr == 261 and (fates.used, fates.merged) == (1, 0)
    else:
        victim = right_guard if scenario == "merged_left" else 1  # block after / before the leftover
        freed = heap.allocation(victim)
        fates.after_free(freed, a.free(victim))
        assert (fates.used, fates.merged) == (0, 1)
    assert fates.pending == {}


# ------------------------------------------- identical traces for all allocators

def recording(cls, log):
    class Recording(cls):
        def alloc(self, alloc_id, size):
            log.append(("A", alloc_id, size))
            return super().alloc(alloc_id, size)

        def free(self, alloc_id):
            log.append(("F", alloc_id))
            return super().free(alloc_id)
    return Recording


@pytest.mark.parametrize("mode", [Mode.FIXED, Mode.UNBOUNDED], ids=lambda m: m.value)
def test_every_allocator_receives_exactly_the_same_event_sequence(mode):
    gt = generate_trace(FAMILIES["F6"], seed=1002, n_events=4000)
    expected = [("A", e.alloc_id, e.size) if e.op is Op.ALLOC else ("F", e.alloc_id) for e in gt.events]
    capacity = int(gt.peak_live * 1.1) if mode is Mode.FIXED else None
    for cls in ALGORITHMS:
        log = []
        replay(recording(cls, log), gt.events, mode, capacity)
        assert log == expected, cls.name


# ------------------------------------------------------ no access to the future

def test_allocators_are_built_from_the_heap_alone():
    for cls in ALGORITHMS:
        assert list(inspect.signature(cls.__init__).parameters) == ["self", "heap"], cls.name


class LazyTrace:
    """A trace that hands out events one at a time and records how many it has produced.
    Random access is forbidden, so replay can only ever see events up to the current one."""

    def __init__(self, events):
        self._events = events
        self.produced = 0

    def __len__(self):
        return len(self._events)

    def __iter__(self):
        for event in self._events:
            self.produced += 1
            yield event

    def __getitem__(self, index):
        raise AssertionError("replay must not index into the trace")


def test_arbf_is_never_handed_an_event_before_its_turn():
    gt = generate_trace(FAMILIES["F12"], seed=1003, n_events=5000)
    lazy = LazyTrace(gt.events)

    class Probe(ARBF):
        calls = 0

        def _check(self):
            Probe.calls += 1
            assert lazy.produced == Probe.calls        # only events up to the current one exist

        def alloc(self, alloc_id, size):
            self._check()
            return super().alloc(alloc_id, size)

        def free(self, alloc_id):
            self._check()
            return super().free(alloc_id)

    replay(Probe, lazy, Mode.FIXED, int(gt.peak_live * 1.1))
    assert Probe.calls == len(gt.events)


@pytest.mark.parametrize("cls", ALGORITHMS, ids=lambda c: c.name)
def test_decisions_do_not_depend_on_future_events(cls):
    gt = generate_trace(FAMILIES["F12"], seed=1004, n_events=6000)
    k = 3000
    changed = [e if i < k or e.op is Op.FREE else alloc(e.alloc_id, 3 * e.size + 1)
               for i, e in enumerate(gt.events)]
    capacity = int(gt.peak_live * 1.1)

    def placements(events):
        out = []

        class Tap(cls):
            def alloc(self, alloc_id, size):
                placed = super().alloc(alloc_id, size)
                out.append(placed)
                return placed
        replay(Tap, make_trace(events), Mode.FIXED, capacity)
        return out

    original, perturbed = placements(gt.events), placements(changed)
    n_prefix = sum(1 for e in gt.events[:k] if e.op is Op.ALLOC)
    assert original[:n_prefix] == perturbed[:n_prefix]          # identical before the change point
    assert original[n_prefix:] != perturbed[n_prefix:]          # the continuation really differs


# -------------------------------------------------------- memory invariants

@pytest.mark.parametrize("mode", [Mode.FIXED, Mode.UNBOUNDED], ids=lambda m: m.value)
@pytest.mark.parametrize("name", list(FAMILIES))
def test_memory_invariants_hold_for_every_family_and_allocator(name, mode):
    gt = generate_trace(FAMILIES[name], seed=1005, n_events=800)
    capacity = int(gt.peak_live * 1.1) if mode is Mode.FIXED else None
    for cls in ALGORITHMS:
        r = replay(cls, gt.events, mode, capacity, check_invariants=True)   # checks after every event
        assert r["successful_allocations"] + r["failed_allocations"] == r["alloc_requests"]
        if mode is Mode.UNBOUNDED:
            assert r["failed_allocations"] == 0
