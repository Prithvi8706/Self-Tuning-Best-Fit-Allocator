import pytest

from engine.algorithms import BestFit
from engine.memory import Block, Heap, Mode
from engine.trace import Event, Op, TraceError, alloc, free, make_trace, run_trace


def test_make_trace_returns_immutable_tuple():
    trace = make_trace([alloc(1, 5), free(1), alloc(1, 3)])   # id reuse after FREE is valid
    assert isinstance(trace, tuple) and len(trace) == 3


@pytest.mark.parametrize("events", [
    [alloc(1, 0)],
    [alloc(1, -2)],
    [alloc(1, True)],
    [alloc(1, 2.0)],
    [alloc(1, 5), alloc(1, 5)],                        # duplicate live id
    [free(1)],                                         # unknown id
    [alloc(1, 5), free(1), free(1)],                   # double free
    [Event(Op.FREE, 1, 5)],                            # FREE with a size
    [alloc("a", 5)],                                   # non-integer id
    [("alloc", 1, 5)],                                 # not an Event
])
def test_make_trace_rejects_protocol_violations(events):
    with pytest.raises(TraceError):
        make_trace(events)


def test_run_trace_passes_only_id_and_size_to_the_allocator():
    calls = []

    class Recorder:
        def alloc(self, alloc_id, size):
            calls.append(("alloc", alloc_id, size))
            return Block(0, size)

        def free(self, alloc_id):
            calls.append(("free", alloc_id))

    run_trace(Recorder(), make_trace([alloc(1, 5), alloc(2, 3), free(1)]))
    assert calls == [("alloc", 1, 5), ("alloc", 2, 3), ("free", 1)]


def test_run_trace_counts_failures_and_notifies_observer_after_each_event():
    seen = []
    trace = make_trace([alloc(1, 6), alloc(2, 6), free(2), free(1), alloc(3, 10)])
    failures = run_trace(BestFit(Heap(Mode.FIXED, 10)), trace,
                         observer=lambda i, e, placed: seen.append((i, e.op, placed)))
    assert failures == 1
    assert seen == [(0, Op.ALLOC, Block(0, 6)), (1, Op.ALLOC, None), (2, Op.FREE, None),
                    (3, Op.FREE, None), (4, Op.ALLOC, Block(0, 10))]
