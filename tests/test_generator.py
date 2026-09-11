import pytest

from engine.trace import Op, alloc, free, make_trace
from framework.generator import (generate_trace, load_trace, save_trace, trace_peak_live,
                                 trace_sha256)
from framework.laws import Constant
from framework.workloads import FAMILIES, Family, Process, custom_family


class Scripted(Process):
    """Returns scripted (size, lifetime) pairs in order."""

    def __init__(self, pairs):
        self.pairs = list(pairs)

    def draw(self, tick, rng):
        return self.pairs.pop(0)


def scripted_family(pairs):
    return Family("scripted", "test", "scripted", lambda rng: Scripted(pairs))


def _ids(trace):
    return [(e.op.value[0].upper(), e.alloc_id) for e in trace]


def test_tick_model_event_order():
    gt = generate_trace(custom_family(Constant(5), Constant(3)), seed=0, n_events=10)
    # t0 A0 | t1 A1 | t2 A2 | t3 F0 A3 | t4 F1 A4 | t5 F2 A5 | t6 F3 (stop at 10 events)
    assert _ids(gt.events) == [("A", 0), ("A", 1), ("A", 2), ("F", 0), ("A", 3),
                               ("F", 1), ("A", 4), ("F", 2), ("A", 5), ("F", 3)]
    assert all(e.size == 5 for e in gt.events if e.op is Op.ALLOC)
    assert gt.alloc_count == 6


def test_frees_come_before_the_ticks_alloc_and_in_death_then_id_order():
    # deaths: id0 at 0+3, id1 at 1+2, id2 at 2+1 -> all at tick 3, then id3 is allocated at tick 3
    gt = generate_trace(scripted_family([(1, 3), (1, 2), (1, 1), (1, 9)]), seed=0, n_events=7)
    assert _ids(gt.events) == [("A", 0), ("A", 1), ("A", 2), ("F", 0), ("F", 1), ("F", 2), ("A", 3)]


def test_exact_event_count_and_sequential_ids():
    gt = generate_trace(FAMILIES["F5"], seed=3, n_events=5001)
    assert len(gt.events) == 5001
    allocs = [e.alloc_id for e in gt.events if e.op is Op.ALLOC]
    assert allocs == list(range(len(allocs))) and gt.alloc_count == len(allocs)


def test_alloc_probability_sets_arrival_rate():
    def mean_live(p):
        gt = generate_trace(custom_family(Constant(1), Constant(100)), seed=1, n_events=40000, alloc_prob=p)
        live, total, count = 0, 0, 0
        for i, e in enumerate(gt.events):
            live += 1 if e.op is Op.ALLOC else -1
            if i >= 5000:                              # skip warm-up
                total, count = total + live, count + 1
        return total / count
    assert 99 <= mean_live(1.0) <= 101          # M/G/inf: mean live ≈ p · lifetime
    assert 40 <= mean_live(0.5) <= 60


@pytest.mark.parametrize("kwargs", [dict(alloc_prob=0), dict(alloc_prob=1.5), dict(alloc_prob=True),
                                    dict(n_events=0), dict(seed="1"), dict(seed=True)])
def test_invalid_generator_arguments(kwargs):
    args = dict(seed=1, n_events=10, alloc_prob=1.0)
    args.update(kwargs)
    with pytest.raises(ValueError):
        generate_trace(FAMILIES["F1"], **args)


def test_generation_is_deterministic_and_seed_sensitive():
    a = generate_trace(FAMILIES["F6"], seed=11, n_events=3000)
    b = generate_trace(FAMILIES["F6"], seed=11, n_events=3000)
    c = generate_trace(FAMILIES["F6"], seed=12, n_events=3000)
    assert a == b
    assert a.sha256 != c.sha256


def test_shorter_trace_is_a_prefix_of_longer_trace():
    short = generate_trace(FAMILIES["F11"], seed=2, n_events=1500)
    long = generate_trace(FAMILIES["F11"], seed=2, n_events=4000)
    assert long.events[:1500] == short.events


def test_hash_and_peak_live_are_consistent():
    trace = make_trace([alloc(0, 5), alloc(1, 7), free(0), alloc(2, 9), free(1)])
    assert trace_peak_live(trace) == 16
    assert trace_sha256(trace) == trace_sha256(make_trace(list(trace)))
    assert trace_sha256(trace) != trace_sha256(make_trace([alloc(0, 5), alloc(1, 7), free(1)]))


def test_save_and_load_round_trip(tmp_path):
    gt = generate_trace(FAMILIES["F12"], seed=4, n_events=2000)
    path = tmp_path / "t.trace"
    save_trace(gt, str(path))
    assert load_trace(str(path)) == gt
    lines = path.read_text().splitlines()
    i = next(i for i, line in enumerate(lines) if line.startswith("A "))
    _, alloc_id, size = lines[i].split()
    lines[i] = f"A {alloc_id} {int(size) + 1}"        # tamper with one request size
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        load_trace(str(path))


# ------------------------------------------------------------------- families

def _alloc_sizes(name, seed=1, n=20000):
    return [e.size for e in generate_trace(FAMILIES[name], seed, n).events if e.op is Op.ALLOC]


def test_registry_roles():
    roles = {}
    for f in FAMILIES.values():
        roles.setdefault(f.role, []).append(f.name)
    assert roles == {"N": ["F1", "F2", "F3", "F9", "F10"],
                     "P": ["F4-s0.02", "F4-s0.05", "F4-s0.10", "F5", "F6"],
                     "boundary": ["F4-s0.20", "F4-s0.40"],
                     "X": ["F7-L369", "F7-L7380", "F8", "F11", "F12"]}


@pytest.mark.parametrize("name", list(FAMILIES))
def test_every_family_generates_a_valid_trace(name):
    gt = generate_trace(FAMILIES[name], seed=1, n_events=3000)
    assert make_trace(gt.events) == gt.events and gt.peak_live > 0


def test_family_size_supports():
    assert len(set(_alloc_sizes("F5"))) <= 8
    assert set(_alloc_sizes("F12")) == {40, 100, 140}
    assert all(1 <= s <= 1024 for s in _alloc_sizes("F1"))
    assert all(1 <= s <= 4096 for s in _alloc_sizes("F10"))
    assert all(s <= 16 or 256 <= s <= 1024 or 2048 <= s <= 4096 for s in _alloc_sizes("F11"))
    assert all(21 <= s <= 27 or 360 <= s <= 440 for s in _alloc_sizes("F4-s0.02"))


def test_phase_family_changes_size_set_and_bursty_family_has_bursts():
    assert len(set(_alloc_sizes("F7-L369"))) > 8

    def longest_run(sizes):
        best = run = 1
        for a, b in zip(sizes, sizes[1:]):
            run = run + 1 if a == b else 1
            best = max(best, run)
        return best
    assert longest_run(_alloc_sizes("F6", n=40000)) >= 20
    assert longest_run(_alloc_sizes("F5", n=40000)) < 20
