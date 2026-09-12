"""Cold start and short workloads: many seeds of very short traces.

ARBF has no confidence threshold: from the second request on, the empirical CDF
of a handful of samples drives decisions (see constructions.minimal_counterexample).
This experiment measures, for short traces, how often ARBF ends up with more or
fewer failed ALLOCs than Best Fit, next to the noise-floor control, and how much
history ARBF had when it deviated.
"""
import json
from multiprocessing import Pool

from adversarial.controls import BestFitHigh
from adversarial.families import get
from adversarial.measure import compare, mode_and_capacity, probe
from engine.algorithms import ARBF, BestFit
from framework.generator import generate_trace

FAMILIES = ("F1", "F5", "F12", "F4-s0.02", "rep-3", "trap-5", "poison-trap", "bimodal-rare-5", "huge-few",
            "tiny-mixed")
LENGTHS = (100, 300, 1000, 3000)
PRESSURES = (0.0, 0.05, 0.10, "unbounded")


def _job(args):
    name, n_events, seed = args
    gt = generate_trace(get(name), seed, n_events)
    out = []
    for pressure in PRESSURES:
        mode, capacity = mode_and_capacity(pressure, gt.peak_live)
        res = compare(gt.events, mode, capacity, (BestFit, ARBF, BestFitHigh))
        pr = probe(gt.events, mode, capacity)
        out.append({"family": name, "n_events": n_events, "seed": seed, "pressure": pressure,
                    **{f"fails_{k}": v["failed_allocations"] for k, v in res.items()},
                    **{f"peak_{k}": v["peak_end"] for k, v in res.items()},
                    "deviations": len(pr.deviations), "dev_history_n": [d.n for d in pr.deviations]})
    return out


def run(path: str, seeds=range(300), processes: int = 20) -> None:
    jobs = [(f, n, s) for f in FAMILIES for n in LENGTHS for s in seeds]
    with Pool(processes) as pool, open(path, "w", encoding="utf-8", newline="\n") as f:
        for recs in pool.imap_unordered(_job, jobs, chunksize=8):
            for r in recs:
                f.write(json.dumps(r) + "\n")
