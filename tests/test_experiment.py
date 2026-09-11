import json
import os
import subprocess
import sys

import pytest

import framework.experiment as experiment
from framework.experiment import (ALGORITHMS_BY_NAME, ExperimentConfig, resolve_memory,
                                  run_experiment, strip_timing, write_jsonl)
from framework.generator import GeneratedTrace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_FIELDS = {
    "algorithm", "workload", "seed", "memory_size", "operation_count", "successful_allocations",
    "failed_allocations", "fragmentation_failures", "ef_mean", "ef_peak", "utilization_mean",
    "utilization_peak", "free_blocks_mean", "free_blocks_final", "largest_free_mean",
    "largest_free_final", "blocks_inspected_total", "blocks_inspected_mean", "timing",
    "trace_sha256", "phi", "first_fragmentation_failure", "arbf",
}


def small(**kw):
    base = dict(workload="F12", seed=1001, n_events=3000, margin=0.10)
    base.update(kw)
    return ExperimentConfig(**base)


def test_one_record_per_algorithm_with_all_required_fields():
    records = run_experiment(small())
    assert [r["algorithm"] for r in records] == list(ALGORITHMS_BY_NAME)
    for r in records:
        assert REQUIRED_FIELDS <= set(r)
        assert r["operation_count"] == 3000 and r["workload"] == "F12" and r["seed"] == 1001
    assert [r["arbf"] is not None for r in records] == [n == "arbf" for n in ALGORITHMS_BY_NAME]


def test_trace_is_generated_once_and_shared_by_all_algorithms(monkeypatch):
    calls = []
    real = experiment.generate_trace
    monkeypatch.setattr(experiment, "generate_trace", lambda *a: calls.append(a) or real(*a))
    records = run_experiment(small(mode="unbounded", margin=None))
    assert len(calls) == 1
    assert len({r["trace_sha256"] for r in records}) == 1
    assert len({r["operation_count"] for r in records}) == 1


def test_results_are_deterministic_in_process():
    for cfg in (small(), small(workload="F6", mode="unbounded", margin=None)):
        first = [strip_timing(r) for r in run_experiment(cfg)]
        second = [strip_timing(r) for r in run_experiment(cfg)]
        assert first == second


def test_results_are_identical_across_processes_and_hash_seeds(tmp_path):
    outputs = []
    for hashseed in ("0", "12345"):
        out = tmp_path / f"r{hashseed}.jsonl"
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        subprocess.run([sys.executable, "-m", "framework", "--workloads", "F5", "F11", "--seeds", "1001",
                        "--n-events", "2000", "--margin", "0.1", "--out", str(out)],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        outputs.append([strip_timing(json.loads(line)) for line in out.read_text().splitlines()])
    assert len(outputs[0]) == 10
    assert outputs[0] == outputs[1]


def _gt(peak):
    return GeneratedTrace("x", 0, 1.0, (), "", peak, 0)


def test_memory_from_margin_uses_exact_decimal_arithmetic():
    assert resolve_memory(small(margin=0.1), _gt(1000)) == 1100      # float 1.1*1000 would round up
    assert resolve_memory(small(margin=0.25), _gt(1001)) == 1252
    assert resolve_memory(small(margin=None, memory=777), _gt(1000)) == 777
    assert resolve_memory(small(mode="unbounded", margin=None), _gt(1000)) is None


@pytest.mark.parametrize("kw", [dict(margin=None), dict(memory=100), dict(mode="unbounded"),
                                dict(margin=-0.1), dict(margin=None, memory=0), dict(mode="elastic")])
def test_invalid_memory_configurations(kw):
    with pytest.raises(ValueError):
        resolve_memory(small(**kw), _gt(1000))


def test_custom_workload_and_config_errors():
    records = run_experiment(small(workload="custom", size_law="choice:4,6,9", lifetime_law="exp:50",
                                   algorithms=("best_fit", "arbf")))
    assert records[0]["workload"] == "custom"
    assert records[0]["workload_desc"] == "custom: sizes mix(1:const(4),1:const(6),1:const(9)); lifetimes exp(50.0)"
    with pytest.raises(ValueError):
        run_experiment(small(workload="custom"))
    with pytest.raises(ValueError):
        run_experiment(small(size_law="uniform:1:9"))
    with pytest.raises(ValueError):
        run_experiment(small(workload="F99"))
    with pytest.raises(ValueError):
        run_experiment(small(algorithms=("buddy",)))


def test_jsonl_output_is_machine_readable(tmp_path):
    path = tmp_path / "out.jsonl"
    records = run_experiment(small(algorithms=("best_fit", "arbf")))
    write_jsonl(records, str(path))
    write_jsonl(records, str(path), append=True)
    parsed = [json.loads(line) for line in path.read_text().splitlines()]
    assert parsed == records + records
