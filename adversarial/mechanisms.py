"""Why did ARBF fail? Causal and control analyses for one trace.

* explain(): the excess failures (ARBF fails, Best Fit does not), and for the
  first few, the single ARBF deviation whose reversal makes the failure vanish,
  plus the structural check "the deviation split a block that could hold the
  failed request while Best Fit's block could not" (a large-block sacrifice).
* matched_random(): a history-blind deviator (controls.RandomWindow) tuned to
  make about as many deviations as ARBF. If ARBF does no better than it, the
  history signal is not what drives the outcome — deviating at all is.
* timeline(): deviation rate and residual usefulness per window of W ALLOCs,
  to show history lag after a workload change.
"""
from typing import Dict, List, Optional, Sequence

from adversarial.controls import random_window
from adversarial.measure import Deviation, ProbeResult, blame, compare, probe
from engine.algorithms.arbf import W
from engine.memory import Mode


def explain(events, mode: Mode, capacity: Optional[int], max_failures: int = 3,
            max_candidates: int = 40) -> dict:
    res = compare(events, mode, capacity)
    pr = probe(events, mode, capacity)
    excess = sorted(set(res["arbf"]["failed_event_indices"]) - set(res["best_fit"]["failed_event_indices"]))
    fates = pr.fates
    out = {"best_fit_failures": res["best_fit"]["failed_allocations"],
           "arbf_failures": res["arbf"]["failed_allocations"],
           "excess_failures": len(excess),
           "deviations": len(pr.deviations),
           "residual_fates": {"used": fates.count("used"), "merged": fates.count("merged"),
                              "survived": fates.count(None)},
           "mean_history_at_deviation": (sum(d.n for d in pr.deviations) / len(pr.deviations)
                                         if pr.deviations else None),
           "analysed": []}
    by_event = {f.event: f for f in pr.failures}
    for target in excess[:max_failures]:
        f = by_event[target]
        cands = blame(events, mode, capacity, target, pr.deviations, max_candidates)
        culprits = [c for c in cands if c["fixes_failure"]]
        out["analysed"].append({
            "event": target, "request": f.size, "total_free": f.total_free, "largest_free": f.largest_free,
            "kind": "fragmentation" if f.total_free >= f.size else "capacity",
            "candidates_tested": len(cands),
            "culprits": culprits,
            "nearest_culprit": culprits[-1] if culprits else None,
            "sacrifices_before": sum(c["sacrificed_fitting_block"] for c in cands),
        })
    return out


def matched_random(events, mode: Mode, capacity: Optional[int], arbf_deviations: int,
                   reps: int = 5) -> dict:
    """Failures (FIXED) or peak end (UNBOUNDED) of a history-blind deviator making
    ~arbf_deviations deviations, over `reps` independent RNG streams."""
    # opportunities seen at p = 1 differ from those at small p (different trajectory);
    # one refinement step brings the realised deviation count close to ARBF's.
    p = min(1.0, arbf_deviations / max(1, _opportunities(events, mode, capacity, 1.0)))
    realised = _deviations(events, mode, capacity, p)
    if realised:
        p = min(1.0, p * arbf_deviations / realised)
    metric = "peak_end" if mode is Mode.UNBOUNDED else "failed_allocations"
    values, devs = [], []
    for k in range(reps):
        cls = random_window(p, k)
        values.append(compare(events, mode, capacity, (cls,))["random_window"][metric])
        devs.append(_deviations(events, mode, capacity, p, k))
    return {"p": p, "metric": metric, "values": values, "deviations": devs}


def _run_rw(events, mode, capacity, p, seed=0):
    from engine.memory import Heap
    from engine.trace import Op
    a = random_window(p, seed)(Heap(mode, capacity))
    for e in events:
        a.alloc(e.alloc_id, e.size) if e.op is Op.ALLOC else a.free(e.alloc_id)
    return a


def _opportunities(events, mode, capacity, p, seed=0) -> int:
    return _run_rw(events, mode, capacity, p, seed).opportunities


def _deviations(events, mode, capacity, p, seed=0) -> int:
    return _run_rw(events, mode, capacity, p, seed).deviations


def timeline(pr: ProbeResult, n_allocs: int, bucket: int = W) -> List[dict]:
    rows = []
    for start in range(0, n_allocs, bucket):
        idx = [k for k, d in enumerate(pr.deviations) if start <= d.ordinal < start + bucket]
        used = sum(pr.fates[k] == "used" for k in idx)
        fails = sum(start <= f.ordinal < start + bucket for f in pr.failures)
        rows.append({"from_alloc": start, "deviations": len(idx), "residual_used": used, "failures": fails,
                     "mean_c_gain": (sum((pr.deviations[k].c_r - pr.deviations[k].c_rbf) / max(1, pr.deviations[k].n)
                                         for k in idx) / len(idx)) if idx else None})
    return rows
