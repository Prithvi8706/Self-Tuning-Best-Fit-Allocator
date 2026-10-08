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
| `engine/` | Heap model + 5 placement policies (first/best/worst/next fit, ARBF). **Frozen** — the tests pin the SHA-256 of ARBF, Best Fit, the heap model and the allocator protocol. |
| `framework/` | Trace generator, 17 preregistered workload families, replay + metrics, experiment CLI. |
| `adversarial/` | The study: 32 adversarial workloads, fuzzing, statistics, controls, 23 preserved failures. |
| `adversarial/REPORT.md` | **← read this one.** Full write-up: method, results, mechanisms, operating envelope, limitations. |
| `docs/ARBF_System_Design_Report.md` (+ PDF) | System design report as submitted on 2026-09-23 (commit `79148c9`), before the simulator existed: its 543-test, ~5,033-line and 61 %-core figures describe that version. Its "250× worst case" for `scan-cost-blowup` is blocks inspected; the time cost is 23× (`adversarial/REPORT.md` §5). |
| `simulator/` + `web/` | Interactive simulator UI (visualization only — it drives the frozen engine and the benchmark, never re-implements a policy). |
| `tests/` | 594 tests: spec properties, differential tests vs brute force, every preserved failure, simulator ↔ benchmark agreement. |

~6,200 lines of Python plus a ~2,800-line React/TypeScript front end in `web/`; the Python needs nothing beyond
`pytest` and `scipy` (statistics only).

### Run it

```bash
python -m pytest -q                                   # 594 tests, ~2.5 min
python -m framework --workloads F5 F12 --seeds 1 2 --margin 0.25 \
       --n-events 20000 --out results.jsonl           # benchmark ARBF vs the baselines
python -m adversarial constructions                   # the handcrafted traps, with their exact outcomes
python -m adversarial verify                          # replay all 23 preserved failures
```

### Simulator UI

A browser front end for demonstrating the allocator: step through any workload and watch the heap, see *why* ARBF
chose each block (its scores, read from the live allocator), compare all five policies on one trace, and run
multi-seed experiments with confidence intervals.

```bash
cd web && npm install && npm run build && cd ..       # once (Node 20.19+ or 22.12+); builds web/dist
python -m simulator                                   # then open http://127.0.0.1:8000
```

* **Simulation** — generated family, hand-written trace (`ALLOC A1 100` / `FREE A1`) or a preserved study trace;
  Run / Pause / Step / Reset / Run all (keys: Space, →, ←, Home, End). Switching algorithm keeps the current operation.
* **Compare** — one trace (shown by its SHA-256), replayed by every selected policy; numbers are
  `framework.replay.replay` records, findings sentences are generated from them.
* **Experiments** — `framework.experiment.run_experiment` per seed; mean, median, SD, 95% CI, and paired differences
  against Best Fit with the study's Wilcoxon signed-rank test.
* **Presentation mode** — larger type, configuration hidden, the ARBF score breakdown shown by default.

For frontend development run `python -m simulator` and `npm run dev` in `web/` (Vite proxies `/api`).
`tests/test_simulator.py` checks that every number the UI shows equals the benchmark's and that every ARBF
explanation agrees with the engine's own decision.

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
workload** / **chaotic outlier** / **design case** (ARBF wins) — see `adversarial/corpus/CORPUS.md` for all 23; for each FIXED-arena ARBF loss
it names the single decision that caused it, found by counterfactual replay.
