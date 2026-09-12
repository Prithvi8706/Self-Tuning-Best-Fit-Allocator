"""Build corpus/manifest.json from the constructions and the study's results.

Selection (rules fixed before the corpus was built):
  1. every handcrafted construction;
  2. the worst seed (largest ARBF-minus-Best-Fit gap) of every follow-up cell whose
     confirmed direction is "ARBF worse";
  3. the largest single-seed ARBF losses of the whole sweep — 6 FIXED (by excess
     failures relative to Best Fit) and 3 UNBOUNDED (by footprint ratio) — which
     are kept *as chaotic outliers* when their family is not systematically worse;
  4. the worst validation seed of the top search candidate and of every candidate
     sent to the exploratory replication round (labelled by its outcome);
  5. the worst seed of every short-trace cell where ARBF is significantly worse,
     plus the single worst short trace overall (labelled if its cell is not).
Generated traces are cut to the shortest prefix that keeps the gap.
"""
import json
import os
from typing import List, Optional

from adversarial import constructions, corpus, search
from adversarial.families import get
from adversarial.measure import mode_and_capacity
from adversarial.mechanisms import explain, matched_random
from engine.memory import Mode
from framework.generator import generate_trace

RESULTS = os.path.join(os.path.dirname(__file__), "results")


def _json(name):
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def narrate(ex: dict, mode: Mode) -> str:
    """Factual account of the first excess failure and its single-deviation cause."""
    if mode is Mode.UNBOUNDED:
        return (f"{ex['deviations']} deviations; residual fates {ex['residual_fates']}. Footprint gaps have no "
                f"single failing request; see the classification for the mechanism.")
    if not ex["analysed"]:
        return (f"No ALLOC fails under ARBF that does not also fail under Best Fit (ARBF {ex['arbf_failures']} "
                f"failures, Best Fit {ex['best_fit_failures']}); {ex['deviations']} deviations, residual fates "
                f"{ex['residual_fates']}.")
    a = ex["analysed"][0]
    text = (f"{ex['excess_failures']} ALLOCs fail under ARBF but not Best Fit "
            f"({ex['arbf_failures']} vs {ex['best_fit_failures']} failures). First one: event {a['event']}, "
            f"request {a['request']} ({a['kind']} failure: {a['total_free']} units free, largest block "
            f"{a['largest_free']}). ")
    c = a["nearest_culprit"]
    if c is None:
        return text + (f"No single one of the last {a['candidates_tested']} deviations is responsible on its own: "
                       f"the failure is the accumulated (chaotic) effect of a different heap trajectory.")
    d = c["deviation"]
    rbf, r = d["b0"] - d["size"], d["chosen"] - d["size"]
    g_b, g_r = d["c_rbf"] / (d["n"] + 1), d["c_r"] / (d["n"] + 1)
    text += (f"Cause: at event {d['event']} ARBF placed a {d['size']} in a {d['chosen']}-block (residual {r}) "
             f"instead of Best Fit's {d['b0']}-block (residual {rbf}), because Ĝ rose from {g_b:.2f} to {g_r:.2f} "
             f"across that residual range (history n = {d['n']}). Reversing only that decision makes event "
             f"{a['event']} succeed.")
    if c["sacrificed_fitting_block"]:
        text += f" The {d['chosen']}-block was able to hold the failed {a['request']}; Best Fit's block was not."
    return text


def generated_entry(name: str, source: dict, events, mode: Mode, capacity: Optional[int],
                    classification: str, context: dict) -> dict:
    prefix = corpus.best_prefix(events, mode, capacity)
    events = events[:prefix]
    ex = explain(events, mode, capacity)
    control = matched_random(events, mode, capacity, ex["deviations"], reps=3)
    extra = {"analysis": ex, "matched_random_control": control, "context": context}
    return corpus.make_entry(name, source, events, mode, capacity, classification, narrate(ex, mode),
                             prefix=prefix, extra=extra)


def from_family(name, family, seed, pressure, n_events, classification, context):
    gt = generate_trace(get(family), seed, n_events)
    mode, capacity = mode_and_capacity(pressure, gt.peak_live)
    src = {"kind": "family", "family": family, "seed": seed, "n_events": n_events, "pressure": pressure}
    return generated_entry(name, src, gt.events, mode, capacity, classification, context)


def build() -> List[dict]:
    entries = []
    for cname, make in constructions.CONSTRUCTIONS.items():
        c = make()
        ex = explain(c.events, c.mode, c.capacity, max_failures=1)
        entries.append(corpus.make_entry(cname, {"kind": "construction", "name": cname}, c.events, c.mode,
                                         c.capacity, c.classification, f"{c.claim}. {narrate(ex, c.mode)}",
                                         extra={"analysis": ex}))
        print("construction", cname, flush=True)

    sweep = _json("sweep_cells.json") or []
    confirm = {(c["family"], c["pressure"]): c for c in (_json("confirm_cells.json") or [])}
    worse = [c for c in confirm.values() if c["verdict"] == "ARBF worse"]
    for c in worse:
        p = c["pressure"] if c["pressure"] == "unbounded" else float(c["pressure"])
        entries.append(from_family(f"confirmed-{c['family']}-{c['pressure']}".replace("/", "_"), c["family"],
                                   c["worst_seed"], p, 50_000,
                                   "theoretical weakness, confirmed on 48 fresh seeds (single-residual myopia on "
                                   "composable sizes; ARBF also loses to a rate-matched history-blind deviator)",
                                   {"cell": _brief(c)}))
        print("confirmed", c["family"], c["pressure"], flush=True)

    fixed = [c for c in sweep if c["pressure"] != "unbounded" and c["verdict"] != "identical"]
    fixed.sort(key=lambda c: c["worst_seed_gap"] / (1 + c["arbf"]["fails_bf"]), reverse=True)
    unb = sorted((c for c in sweep if c["pressure"] == "unbounded"), key=lambda c: c["worst_seed_gap"],
                 reverse=True)
    for c in fixed[:6] + unb[:3]:
        key = (c["family"], c["pressure"])
        fu = confirm.get(key)
        systematic = fu is not None and fu["verdict"] == "ARBF worse"
        if systematic:
            continue                                   # already preserved as a confirmed weakness
        label = ("chaotic outlier: family not systematically worse (Stage 1 verdict "
                 f"'{c['verdict']}'" + (f", follow-up verdict '{fu['verdict']}'" if fu else "") + ")")
        p = c["pressure"] if c["pressure"] == "unbounded" else float(c["pressure"])
        entries.append(from_family(f"outlier-{c['family']}-{c['pressure']}".replace("/", "_"), c["family"],
                                   c["worst_seed"], p, 50_000, label,
                                   {"cell": _brief(c), "follow_up": _brief(fu) if fu else None}))
        print("outlier", c["family"], c["pressure"], flush=True)

    val = _json("search_worse_validated.json") or []
    rep = {v["id"]: v for v in (_json("search_worse_replication.json") or [])}
    top = sorted(val, key=lambda v: v["mean_gap"], reverse=True)[:1]
    for v in top + [x for x in val if x["id"] in rep and x not in top]:
        run = max(v["runs"], key=lambda r: r["gap"])
        g = v["genome"]
        gt = generate_trace(search.family(g), run["seed"], 50_000)
        mode, capacity = mode_and_capacity(g["pressure"], gt.peak_live)
        r = rep.get(v["id"])
        if r is not None and r["q"] < 0.05:
            label = ("search-found, replicated (exploratory round), but the tie-break control is worse still: "
                     "Best Fit is a fragile optimum here (expected tradeoff)")
        else:
            label = "search-found, did NOT replicate on fresh seeds (winner's curse / chaotic)"
        stats_of = lambda x: {kk: x[kk] for kk in ("mean_gap", "losses", "wins", "ties", "p", "q", "control_mean_gap",
                                                   "control_p")}
        src = {"kind": "search", "genome": g, "seed": run["seed"], "n_events": 50_000}
        entries.append(generated_entry(f"search-{v['id']}", src, gt.events, mode, capacity, label,
                                       {"description": v["description"], "validation": stats_of(v),
                                        "replication": stats_of(r) if r else None}))
        print("search", v["id"], flush=True)

    cold = [c for c in (_json("coldstart_cells.json") or []) if c["pressure"] != "unbounded"
            and c["q"] < 0.05 and c["arbf_worse"] > c["arbf_better"]]
    raw = [json.loads(line) for line in open(os.path.join(RESULTS, "coldstart.jsonl"), encoding="utf-8")]
    for c in cold:
        runs = [r for r in raw if (r["family"], r["n_events"], str(r["pressure"])) ==
                (c["family"], c["n_events"], c["pressure"])]
        worst = max(runs, key=lambda r: (r["fails_arbf"] - r["fails_best_fit"], -r["seed"]))
        entries.append(from_family(f"warmup-{c['family']}-{c['n_events']}-{c['pressure']}", c["family"],
                                   worst["seed"], float(c["pressure"]), c["n_events"],
                                   "theoretical weakness (single-residual myopia on composable sizes; "
                                   "heap warm-up; statistically consistent but ~1-2% in magnitude)",
                                   {"coldstart_cell": c}))
        print("warmup", c["family"], c["n_events"], flush=True)
    worst = _json("coldstart_worst.json")
    if worst and not any(c["family"] == worst["family"] and c["n_events"] == worst["n_events"] for c in cold):
        entries.append(from_family(f"short-{worst['family']}-{worst['n_events']}", worst["family"], worst["seed"],
                                   float(worst["pressure"]), worst["n_events"],
                                   "chaotic outlier: largest short-trace loss, cell not significant",
                                   {"coldstart": worst}))
    corpus.save_manifest(entries)
    write_index(entries)
    return entries


def write_index(entries: List[dict]) -> None:
    """corpus/CORPUS.md: one section per preserved trace."""
    out = ["# Preserved failures", "",
           "Generated by `python -m adversarial corpus` from `manifest.json`; verified by "
           "`python -m adversarial verify` and `tests/test_adversarial.py`. Outcomes are exact and deterministic.", ""]
    for e in entries:
        bf, a = e["expected"]["best_fit"], e["expected"]["arbf"]
        src = e["source"]
        if src["kind"] == "construction":
            how = f"`adversarial.constructions.{src['name'].replace('-', '_')}()`"
        elif src["kind"] == "family":
            how = (f"family `{src['family']}`, seed {src['seed']}, {src['n_events']} events, pressure {src['pressure']}"
                   f" (first {e['prefix']} events kept)")
        else:
            how = f"search genome (see manifest), seed {src['seed']}, first {e['prefix']} of {src['n_events']} events"
        arena = "UNBOUNDED" if e["mode"] == "unbounded" else f"FIXED arena {e['memory']}"
        metric = ("peak heap end" if e["mode"] == "unbounded" else "failed ALLOCs")
        key = "peak_end" if e["mode"] == "unbounded" else "failed_allocations"
        out += [f"## {e['name']}", "",
                f"* **Classification:** {e['classification']}",
                f"* **Outcome ({metric}):** Best Fit {bf[key]}, ARBF {a[key]} — {arena}, {e['n_events']} events",
                f"* **Reproduce:** {how}; trace `{e['trace_file']}` (sha256 `{e['sha256'][:16]}…`)"]
        ctl = e.get("matched_random_control")
        if ctl:
            out.append(f"* **History-blind deviator, same deviation count:** {ctl['metric']} = {ctl['values']}")
        out += ["", e["explanation"], ""]
    with open(os.path.join(corpus.HERE, "CORPUS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))


def _brief(c):
    if c is None:
        return None
    return {k: c[k] for k in ("family", "pressure", "verdict", "seeds", "divergence_rate", "worst_seed")} | {
        "arbf": {k: c["arbf"][k] for k in ("effect", "wins", "losses", "ties", "p", "q")},
        "control": {k: c["control"][k] for k in ("effect", "p")}}
