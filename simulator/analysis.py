"""Comparisons and multi-seed experiments for the UI.

Comparison: one workload, built once, replayed by every selected policy. The summary
numbers are ``framework.replay.replay`` records; the over-time series come from the
same per-event metrics, bucketed for plotting.

Experiments: ``framework.experiment.run_experiment`` per seed (one trace per seed,
shared by every policy), then descriptive statistics per policy and paired
differences against Best Fit, using the study's Wilcoxon signed-rank helper.
"""
import math
import statistics
from typing import Callable, Dict, List, Optional, Sequence

from engine.memory import Mode
from framework.experiment import ALGORITHMS_BY_NAME, ExperimentConfig, run_experiment
from framework.replay import replay
from framework.workloads import get_family
from simulator.session import Stepper, algorithm_class
from simulator.workload import MAX_EVENTS, Workload, WorkloadError

MAX_POINTS = 400                    # points per over-time series
MAX_EXPERIMENT_EVENTS = 1_000_000   # seeds × events per seed, keeps a run under ~a minute
REFERENCE = "best_fit"

# metric key -> (label, how it is read from a replay record, lower_is_better)
METRICS: Dict[str, tuple] = {
    "ef_mean": ("External fragmentation (time-avg)", lambda r: r["ef_mean"], True),
    "success_rate": ("Allocation success rate",
                     lambda r: r["successful_allocations"] / r["alloc_requests"] if r["alloc_requests"] else None,
                     False),
    "failed_allocations": ("Failed allocations", lambda r: r["failed_allocations"], True),
    "utilization_mean": ("Memory utilization (time-avg)", lambda r: r["utilization_mean"], False),
    "blocks_inspected_mean": ("Search cost (blocks inspected per ALLOC)", lambda r: r["blocks_inspected_mean"], True),
    "free_blocks_mean": ("Free fragments (time-avg count)", lambda r: r["free_blocks_mean"], True),
    "largest_free_mean": ("Largest free block (time-avg, units)", lambda r: r["largest_free_mean"], False),
}


def _algorithms(names: Optional[Sequence[str]]) -> List[str]:
    names = list(names) if names else list(ALGORITHMS_BY_NAME)
    for n in names:
        algorithm_class(n)
    if not names:
        raise WorkloadError("select at least one algorithm")
    return [n for n in ALGORITHMS_BY_NAME if n in names]      # canonical order


def _scalar_metrics(record: dict) -> dict:
    return {k: get(record) for k, (_, get, _) in METRICS.items()}


# --------------------------------------------------------------- comparison

def _series(workload: Workload, algorithm: str, bucket: int) -> dict:
    """Per-bucket means of the per-event metrics (failures: cumulative at bucket end)."""
    stepper = Stepper(workload, algorithm)
    out = {k: [] for k in ("x", "ef", "util", "largest", "failed")}
    acc = {"ef": [], "util": [], "largest": []}
    n = len(workload.events)
    for i in range(n):
        m = stepper.step()["metrics"]
        if m["ef"] is not None:
            acc["ef"].append(m["ef"])
        acc["util"].append(m["util"])
        acc["largest"].append(m["largest"])
        if (i + 1) % bucket == 0 or i == n - 1:
            out["x"].append(i + 1)
            for k, vals in acc.items():
                out[k].append(sum(vals) / len(vals) if vals else None)
                vals.clear()
            out["failed"].append(m["allocs"] - m["ok"])
    return out


def compare(workload: Workload, algorithms: Optional[Sequence[str]],
            progress: Callable[[int, int], None] = lambda done, total: None) -> dict:
    names = _algorithms(algorithms)
    bucket = max(1, math.ceil(len(workload.events) / MAX_POINTS))
    results = []
    for k, name in enumerate(names):
        record = replay(ALGORITHMS_BY_NAME[name], workload.events, Mode.FIXED, workload.capacity)
        record.pop("failed_event_indices", None)
        results.append({"algorithm": name, "record": record, "metrics": _scalar_metrics(record),
                        "series": _series(workload, name, bucket)})
        progress(k + 1, len(names))
    return {"workload": workload.info(), "bucket": bucket, "results": results,
            "metric_info": {k: {"label": v[0], "lower_is_better": v[2]} for k, v in METRICS.items()}}


# -------------------------------------------------------------- experiments

def _t_critical(df: int) -> float:
    try:
        from scipy.stats import t
        return float(t.ppf(0.975, df))
    except ImportError:                     # normal approximation without scipy
        return 1.959964


def _wilcoxon_p(diffs: Sequence[float]) -> Optional[float]:
    try:
        from adversarial.stats import _p    # the study's paired test (two-sided Wilcoxon signed-rank)
    except ImportError:
        return None
    return _p(diffs)


def describe(values: Sequence[float]) -> dict:
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else None
    half = _t_critical(n - 1) * sd / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean": mean, "median": statistics.median(values), "sd": sd,
            "ci_low": None if half is None else mean - half, "ci_high": None if half is None else mean + half,
            "min": min(values), "max": max(values)}


def experiment(spec: dict, progress: Callable[[int, int], None] = lambda done, total: None) -> dict:
    family = get_family(str(spec.get("family")))
    names = _algorithms(spec.get("algorithms"))
    first_seed, seed_count, n_events = (spec.get(k) for k in ("first_seed", "seed_count", "n_events"))
    for key, value, lo, hi in (("first_seed", first_seed, 0, 2**31 - 1), ("seed_count", seed_count, 2, 100),
                               ("n_events", n_events, 100, MAX_EVENTS)):
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise WorkloadError(f"{key} must be an integer in [{lo:,}, {hi:,}], got {value!r}")
    if seed_count * n_events > MAX_EXPERIMENT_EVENTS:
        raise WorkloadError(f"seeds × events must be at most {MAX_EXPERIMENT_EVENTS:,}")
    memory, margin = spec.get("memory"), spec.get("margin")
    if (memory is None) == (margin is None):
        raise WorkloadError("give exactly one of memory (units) or margin")

    seeds = list(range(first_seed, first_seed + seed_count))
    per_seed: List[dict] = []
    for k, seed in enumerate(seeds):
        cfg = ExperimentConfig(workload=family.name, seed=seed, n_events=n_events, margin=margin, memory=memory,
                               algorithms=tuple(names))
        records = run_experiment(cfg)
        per_seed.append({"seed": seed, "memory_size": records[0]["memory_size"],
                         "trace_sha256": records[0]["trace_sha256"],
                         "values": {r["algorithm"]: _scalar_metrics(r) for r in records}})
        progress(k + 1, len(seeds))

    stats: Dict[str, Dict[str, dict]] = {}
    for metric, (_, _, lower_better) in METRICS.items():
        stats[metric] = {}
        for name in names:
            values = [s["values"][name][metric] for s in per_seed]
            defined = [v for v in values if v is not None]
            entry = {"values": values, **(describe(defined) if defined else {"n": 0})}
            if REFERENCE in names and name != REFERENCE:
                entry["paired"] = _paired(per_seed, name, metric, lower_better)
            stats[metric][name] = entry
    return {"config": {"family": family.name, "description": family.description, "role": family.role,
                       "seeds": seeds, "n_events": n_events, "memory": memory, "margin": margin,
                       "algorithms": names},
            "per_seed": [{k: s[k] for k in ("seed", "memory_size", "trace_sha256")} for s in per_seed],
            "stats": stats, "reference": REFERENCE if REFERENCE in names else None,
            "metric_info": {k: {"label": v[0], "lower_is_better": v[2]} for k, v in METRICS.items()}}


def _paired(per_seed: List[dict], name: str, metric: str, lower_better: bool) -> Optional[dict]:
    pairs = [(s["values"][name][metric], s["values"][REFERENCE][metric]) for s in per_seed]
    diffs = [a - b for a, b in pairs if a is not None and b is not None]
    if not diffs:
        return None
    better = sum((d < 0) if lower_better else (d > 0) for d in diffs)
    worse = sum((d > 0) if lower_better else (d < 0) for d in diffs)
    d = describe(diffs)
    return {"mean_diff": d["mean"], "ci_low": d["ci_low"], "ci_high": d["ci_high"], "n": d["n"],
            "better": better, "worse": worse, "ties": len(diffs) - better - worse,
            "p": _wilcoxon_p(diffs)}
