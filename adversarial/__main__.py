"""Reproduce the adversarial study stage by stage.

    python -m adversarial fuzz            # implementation-bug hunt (differential vs brute force)
    python -m adversarial sweep           # Stage 1: families × pressures × seeds
    python -m adversarial confirm         # Stage 1b: suspicious cells on 48 fresh seeds
    python -m adversarial search          # Stage 2: evolutionary search (both directions) + validation
    python -m adversarial coldstart       # short traces, many seeds
    python -m adversarial constructions   # handcrafted pathological traces
    python -m adversarial summarize       # tables from results/*.jsonl
    python -m adversarial corpus          # rebuild the preserved-failure corpus
    python -m adversarial verify          # replay every corpus entry and check its outcome

Results go to adversarial/results/. Default sizes are those used for REPORT.md.
"""
import argparse
import json
import os
import sys

RESULTS = os.path.join(os.path.dirname(__file__), "results")


def _path(name: str) -> str:
    os.makedirs(RESULTS, exist_ok=True)
    return os.path.join(RESULTS, name)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m adversarial", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["fuzz", "sweep", "confirm", "search", "coldstart", "constructions",
                                     "summarize", "corpus", "verify"])
    p.add_argument("--processes", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = p.parse_args(argv)

    if args.stage == "fuzz":
        from adversarial import fuzz
        for label, kw in (("random", dict(seeds=40, n_events=8000)), ("families", dict(seeds=6, n_events=20000,
                                                                                       families=True))):
            r = fuzz.run(processes=args.processes, **kw)
            with open(_path(f"fuzz_{label}.json"), "w", encoding="utf-8") as f:
                json.dump(r, f, indent=1)
            print(label, {k: v for k, v in r.items() if k != "violations"}, "violations:", len(r["violations"]))
    elif args.stage == "sweep":
        from adversarial import sweep
        sweep.run(_path("sweep.jsonl"), processes=args.processes)
    elif args.stage == "confirm":
        from adversarial import confirm, report
        confirm.run(report.sweep_cells(), _path("confirm.jsonl"), processes=args.processes)
    elif args.stage == "search":
        from adversarial import search
        for sign, label in ((1, "worse"), (-1, "better")):
            ranked = search.evolve(_path(f"search_{label}.jsonl"), sign=sign, processes=args.processes)
            validated = search.validate(search.distinct_top(ranked, 12), processes=args.processes)
            with open(_path(f"search_{label}_validated.json"), "w", encoding="utf-8") as f:
                json.dump(validated, f, indent=1)
            if sign == 1:
                with open(_path("search_worse_replication.json"), "w", encoding="utf-8") as f:
                    json.dump(search.replicate(validated, processes=args.processes), f, indent=1)
    elif args.stage == "coldstart":
        from adversarial import coldstart
        coldstart.run(_path("coldstart.jsonl"), processes=args.processes)
    elif args.stage == "constructions":
        from adversarial.constructions import CONSTRUCTIONS
        from adversarial.measure import compare
        for name, build in CONSTRUCTIONS.items():
            c = build()
            r = compare(c.events, c.mode, c.capacity)
            print(f"{name:24} BF fails {r['best_fit']['failed_allocations']:4}  ARBF fails "
                  f"{r['arbf']['failed_allocations']:4}  inspected/alloc BF {r['best_fit']['blocks_inspected_mean']:.1f}"
                  f" ARBF {r['arbf']['blocks_inspected_mean']:.1f}  — {c.claim}")
    elif args.stage == "summarize":
        from adversarial import report
        report.write_tables()
    elif args.stage == "corpus":
        from adversarial import build_corpus
        build_corpus.build()
    elif args.stage == "verify":
        from adversarial import corpus
        bad = 0
        for entry in corpus.load_manifest():
            ok, why = corpus.verify(entry)
            bad += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {entry['name']}: {why}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
