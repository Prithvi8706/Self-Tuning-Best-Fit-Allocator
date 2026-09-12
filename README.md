# Self-Tuning Best-Fit Allocator — ARBF Version 1

A memory-allocator research project: an allocator that **learns from recent request sizes**, a reproducible
benchmark harness, and an adversarial study that maps exactly where it beats Best Fit and where it loses.

### The idea in one formula

Best Fit always takes the smallest block that fits, which can leave a useless sliver behind. ARBF instead looks at
the **leftover** `r` each candidate block would produce and picks the cheapest one by

> **K(r) = r · (2(n+1) − c(r))**  — where `c(r)` = how many of the last **W = 738** requests would fit in `r`.

A leftover that matches a size the program asks for often is cheap; a leftover nothing fits is expensive. So ARBF
will pass over the tightest block if a slightly larger one leaves a leftover that is actually *reusable*.

### The answer, up front

| Question | Answer |
|---|---|
| Is the implementation correct? | **Yes.** 4.64 M decisions checked one-by-one against an independent brute-force implementation of the spec — 0 mismatches, 0 property violations. |
| Does it beat Best Fit? | **On one identifiable class**, yes: a few dominant sizes, leftovers landing just below a popular size, long-lived objects, tight memory → **6–38 % fewer failed allocations**, replicated on fresh seeds. |
| Is it ever worse? | **Yes, and we found why.** When popular sizes add up to another size (40 + 100 = 140) it is ~8 % worse; a purpose-built workload makes it fail 200 times where Best Fit fails 0. |
| Does it matter in general? | **No.** On most workloads it makes the *same placements* as Best Fit (it deviates on ≤ 1.7 % of allocations) for ~1.4× the search time. |

Neither policy dominates: the same construction mirrored makes **Best Fit** fail 200 times where ARBF fails 0.

### What's in the repo

| Path | What it is |
|---|---|
| `engine/` | Heap model + 5 placement policies (first/best/worst/next fit, ARBF). **Frozen** — the tests pin its SHA-256. |
| `framework/` | Trace generator, 17 preregistered workload families, replay + metrics, experiment CLI. |
| `adversarial/` | The study: 32 adversarial workloads, fuzzing, statistics, controls, 23 preserved failures. |
| `adversarial/REPORT.md` | **← read this one.** Full write-up: method, results, mechanisms, operating envelope, limitations. |
| `tests/` | 543 tests: spec properties, differential tests vs brute force, every preserved failure. |

~5,000 lines of Python, no dependencies beyond `pytest` and `scipy` (statistics only).

### Run it

```bash
python -m pytest -q                                   # 543 tests, ~2.5 min
python -m framework --workloads F5 F12 --seeds 1 2 --margin 0.25 \
       --n-events 20000 --out results.jsonl           # benchmark ARBF vs the baselines
python -m adversarial constructions                   # the handcrafted traps, with their exact outcomes
python -m adversarial verify                          # replay all 23 preserved failures
```

### How the study was done

Every claim is paired (same trace for every policy), tested with Wilcoxon signed-rank + Benjamini–Hochberg
correction, and checked against two controls — because allocation is **chaotic**: one different placement changes
the whole future heap, so a single bad trace proves nothing.

1. **Tie-break control** — Best Fit with the opposite tie-break, to size the noise floor.
2. **Rate-matched blind deviator** — deviates as often as ARBF but ignores the history, to test whether ARBF's
   *learning* is doing the work or merely its *deviating*.

Suspicious results were re-run on fresh seeds before being believed; the evolutionary search's best "ARBF is worse"
workload collapsed from a fitness of 0.94 to statistical noise when re-tested, which is exactly why that step exists.

Findings are labelled **implementation bug** / **theoretical weakness** / **expected tradeoff** / **pathological
workload** / **chaotic outlier** — see `adversarial/corpus/CORPUS.md` for all 23, each with the single decision
that caused it, found by counterfactual replay.
