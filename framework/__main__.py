"""Command line: python -m framework --workloads F5 F12 --seeds 1 2 --margin 0.25 --out results.jsonl"""
import argparse
import sys

from framework.experiment import ALGORITHMS_BY_NAME, ExperimentConfig, run_experiment, write_jsonl
from framework.workloads import FAMILIES


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m framework", description=__doc__)
    p.add_argument("--workloads", nargs="+", help="family names, or 'custom'")
    p.add_argument("--seeds", nargs="+", type=int, help="explicit seeds")
    p.add_argument("--seed-range", nargs=2, type=int, metavar=("FIRST", "LAST"), help="inclusive seed range")
    p.add_argument("--algorithms", nargs="+", default=list(ALGORITHMS_BY_NAME), choices=list(ALGORITHMS_BY_NAME))
    p.add_argument("--mode", choices=["fixed", "unbounded"], default="fixed")
    p.add_argument("--margin", type=float, help="FIXED: H = ceil((1+margin) * trace peak live)")
    p.add_argument("--memory", type=int, help="FIXED: explicit arena size in units")
    p.add_argument("--n-events", type=int, default=400_000)
    p.add_argument("--alloc-prob", type=float, default=1.0)
    p.add_argument("--size-law", help="custom workload size law, e.g. uniform:1:1024")
    p.add_argument("--lifetime-law", help="custom workload lifetime law, e.g. exp:1000")
    p.add_argument("--check-invariants", action="store_true")
    p.add_argument("--out", help="JSONL output file")
    p.add_argument("--list-workloads", action="store_true")
    args = p.parse_args(argv)

    if args.list_workloads:
        for f in FAMILIES.values():
            print(f"{f.name:10} {f.role:9} {f.description}")
        return 0
    if not args.workloads or not args.out or (args.seeds is None) == (args.seed_range is None):
        p.error("--workloads, --out and exactly one of --seeds / --seed-range are required")
    seeds = args.seeds if args.seeds is not None else range(args.seed_range[0], args.seed_range[1] + 1)

    first = True
    for workload in args.workloads:
        for seed in seeds:
            cfg = ExperimentConfig(workload=workload, seed=seed, n_events=args.n_events,
                                   alloc_prob=args.alloc_prob, mode=args.mode, margin=args.margin,
                                   memory=args.memory, algorithms=tuple(args.algorithms),
                                   size_law=args.size_law, lifetime_law=args.lifetime_law,
                                   check_invariants=args.check_invariants)
            records = run_experiment(cfg)
            write_jsonl(records, args.out, append=not first)
            first = False
            for r in records:
                print(f"{r['workload']:9} seed={r['seed']:<4} {r['algorithm']:10} "
                      f"fail={r['failed_allocations']:<6} ef_mean={r['ef_mean']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
