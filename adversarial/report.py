"""Turn results/*.jsonl into the tables quoted by REPORT.md (results/tables.md + JSON)."""
import json
import os
import statistics
from collections import defaultdict

from adversarial import stats
from adversarial.stats import _p, bh

RESULTS = os.path.join(os.path.dirname(__file__), "results")


def _load_jsonl(name):
    path = os.path.join(RESULTS, name)
    return stats.load(path) if os.path.exists(path) else []


def sweep_cells():
    cells = stats.summarize(_load_jsonl("sweep.jsonl"))
    with open(os.path.join(RESULTS, "sweep_cells.json"), "w", encoding="utf-8") as f:
        json.dump(cells, f, indent=1)
    return cells


def coldstart_cells():
    groups = defaultdict(list)
    for r in _load_jsonl("coldstart.jsonl"):
        groups[(r["family"], r["n_events"], str(r["pressure"]))].append(r)
    rows = []
    for (family, n, pressure), recs in sorted(groups.items()):
        key = "peak" if pressure == "unbounded" else "fails"
        d = [r[f"{key}_arbf"] - r[f"{key}_best_fit"] for r in recs]
        k = [r[f"{key}_best_fit_high"] - r[f"{key}_best_fit"] for r in recs]
        hist = [n_ for r in recs for n_ in r["dev_history_n"]]
        rows.append({"family": family, "n_events": n, "pressure": pressure, "seeds": len(recs),
                     "arbf_worse": sum(x > 0 for x in d), "arbf_better": sum(x < 0 for x in d),
                     "control_worse": sum(x > 0 for x in k), "control_better": sum(x < 0 for x in k),
                     "net_excess": sum(d), "control_net_excess": sum(k), "p": _p(d),
                     "mean_deviations": sum(r["deviations"] for r in recs) / len(recs),
                     "median_history_at_deviation": statistics.median(hist) if hist else None,
                     "deviations_with_history_below_50": sum(h < 50 for h in hist)})
    for r, q in zip(rows, bh([r["p"] for r in rows])):
        r["q"] = q
    with open(os.path.join(RESULTS, "coldstart_cells.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    fixed = [r for recs in groups.values() for r in recs if r["pressure"] != "unbounded"]
    if fixed:
        worst = max(fixed, key=lambda r: (r["fails_arbf"] - r["fails_best_fit"], -r["n_events"]))
        with open(os.path.join(RESULTS, "coldstart_worst.json"), "w", encoding="utf-8") as f:
            json.dump({k: worst[k] for k in ("family", "n_events", "seed", "pressure", "fails_arbf",
                                             "fails_best_fit", "fails_best_fit_high")}, f, indent=1)
    return rows


def informativeness_cells():
    """ARBF vs a history-blind deviator making ~the same number of deviations, per cell."""
    groups = defaultdict(list)
    for r in _load_jsonl("informativeness.jsonl"):
        groups[(r["family"], str(r["pressure"]))].append(r)
    rows = []
    for (family, pressure), recs in sorted(groups.items()):
        rel = (lambda a, b: a / b - 1) if pressure == "unbounded" else (lambda a, b: (a - b) / max(1, b))
        tot = lambda k: sum(r[k] for r in recs)
        a_vs_r = [r["arbf"] - r["random"] for r in recs]
        a_vs_b = [r["arbf"] - r["best_fit"] for r in recs]
        r_vs_b = [r["random"] - r["best_fit"] for r in recs]
        rows.append({"family": family, "pressure": pressure, "seeds": len(recs), "metric": recs[0]["metric"],
                     "arbf_vs_bf": rel(tot("arbf"), tot("best_fit")), "random_vs_bf": rel(tot("random"), tot("best_fit")),
                     "arbf_vs_random": rel(tot("arbf"), tot("random")),
                     "arbf_beats_random": sum(x < 0 for x in a_vs_r), "random_beats_arbf": sum(x > 0 for x in a_vs_r),
                     "p_arbf_vs_random": _p(a_vs_r), "p_arbf_vs_bf": _p(a_vs_b), "p_random_vs_bf": _p(r_vs_b),
                     "deviations_arbf": tot("arbf_deviations") / len(recs),
                     "deviations_random": tot("random_deviations") / len(recs)})
    for key in ("p_arbf_vs_random", "p_arbf_vs_bf", "p_random_vs_bf"):
        for r, q in zip(rows, bh([r[key] for r in rows])):
            r[key.replace("p_", "q_")] = q
    with open(os.path.join(RESULTS, "informativeness_cells.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    return rows


def confirm_cells():
    records = _load_jsonl("confirm.jsonl")
    if not records:
        return []
    cells = stats.summarize(records)
    with open(os.path.join(RESULTS, "confirm_cells.json"), "w", encoding="utf-8") as f:
        json.dump(cells, f, indent=1)
    return cells


def write_tables():
    cells = sweep_cells()
    out = ["# Adversarial study — generated tables", "",
           "W/L/T = seeds where ARBF is better / worse / identical-outcome vs Best Fit. FIXED effect = relative "
           "change in failed ALLOCs summed over seeds; UNBOUNDED effect = geometric-mean change in peak "
           "footprint. q = Benjamini–Hochberg-adjusted Wilcoxon p. Control = Best Fit with the opposite tie-break.",
           "", "## Verdict counts", ""]
    counts = defaultdict(int)
    for c in cells:
        counts[c["verdict"]] += 1
    out += [f"- {v}: {n}" for v, n in sorted(counts.items())]
    out += ["", "## Cells where ARBF differs significantly from Best Fit", "",
            stats.markdown_table(cells, only=("ARBF worse", "ARBF better", "significant, below practical threshold")),
            "", "## All cells", "", stats.markdown_table(cells)]
    conf = confirm_cells()
    if conf:
        counts = defaultdict(int)
        for c in conf:
            counts[c["verdict"]] += 1
        out += ["", "## Confirmatory follow-up (48 fresh seeds, BH within the follow-up set)", ""]
        out += [f"- {v}: {n}" for v, n in sorted(counts.items())]
        out += ["", stats.markdown_table(conf)]
    info = informativeness_cells()
    if info:
        out += ["", "## Is the history informative? ARBF vs a rate-matched history-blind deviator", "",
                "| family | pressure | ARBF vs BF | random vs BF | ARBF vs random | ARBF/random better | "
                "q (ARBF vs random) | q (random vs BF) | devs ARBF | devs random |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for r in info:
            out.append(f"| {r['family']} | {r['pressure']} | {stats.fmt_pct(r['arbf_vs_bf'])} "
                       f"| {stats.fmt_pct(r['random_vs_bf'])} | {stats.fmt_pct(r['arbf_vs_random'])} "
                       f"| {r['arbf_beats_random']}/{r['random_beats_arbf']} | {r['q_arbf_vs_random']:.3g} "
                       f"| {r['q_random_vs_bf']:.3g} | {r['deviations_arbf']:.0f} | {r['deviations_random']:.0f} |")
    cold = coldstart_cells()
    if cold:
        out += ["", "## Cold start / short traces", "",
                "| family | events | pressure | ARBF worse | ARBF better | control worse | control better | "
                "net excess | q | mean devs | median n at deviation |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in cold:
            out.append(f"| {r['family']} | {r['n_events']} | {r['pressure']} | {r['arbf_worse']} | {r['arbf_better']} "
                       f"| {r['control_worse']} | {r['control_better']} | {r['net_excess']} | {r['q']:.3g} "
                       f"| {r['mean_deviations']:.2f} | {r['median_history_at_deviation']} |")
    for label in ("worse", "better", "worse_replication"):
        path = os.path.join(RESULTS, f"search_{label}_validated.json" if label != "worse_replication"
                            else "search_worse_replication.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            val = json.load(f)
        title = {"worse": "Search (ARBF-worse direction), validated on 24 fresh seeds",
                 "better": "Search (ARBF-better direction), validated on 24 fresh seeds",
                 "worse_replication": "Exploratory replication of the borderline ARBF-worse candidates "
                                      "(48 further seeds)"}[label]
        out += ["", f"## {title}", "",
                "| id | workload | search fitness | mean gap | ARBF worse/better/tie | q | control mean gap |",
                "|---|---|---|---|---|---|---|"]
        for v in val:
            out.append(f"| {v['id']} | {v['description']} | {v['search_fitness']:.3f} | {v['mean_gap']:+.4f} "
                       f"| {v['losses']}/{v['wins']}/{v['ties']} | {v['q']:.3g} | {v['control_mean_gap']:+.4f} |")
    with open(os.path.join(RESULTS, "tables.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
