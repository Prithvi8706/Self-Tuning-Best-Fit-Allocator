"""Stage 1 — systematic sweep: every family × pressure × seed, ARBF vs Best Fit.

One trace is generated per (family, seed) and replayed at every pressure level by
Best Fit, ARBF and the noise-floor control (Best Fit with the opposite tie-break).
One JSONL record per (family, seed, pressure).
"""
import json
import time
from multiprocessing import Pool
from typing import Iterable, Sequence

from adversarial.controls import BestFitHigh
from adversarial.families import ALL, get
from adversarial.measure import PRESSURES, compare, mode_and_capacity
from engine.algorithms import ARBF, BestFit
from framework.generator import generate_trace

ALGOS = (BestFit, ARBF, BestFitHigh)


def _job(args) -> list:
    name, seed, n_events, pressures = args
    family = get(name)
    gt = generate_trace(family, seed, n_events)
    out = []
    for pressure in pressures:
        mode, capacity = mode_and_capacity(pressure, gt.peak_live)
        results = compare(gt.events, mode, capacity, ALGOS)
        for r in results.values():
            r.pop("failed_event_indices")
        out.append({"family": name, "category": family.role, "seed": seed, "n_events": n_events,
                    "pressure": pressure, "memory": capacity, "trace_sha256": gt.sha256,
                    "trace_peak_live": gt.peak_live, "results": results})
    return out


def run(path: str, families: Sequence[str] = tuple(ALL), seeds: Iterable[int] = range(12),
        n_events: int = 50_000, pressures=PRESSURES, processes: int = 20) -> None:
    jobs = [(name, seed, n_events, tuple(pressures)) for name in families for seed in seeds]
    start = time.time()
    with Pool(processes) as pool, open(path, "w", encoding="utf-8", newline="\n") as f:
        for k, records in enumerate(pool.imap_unordered(_job, jobs, chunksize=1), 1):
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            if k % 50 == 0:
                print(f"{k}/{len(jobs)} jobs, {time.time() - start:.0f}s", flush=True)
