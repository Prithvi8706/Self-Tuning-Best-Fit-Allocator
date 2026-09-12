"""Stage 2 — adversarial search over a parameterised workload space.

A genome describes a tick-model workload: one or two phases of 1–3 size classes
(each with its own size law, weight and lifetime law; lifetime 1 = transient
"history poison"), an optional sudden shift or periodic alternation between the
phases, and a heap pressure. An evolutionary loop maximises how much worse ARBF
does than Best Fit on a few *search* seeds (sign = +1), or how much better
(sign = −1, to map the other side of the envelope). Winners are then re-run on
fresh *validation* seeds so that the selection effect (winner's curse) cannot
turn chaotic noise into a claimed weakness.
"""
import hashlib
import json
import math
import random
import statistics
import time
from multiprocessing import Pool
from typing import List, Optional

from adversarial.controls import BestFitHigh
from adversarial.families import Schedule, W
from adversarial.measure import compare, mode_and_capacity
from adversarial.stats import _p, bh
from engine.algorithms import ARBF, BestFit
from framework.generator import generate_trace
from framework.laws import Constant, Exponential, LogNormal, Uniform
from framework.workloads import Classes, Family

PRESSURES = (0.0, 0.02, 0.05, 0.10, "unbounded")


# ----------------------------------------------------------------- genomes

def _logu(rng, lo, hi):
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def random_class(rng: random.Random) -> dict:
    kind = rng.choice(("const", "const", "uniform", "lognormal"))
    c = {"kind": kind, "weight": round(rng.uniform(0.05, 1.0), 3)}
    if kind == "const":
        c["value"] = int(_logu(rng, 1, 4096))
    elif kind == "uniform":
        lo = int(_logu(rng, 1, 4096))
        c["lo"], c["hi"] = lo, int(lo * rng.uniform(1.0, 4.0)) + 1
    else:
        c["median"], c["sigma"] = round(_logu(rng, 2, 4096), 1), round(rng.uniform(0.02, 0.5), 3)
    c["life"] = 1 if rng.random() < 0.15 else int(_logu(rng, 2, 30000))
    return c


def random_genome(rng: random.Random) -> dict:
    g = {"pressure": rng.choice(PRESSURES),
         "phases": [[random_class(rng) for _ in range(rng.randint(1, 3))]],
         "schedule": rng.choice(("none", "none", "shift", "alternate"))}
    if g["schedule"] != "none":
        g["phases"].append([random_class(rng) for _ in range(rng.randint(1, 3))])
        g["at"] = int(_logu(rng, W // 8, 20 * W))
    return g


def mutate(g: dict, rng: random.Random) -> dict:
    g = json.loads(json.dumps(g))
    op = rng.randrange(6)
    phase = rng.choice(g["phases"])
    if op == 0:
        g["pressure"] = rng.choice(PRESSURES)
    elif op == 1 and len(phase) < 3:
        phase.append(random_class(rng))
    elif op == 2 and len(phase) > 1:
        phase.pop(rng.randrange(len(phase)))
    elif op == 3:
        g["schedule"] = rng.choice(("none", "shift", "alternate"))
        if g["schedule"] == "none":
            g["phases"] = g["phases"][:1]
            g.pop("at", None)
        else:
            if len(g["phases"]) == 1:
                g["phases"].append([random_class(rng) for _ in range(rng.randint(1, 3))])
            g.setdefault("at", int(_logu(rng, W // 8, 20 * W)))
    else:                                    # jitter one parameter of one class
        c = rng.choice(phase)
        f = math.exp(rng.gauss(0, 0.3))
        if c["kind"] == "const":
            c["value"] = max(1, int(c["value"] * f))
        elif c["kind"] == "uniform":
            c["lo"] = max(1, int(c["lo"] * f))
            c["hi"] = max(c["lo"], int(c["hi"] * math.exp(rng.gauss(0, 0.3))))
        else:
            c["median"] = round(max(1.0, c["median"] * f), 1)
            c["sigma"] = round(min(1.0, max(0.01, c["sigma"] * math.exp(rng.gauss(0, 0.3)))), 3)
        if rng.random() < 0.3:
            c["life"] = 1 if rng.random() < 0.2 else max(2, int(max(2, c["life"]) * math.exp(rng.gauss(0, 0.7))))
        c["weight"] = round(min(1.0, max(0.01, c["weight"] * math.exp(rng.gauss(0, 0.3)))), 3)
        if "at" in g and rng.random() < 0.3:
            g["at"] = max(8, int(g["at"] * math.exp(rng.gauss(0, 0.5))))
    return g


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    child = json.loads(json.dumps(a))
    donor = rng.choice(b["phases"])
    child["phases"][rng.randrange(len(child["phases"]))] = json.loads(json.dumps(donor))
    return child


def genome_id(g: dict) -> str:
    return hashlib.sha256(json.dumps(g, sort_keys=True).encode()).hexdigest()[:12]


# ------------------------------------------------------- genome -> workload

def _size_law(c):
    if c["kind"] == "const":
        return Constant(c["value"])
    if c["kind"] == "uniform":
        return Uniform(c["lo"], c["hi"])
    return LogNormal(c["median"], c["sigma"])


def _process(classes):
    return Classes([(c["weight"], _size_law(c), Constant(1) if c["life"] == 1 else Exponential(c["life"]))
                    for c in classes])


def family(g: dict) -> Family:
    def build(rng):
        procs = [_process(p) for p in g["phases"]]
        if g["schedule"] == "none":
            return procs[0]
        return Schedule([(g["at"], procs[0]), (g["at"], procs[1])], repeat=g["schedule"] == "alternate")
    return Family(f"search:{genome_id(g)}", "search", json.dumps(g, sort_keys=True), build)


def describe(g: dict) -> str:
    def cls(c):
        size = {"const": lambda: f"{c['value']}", "uniform": lambda: f"U{{{c['lo']}..{c['hi']}}}",
                "lognormal": lambda: f"LN({c['median']},{c['sigma']})"}[c["kind"]]()
        life = "transient" if c["life"] == 1 else f"exp({c['life']})"
        return f"{c['weight']}x{size}/{life}"
    phases = [" + ".join(cls(c) for c in p) for p in g["phases"]]
    sched = "" if g["schedule"] == "none" else f" [{g['schedule']} @ {g['at']} ticks]"
    return f"{' || '.join(phases)}{sched}; pressure {g['pressure']}"


# -------------------------------------------------------------- evaluation

def _gap(g: dict, seed: int, n_events: int, with_control: bool = False) -> dict:
    gt = generate_trace(family(g), seed, n_events)
    mode, capacity = mode_and_capacity(g["pressure"], gt.peak_live)
    algos = (BestFit, ARBF, BestFitHigh) if with_control else (BestFit, ARBF)
    res = compare(gt.events, mode, capacity, algos)

    def gap(name):
        a, b = res[name], res["best_fit"]
        if g["pressure"] == "unbounded":
            return math.log(a["peak_end"] / b["peak_end"])
        return (a["failed_allocations"] - b["failed_allocations"]) / (b["failed_allocations"] + 10)

    out = {"seed": seed, "gap": gap("arbf"), "deviations": res["arbf"]["arbf"]["deviations"],
           "fails_bf": res["best_fit"]["failed_allocations"], "fails_arbf": res["arbf"]["failed_allocations"],
           "peak_bf": res["best_fit"]["peak_end"], "peak_arbf": res["arbf"]["peak_end"],
           "sha256": gt.sha256, "memory": capacity}
    if with_control:
        out["control_gap"] = gap("best_fit_high")
    return out


def _evaluate(args):
    g, seeds, n_events, sign = args
    try:
        runs = [_gap(g, s, n_events) for s in seeds]
    except Exception as exc:               # e.g. a law parameter pushed out of range by mutation
        return {"genome": g, "fitness": -math.inf, "error": repr(exc)}
    gaps = [sign * r["gap"] for r in runs]
    fitness = statistics.mean(gaps) - 0.5 * statistics.pstdev(gaps)
    if not any(r["deviations"] for r in runs):
        fitness = -math.inf                # ARBF identical to Best Fit: nothing to find here
    return {"genome": g, "fitness": fitness, "runs": runs}


def evolve(path: str, sign: int = 1, generations: int = 25, population: int = 48, elite: int = 12,
           seeds=(1, 2, 3, 4), n_events: int = 30_000, rng_seed: int = 0, processes: int = 20) -> List[dict]:
    rng = random.Random(f"search:{sign}:{rng_seed}")
    pop = [random_genome(rng) for _ in range(population)]
    seen = {}
    start = time.time()
    with Pool(processes) as pool, open(path, "w", encoding="utf-8", newline="\n") as log:
        for gen in range(generations):
            todo = [g for g in pop if genome_id(g) not in seen]
            for r in pool.imap_unordered(_evaluate, [(g, seeds, n_events, sign) for g in todo]):
                seen[genome_id(r["genome"])] = r
                log.write(json.dumps({"generation": gen, **r}, sort_keys=True) + "\n")
            log.flush()
            ranked = sorted((seen[genome_id(g)] for g in pop), key=lambda r: r["fitness"], reverse=True)
            best = ranked[0]
            print(f"gen {gen}: best fitness {best['fitness']:.4f} {describe(best['genome'])} "
                  f"({time.time() - start:.0f}s)", flush=True)
            parents = [r["genome"] for r in ranked[:elite]]
            pop = list(parents)
            while len(pop) < population:
                if rng.random() < 0.25:
                    pop.append(crossover(rng.choice(parents), rng.choice(parents), rng))
                else:
                    pop.append(mutate(rng.choice(parents), rng))
    return sorted(seen.values(), key=lambda r: r["fitness"], reverse=True)


def _validate_one(args):
    g, seed, n_events = args
    return genome_id(g), _gap(g, seed, n_events, with_control=True)


def validate(candidates: List[dict], seeds=range(10_000, 10_024), n_events: int = 50_000,
             processes: int = 20) -> List[dict]:
    """Re-run candidate genomes on fresh seeds; paired Wilcoxon + BH across candidates."""
    jobs = [(c["genome"], s, n_events) for c in candidates for s in seeds]
    with Pool(processes) as pool:
        results = pool.map(_validate_one, jobs, chunksize=1)
    by_id = {}
    for gid, run in results:
        by_id.setdefault(gid, []).append(run)
    out = []
    for c in candidates:
        runs = sorted(by_id[genome_id(c["genome"])], key=lambda r: r["seed"])
        gaps = [r["gap"] for r in runs]
        ctrl = [r["control_gap"] for r in runs]
        out.append({"genome": c["genome"], "id": genome_id(c["genome"]), "description": describe(c["genome"]),
                    "search_fitness": c["fitness"], "runs": runs,
                    "mean_gap": statistics.mean(gaps), "median_gap": statistics.median(gaps),
                    "losses": sum(x > 0 for x in gaps), "wins": sum(x < 0 for x in gaps),
                    "ties": sum(x == 0 for x in gaps), "p": _p(gaps),
                    "control_mean_gap": statistics.mean(ctrl), "control_p": _p(ctrl)})
    for r, q in zip(out, bh([r["p"] for r in out])):
        r["q"] = q
    return out


def replicate(validated: List[dict], top: int = 2, seeds=range(20_000, 20_048), processes: int = 20) -> List[dict]:
    """Exploratory second replication of the `top` lowest-p validated candidates that
    failed the FDR threshold, on further fresh seeds (declared as exploratory)."""
    borderline = sorted((v for v in validated if v["q"] >= 0.05), key=lambda v: v["p"])[:top]
    cands = [{"genome": v["genome"], "fitness": v["search_fitness"]} for v in borderline]
    return validate(cands, seeds=seeds, processes=processes) if cands else []


def distinct_top(ranked: List[dict], k: int) -> List[dict]:
    """Top-k by fitness, skipping near-duplicates (same description modulo tiny jitter)."""
    picked, keys = [], set()
    for r in ranked:
        if not math.isfinite(r["fitness"]):
            continue
        g = r["genome"]
        key = (g["pressure"], g["schedule"],
               tuple(sorted((c["kind"], round(math.log2(c.get("value", c.get("lo", c.get("median", 1))))),
                             c["life"] == 1) for p in g["phases"] for c in p)))
        if key in keys:
            continue
        keys.add(key)
        picked.append(r)
        if len(picked) == k:
            break
    return picked
