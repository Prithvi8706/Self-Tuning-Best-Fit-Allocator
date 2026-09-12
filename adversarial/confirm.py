"""Stage 1b — confirmatory follow-up on fresh seeds.

Stage 1 has 12 seeds per cell and ~300 cells, too little power to confirm small
effects after FDR correction. The rule for follow-up was fixed before looking at
follow-up data: every non-identical Stage-1 cell with raw p < 0.10 or
|wins − losses| >= 6 is re-run on 48 fresh seeds (1000–1047), and BH correction
is applied within the follow-up set only.
"""
import json
from collections import defaultdict
from multiprocessing import Pool

from adversarial.sweep import _job

SEEDS = range(1000, 1048)


def select(cells):
    return [c for c in cells if c["verdict"] != "identical"
            and (c["arbf"]["p"] < 0.10 or abs(c["arbf"]["wins"] - c["arbf"]["losses"]) >= 6)]


def _pressure(p: str):
    return p if p == "unbounded" else float(p)


def run(cells, path: str, n_events: int = 50_000, processes: int = 20) -> None:
    per_family = defaultdict(list)
    for c in select(cells):
        per_family[c["family"]].append(_pressure(c["pressure"]))
    jobs = [(fam, seed, n_events, tuple(ps)) for fam, ps in per_family.items() for seed in SEEDS]
    with Pool(processes) as pool, open(path, "w", encoding="utf-8", newline="\n") as f:
        for records in pool.imap_unordered(_job, jobs, chunksize=1):
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
