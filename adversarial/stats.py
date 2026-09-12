"""Paired statistics over sweep records: ARBF vs Best Fit per (family, pressure) cell.

FIXED cells compare failed ALLOCs per seed; UNBOUNDED cells compare peak heap end
(footprint). Each seed is one paired observation (same trace for every policy).
Two-sided Wilcoxon signed-rank tests, Benjamini–Hochberg FDR across all cells.
The same statistics for the noise-floor control (Best Fit, opposite tie-break)
say how large gaps become from perturbation alone.
"""
import json
import math
import warnings
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from scipy.stats import wilcoxon

Q_LEVEL = 0.05
MIN_FIXED_REL = 0.05       # practical threshold: >= 5% more (or fewer) failures than Best Fit
MIN_UNB_RATIO = 0.005      # practical threshold: >= 0.5% larger (or smaller) peak footprint


def load(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _p(diffs: Sequence[float]) -> float:
    if not any(diffs):
        return 1.0
    with warnings.catch_warnings():                 # small-sample normal-approximation notices
        warnings.simplefilter("ignore")
        return float(wilcoxon(diffs, zero_method="wilcox", alternative="two-sided").pvalue)


def bh(pvalues: Sequence[float]) -> List[float]:
    """Benjamini–Hochberg adjusted q-values, in input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


def _compare(recs: List[dict], other: str, unbounded: bool) -> dict:
    if unbounded:
        vals = [math.log(r["results"][other]["peak_end"] / r["results"]["best_fit"]["peak_end"]) for r in recs]
        return {"effect": math.exp(sum(vals) / len(vals)) - 1,          # geometric-mean footprint change
                "worst_seed_effect": math.exp(max(vals)) - 1,
                "wins": sum(v < 0 for v in vals), "losses": sum(v > 0 for v in vals),
                "ties": sum(v == 0 for v in vals), "mean_abs": sum(abs(v) for v in vals) / len(vals),
                "p": _p(vals)}
    fb = [r["results"]["best_fit"]["failed_allocations"] for r in recs]
    fo = [r["results"][other]["failed_allocations"] for r in recs]
    d = [o - b for o, b in zip(fo, fb)]
    return {"effect": (sum(fo) - sum(fb)) / max(1, sum(fb)),             # relative change in failures
            "worst_seed_effect": max(d),
            "fails_bf": sum(fb) / len(recs), "fails_other": sum(fo) / len(recs),
            "wins": sum(x < 0 for x in d), "losses": sum(x > 0 for x in d), "ties": sum(x == 0 for x in d),
            "mean_abs": sum(abs(x) for x in d) / len(d), "p": _p(d)}


def summarize(records: List[dict]) -> List[dict]:
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in records:
        groups[(r["family"], str(r["pressure"]))].append(r)
    cells = []
    for (family, pressure), recs in groups.items():
        recs.sort(key=lambda r: r["seed"])
        unb = pressure == "unbounded"
        a = [r["results"]["arbf"]["arbf"] for r in recs]
        allocs = sum(r["results"]["arbf"]["alloc_requests"] for r in recs)
        devs = sum(x["deviations"] for x in a)
        insp_a = sum(r["results"]["arbf"]["blocks_inspected_mean"] for r in recs) / len(recs)
        insp_b = sum(r["results"]["best_fit"]["blocks_inspected_mean"] for r in recs) / len(recs)
        worst = max(recs, key=lambda r: _seed_gap(r, unb))
        cells.append({
            "family": family, "category": recs[0]["category"], "pressure": pressure, "seeds": len(recs),
            "identical_seeds": sum(x["deviations"] == 0 for x in a),
            "divergence_rate": devs / allocs if allocs else 0.0,
            "residual_used_share": sum(x["residual_used"] for x in a) / devs if devs else None,
            "inspected_ratio": insp_a / insp_b if insp_b else None,
            "arbf": _compare(recs, "arbf", unb), "control": _compare(recs, "best_fit_high", unb),
            "worst_seed": worst["seed"], "worst_seed_gap": _seed_gap(worst, unb),
        })
    for key in ("arbf", "control"):
        qs = bh([c[key]["p"] for c in cells])
        for c, q in zip(cells, qs):
            c[key]["q"] = q
    for c in cells:
        c["verdict"] = verdict(c)
    cells.sort(key=lambda c: (c["family"], c["pressure"]))
    return cells


def _seed_gap(r: dict, unbounded: bool) -> float:
    a, b = r["results"]["arbf"], r["results"]["best_fit"]
    if unbounded:
        return a["peak_end"] / b["peak_end"] - 1
    return a["failed_allocations"] - b["failed_allocations"]


def verdict(c: dict) -> str:
    if c["identical_seeds"] == c["seeds"]:
        return "identical"
    s = c["arbf"]
    threshold = MIN_UNB_RATIO if c["pressure"] == "unbounded" else MIN_FIXED_REL
    if s["q"] < Q_LEVEL and abs(s["effect"]) >= threshold:
        return "ARBF worse" if s["effect"] > 0 else "ARBF better"
    if s["q"] < Q_LEVEL:
        return "significant, below practical threshold"
    return "no significant difference"


def fmt_pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{100 * x:+.1f}%"


def markdown_table(cells: List[dict], only: Optional[Sequence[str]] = None) -> str:
    rows = ["| family | category | pressure | verdict | ARBF effect | W/L/T | q | control effect | divergence | "
            "identical seeds |", "|---|---|---|---|---|---|---|---|---|---|"]
    for c in cells:
        if only and c["verdict"] not in only:
            continue
        s, k = c["arbf"], c["control"]
        rows.append(f"| {c['family']} | {c['category']} | {c['pressure']} | {c['verdict']} | {fmt_pct(s['effect'])} "
                    f"| {s['wins']}/{s['losses']}/{s['ties']} | {s['q']:.3g} | {fmt_pct(k['effect'])} "
                    f"| {100 * c['divergence_rate']:.3f}% | {c['identical_seeds']}/{c['seeds']} |")
    return "\n".join(rows)
