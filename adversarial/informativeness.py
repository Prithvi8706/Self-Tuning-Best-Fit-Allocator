"""Stage 3 — is the history signal informative?

For each trace, ARBF is compared with a history-blind deviator that deviates
inside the same P4 window at (approximately) the same number of decisions
(mechanisms.matched_random). If ARBF beats it, ARBF's *choice* of when and
where to deviate carries information; if not, its outcomes are those of
deviating at all.
"""
import json
from multiprocessing import Pool

from adversarial.families import get
from adversarial.measure import compare, mode_and_capacity
from adversarial.mechanisms import matched_random
from engine.algorithms import ARBF, BestFit
from framework.generator import generate_trace

FAMILIES = ("F5", "F6", "F4-s0.02", "F7-L7380", "stale-trap", "alt-4W", "rep-adjacent", "poison-90",
            "trap-0.5", "shift-disjoint")
PRESSURES = (0.0, 0.02, "unbounded")


def _job(args):
    name, seed = args
    gt = generate_trace(get(name), seed, 50_000)
    out = []
    for pressure in PRESSURES:
        mode, capacity = mode_and_capacity(pressure, gt.peak_live)
        res = compare(gt.events, mode, capacity, (BestFit, ARBF))
        devs = res["arbf"]["arbf"]["deviations"]
        rw = matched_random(gt.events, mode, capacity, devs, reps=1)
        metric = rw["metric"]
        out.append({"family": name, "seed": seed, "pressure": pressure, "metric": metric,
                    "best_fit": res["best_fit"][metric], "arbf": res["arbf"][metric], "random": rw["values"][0],
                    "arbf_deviations": devs, "random_deviations": rw["deviations"][0]})
    return out


def _genome_job(args):
    from adversarial import search
    genome, seed = args
    gt = generate_trace(search.family(genome), seed, 50_000)
    mode, capacity = mode_and_capacity(genome["pressure"], gt.peak_live)
    res = compare(gt.events, mode, capacity, (BestFit, ARBF))
    devs = res["arbf"]["arbf"]["deviations"]
    rw = matched_random(gt.events, mode, capacity, devs, reps=1)
    metric = rw["metric"]
    return {"seed": seed, "metric": metric, "best_fit": res["best_fit"][metric], "arbf": res["arbf"][metric],
            "random": rw["values"][0], "arbf_deviations": devs, "random_deviations": rw["deviations"][0]}


def run_genome(genome: dict, path: str, seeds=range(30_000, 30_048), processes: int = 20) -> dict:
    """Same control, applied to a search genome (used for the replicated ARBF-worse workload)."""
    from adversarial.stats import _p
    with Pool(processes) as pool:
        rows = pool.map(_genome_job, [(genome, s) for s in seeds], chunksize=1)
    a = [r["arbf"] - r["random"] for r in rows]
    b = [r["arbf"] - r["best_fit"] for r in rows]
    c = [r["random"] - r["best_fit"] for r in rows]
    total = lambda k: sum(r[k] for r in rows)
    out = {"genome": genome, "rows": rows, "totals": {k: total(k) for k in ("best_fit", "arbf", "random")},
           "deviations": {"arbf": total("arbf_deviations") / len(rows),
                          "random": total("random_deviations") / len(rows)},
           "arbf_better_than_random": sum(x < 0 for x in a), "arbf_worse_than_random": sum(x > 0 for x in a),
           "p_arbf_vs_random": _p(a), "p_arbf_vs_bf": _p(b), "p_random_vs_bf": _p(c)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return out


def run(path: str, seeds=range(2000, 2024), processes: int = 20) -> None:
    jobs = [(f, s) for f in FAMILIES for s in seeds]
    with Pool(processes) as pool, open(path, "w", encoding="utf-8", newline="\n") as f:
        for recs in pool.imap_unordered(_job, jobs, chunksize=1):
            for r in recs:
                f.write(json.dumps(r) + "\n")
