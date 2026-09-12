# Breaking ARBF Version 1 — an adversarial study of its operating envelope

*Study date 2026-09-12. Subject: the frozen ARBF V1 in `engine/algorithms/arbf.py` (commit `14ead70`), compared with Best Fit
on the frozen engine. Nothing in `engine/` or `framework/` was modified; `tests/test_adversarial.py` pins the SHA-256 of the
frozen files. Every number below comes from `adversarial/results/` and can be regenerated with `python -m adversarial …`
(see §12). Generated tables: `adversarial/results/tables.md`.*

---

## 0. Answers first

1. **No implementation bug was found.** 4.64 million ARBF decisions (14,359 of them deviations from Best Fit), taken on
   adversarially chosen traces, were compared one by one with an independent brute-force implementation of the spec
   (full scan, no pruning, no index). There were 0 mismatches and 0 violations of P1–P4 or of the history rule.
2. **ARBF can be made to fail arbitrarily often while Best Fit never fails** — but only by a workload built for it. The
   periodic form of the spec's own counterexample gives ARBF 200 failures to Best Fit's 0 (§5). The mirror-image
   workload gives Best Fit 200 failures to ARBF's 0. Neither policy dominates, as expected for online allocators.
3. **On stochastic workloads ARBF is almost never significantly worse than Best Fit.** Across 49 workload families × 6
   memory pressures (3,528 paired runs), no cell differs significantly after FDR correction. A pre-declared confirmatory
   rerun of the 38 most suspicious cells on 48 fresh seeds found **one** cell where ARBF is worse (`trap-0.5` at zero
   heap margin: +8.0% failed allocations), against **six** where it is better (−6% to −30%).
4. **The one reproducible weakness is specific and explained:** *single-residual myopia on composable sizes*. When the
   popular sizes add up to another requested size (40 + 100 = 140), ARBF trades Best Fit's perfectly tileable leftovers
   ({80, 140}) for ones that are not ({100, 120}). There ARBF even loses to a history-blind random deviator making the
   same number of deviations (§9). The same mechanism makes ARBF slightly worse (≈1–2%) during heap warm-up on those
   size sets (§8).
5. **Most apparent "failures" are chaos, not weakness.** The largest relative losses (up to +175% failures) sit on tiny
   baselines (Best Fit failing 0.2–12 times per trace); in four of the eight largest, a mere *tie-break flip of Best Fit
   itself* produces a gap at least as big (F4-s0.05: ARBF +123%, control +158%); none reaches significance, and the five
   that met the follow-up rule all came back "no significant difference" on 48 fresh seeds. The evolutionary search's
   best ARBF-worse workload (fitness 0.94 on its 4 search seeds) shrank to a mean gap of +0.22 on fresh seeds, not
   significant (§7).
6. **ARBF is useful for an identifiable class of workloads:** a few dominant request sizes, best-fit leftovers that
   often land just *below* one of them (within 2×), long-lived placements that pin those leftovers, and tight memory
   (heap margin ≤ 5%). There its history signal is genuinely informative: it beats a history-blind deviator making the
   same number of deviations, and it cuts failed allocations by 6–38% (§10). Outside that class it is Best Fit plus
   1.4× search time, placement-identical on most workloads.

---

## 1. Rules of engagement

* **Not modified:** `engine/algorithms/arbf.py`, the heap/allocator protocol, the frozen workload registry, the
  replay and metric code. The study lives in `adversarial/` and only *generates traces and replays them*.
* **Bug** means a violation of the specification (the docstrings and tests encode it: K(r) = r·(2(n+1) − c(r)),
  lexicographic (K, size, addr) minimum, exact P2/P4/P5, history = last W = 738 requests including FAILs, updated
  after the decision). Anything the spec prescribes is not a bug, however bad its consequences.
* **Classification** of every finding:
  *implementation bug* (violates the spec) · *theoretical weakness* (a property of the V1 design that can make it
  lose) · *expected tradeoff* (a cost the design knowingly pays) · *pathological workload* (needs an adversary that
  knows the algorithm) · *chaotic outlier* (a single-trace loss that a perturbation control reproduces as well).

## 2. Method

**Metrics** (all from the frozen replay). FIXED heap: failed ALLOCs, with the arena H = ⌈(1+margin)·peak live⌉ for
margin ∈ {0, 0.02, 0.05, 0.10, 0.25}. UNBOUNDED heap: peak heap end (footprint). One seed = one trace replayed by every
policy (paired design).

**Why controls are essential.** Allocation is chaotic: one different placement changes the whole future heap. A single
trace where ARBF fails more than Best Fit therefore proves nothing. Two controls calibrate this:

* `best_fit_high`: Best Fit with the opposite tie-break (highest address). The same policy quality; it only differs on
  ties. It measures how large gaps get from perturbation alone.
* `random_window`: a history-blind deviator. It deviates inside exactly ARBF's P4 window, with probability tuned per
  trace so that it makes about as many deviations as ARBF. If ARBF does no better than it, ARBF's *history* is not what
  drives the result.

**Statistics.** Two-sided Wilcoxon signed-rank over seeds, Benjamini–Hochberg FDR across cells. A cell is "worse" or
"better" only if q < 0.05 **and** the effect clears a practical threshold (≥ 5% failures, ≥ 0.5% footprint).

**Stages.**

| stage | what | size |
|---|---|---|
| 0 | differential fuzz vs brute-force spec reference | 776 traces, 4.64 M decisions |
| 1 | systematic sweep: 17 frozen + 32 adversarial families × 6 pressures | 12 seeds, 50k events, 3,528 paired runs |
| 1b | confirmatory rerun of every Stage-1 cell with raw p < 0.10 or \|W−L\| ≥ 6 (rule fixed in advance) | 38 cells × 48 fresh seeds |
| 2 | evolutionary search in both directions (25 generations × 48 genomes, 4 search seeds), then validation | 12 + 12 winners × 24 fresh seeds |
| 3 | rate-matched random-deviator control | 10 families × 3 pressures × 48 seeds |
| 4 | cold start / short traces | 10 families × {100, 300, 1000, 3000} events × 300 seeds |
| 5 | handcrafted pathological constructions with proofs | 7 traces |
| 6 | counterfactual attribution: which single deviation caused a failure | every corpus entry |

The 32 new families cover each requested stress category: distribution change (`shift-*`), stale history (`stale-trap`,
`poison-*`), random sizes (`rand-*`, `pareto`), bimodal (`bimodal-*`, `trap-*`), tiny fragments (`tiny*`), very large
blocks (`huge*`), repetitive (`rep-*`), rapid alloc/free (`churn*`), long-lived (`longlived-*`) and alternating (`alt-*`).
Extreme memory pressure is the margin axis. Cold start and short workloads are Stage 4. Definitions are in
`adversarial/families.py`.

## 3. Implementation bugs: none found

`adversarial/fuzz.py` replays traces chosen to hit the corners: tiny sizes (P4 window ≤ 1), tie-prone size sets (equal-K
candidates), long scan windows, heavy tails, phase switches, histories wrapping the 738-request window many times,
FIXED arenas small enough to fail on 20% of requests, and UNBOUNDED growth. It also covers 12 deviation-heavy study
families. **Every** decision is checked against a reference written from the spec formula alone. The checks: same chosen
block and address; b₀ is Best Fit's block; P1 (n = 0 ⇒ Best Fit); P2 (exact fit wins); P3 (r·(n+2) ≤ 2(n+1)·r_BF);
P4 (deviations have r < 2·r_BF); history = the last W requests, FAILs included; heap invariants.

| fuzz set | traces | decisions | deviations | FAILs | mismatches | violations |
|---|---|---|---|---|---|---|
| random traces | 560 | 2,377,739 | 2,911 | 466,083 | 0 | 0 |
| deviation-heavy families | 216 | 2,262,162 | 11,448 | 64,715 | 0 | 0 |

Checked by hand as well: the P4 cut (r ≥ 2·r_BF can never win, because K(r) ≥ 2r_BF(n+2) > 2r_BF(n+1) ≥ K(r_BF)) and the
P5 shortcut (no history mass in (r_BF, 2r_BF) ⇒ K strictly increasing over the window) are exact. So the pruned
implementation *is* the full-scan argmin. Behaviours that look odd but are **specified**, and therefore not bugs:
FAILed requests enter the history; transient requests count as much as long-lived ones; residuals of 1 are never
avoided.

## 4. Theoretical properties of V1 (exact, from the cost function)

Write Ĝ(x) = c(x)/(n+1). Dividing K by (n+1), ARBF prefers a residual r over Best Fit's r_BF iff r·(2 − Ĝ(r)) <
r_BF·(2 − Ĝ(r_BF)), i.e.

> **Deviation condition:** Ĝ(r) − Ĝ(r_BF) > (1 − r_BF/r) · (2 − Ĝ(r_BF)).

Everything below follows from this condition and the heap mechanics.

**4.1 ARBF acts only on concentrated recent sizes.** The share of recent requests with sizes in (r_BF, r] must exceed the
relative growth of the residual (at least 1 − r_BF/r). Wide or continuous distributions almost never satisfy this.
Measured divergence (share of ALLOCs where ARBF ≠ Best Fit): **0.000–0.025%** on F1, F2, F3, F10, pareto, rand-*,
huge, churn, longlived-mixed; **0.1–1.7%** on the concentrated families (F4-s0.02/0.05, F5–F8, alt-*, rep-*,
shift-disjoint, poison-*, trap-*). The maximum over all 294 cells is 1.65%. Five families (F2, pareto, tiny, tiny-geo,
tiny-mixed) are placement-identical to Best Fit at every pressure on every seed.

**4.2 Small slivers are never avoided.** K(1) ≤ 2(n+1) < (n+2)·r ≤ K(r) for every r ≥ 2, so a residual of 1 always
wins. More generally, a residual can only be traded for one below 2·r_BF, so slivers smaller than half the smallest
popular size are unavoidable (construction `sliver-blind-spot`; tiny families 0% divergence). *Theoretical weakness
(no benefit, never harm).*

**4.3 Losses can be immediate; gains are always deferred.** From a common heap, a deviation leaves Best Fit {b₀−R, b}
and ARBF {b₀, b−R} with b > b₀. Best Fit's largest block b is bigger than both of ARBF's, so any single next request that
ARBF can place, Best Fit can place too. The shortest trace where ARBF fails and Best Fit does not has **5 events**
(`minimal-counterexample`); the shortest mirror image needs **6** (`minimal-mirror`). Both are minimal by the argument
in their docstrings (a deviation needs two free blocks, hence ≥ 3 events, plus the deviating and the failing request);
the asymmetry argument is general, and the tests check it exhaustively for every possible next-request size on the
`minimal-mirror` heap. *Expected tradeoff*: every deviation lowers the largest of the two affected blocks.

**4.4 Single-residual myopia.** K scores only the chosen block's leftover, and only by "does *one* request fit". It
does not see (a) that a leftover can hold several requests (80 = 40 + 40), or (b) what is lost by leaving b₀ unused
and consuming the larger block b. When popular sizes compose (40 + 100 = 140), Best Fit's leftovers tile exactly and
ARBF's do not (§8, §9). *Theoretical weakness.*

**4.5 History lag is bounded by W.** Pre-change requests leave the window after exactly W = 738 requests, so a
permanent change can mislead at most the next 738 decisions. The damage is (number of decisions in the window
where the stale geometry occurs) — in stochastic traffic ≈ 738 × divergence ≈ a handful (§6.2). An adversary that
rebuilds the geometry every cycle turns it into 185 consecutive failures (`stale-history-trap`, exact arithmetic in
§5). *Theoretical weakness; pathological in its strong form.*

**4.6 Requests, not residency.** Ĝ counts requests. A size requested often but freed immediately dominates Ĝ although
it contributes nothing to the live heap. In the poison families, 99–100% of deviations (all seeds analysed) leave a
residual sized for the transient request, and only 17–32% of those residuals are ever used (vs ~97% elsewhere). *Theoretical weakness*; measured cost ≤ ±1.2% footprint,
not significant on 48 seeds.

**4.7 No confidence threshold.** P1 applies only at n = 0. With n = 2 remembered requests, a single sample of 40 makes
ARBF sacrifice the 140-hole in `minimal-counterexample`. In stochastic traffic this is not measurable: deviations need
several holes, holes need frees, and frees start after the history already holds tens to hundreds of requests. Only
`huge-few` (lifetimes exp(5)) produced deviations with n < 50, and there the outcome is balanced (§8). *Expected
tradeoff.*

**4.8 Search cost Θ(D).** Each ALLOC evaluates K once per distinct free size in the P4 window. With D such sizes, the
cost is Θ(D log F) against Best Fit's single index lookup. The `scan-cost-blowup` construction forces ~1,000 K
evaluations per request (23× Best Fit's allocator time). On the benchmark families ARBF inspects up to 5.6× more
blocks, and its median allocator time is 1.41× (p90 1.85×), **even where it never deviates** (F1: 2.8× inspections at
0.018% divergence). *Expected tradeoff.*

## 5. Handcrafted pathological workloads

All in `adversarial/constructions.py`, all exact (asserted by `tests/test_adversarial.py`), all preserved in the corpus.

| construction | events | Best Fit fails | ARBF fails | classification | why |
|---|---|---|---|---|---|
| `minimal-counterexample` | 5 | 0 | 1 | expected tradeoff (cold start) | holes {135,140}, history {135, 40}: K(35) = 210 > K(40) = 200, so the 100 takes the 140-hole and the 140 fails |
| `minimal-mirror` | 6 | 1 | 0 | design case | holes {160,170}, history {160, 64}: K(60) = 360 > K(70) = 350, so ARBF keeps the 160-hole for the 150 |
| `rare-large-trap` | 1,606 | 0 | 200 | pathological (spec counterexample made periodic) | arena [135\|1\|140\|1]; 40s ≥ ¼ of history ⇒ every 100 goes into the 140-hole, every 140 fails |
| `stale-history-trap` | 3,082 | 0 | **185** | theoretical weakness (history lag) | after the change, c₄₀ = 369 − k, deviation iff c₄₀ ≥ 185 ⇒ exactly cycles k = 0…184 fail, then ARBF = Best Fit |
| `reverse-trap` | 2,006 | 200 | 0 | design case | mirror of `rare-large-trap` |
| `sliver-blind-spot` | 2,406 | 0 | 0 | theoretical weakness (no benefit) | residual 1 always wins; 0 deviations although the 18-hole would leave a useful 8 |
| `scan-cost-blowup` | 7,000 | 0 | 0 | expected tradeoff (search cost) | ~1,000 K evaluations per size-1 request; 23× Best Fit's allocator time |

Each trap is **defeated by its mirror**, and each needs an adversary that knows the history rule and rebuilds an exact
hole geometry every cycle. They bound what is *possible*, not what is *typical*.

## 6. Stochastic workloads (Stage 1 + 1b)

### 6.1 Sweep: nothing survives multiple-testing correction

Of the 294 (family, pressure) cells, **31 are placement-identical** (ARBF never deviates on any seed) and **263 show no
significant difference** after BH correction. Not one is significant in either direction. Two facts explain the null:

* ARBF rarely acts (§4.1), and failures themselves become rare as the margin grows: 49 families have any failure at
  0% margin, 34 at 5%, 15 at 10% and 4 at 25% (Best Fit fails 0.77%, 0.27%, 0.18% and 0.08% of requests). The failure
  metric carries most of its information at margin ≤ 5%.
* Where it acts, single-trace gaps are dominated by chaos and by small baselines. The eight largest ARBF-worse cell
  effects have Best Fit failing 0.2–11.6 times per trace on average, and in four of them the tie-break control produces
  a gap at least as large (F4-s0.05 at 5% margin: ARBF +123%, control +158%). UNBOUNDED footprint effects lie within
  ±0.8% everywhere.

### 6.2 Confirmation on 48 fresh seeds

The 38 cells meeting the pre-declared rule were rerun on seeds 1000–1047:

| family | pressure | verdict | ARBF vs Best Fit (failures) | seeds ARBF better/worse/tie | q | tie-break control |
|---|---|---|---|---|---|---|
| stale-trap | 0.02 | **ARBF better** | −23.8% | 40/7/1 | 2.7e-6 | +3.6% (p = 0.18) |
| stale-trap | 0.0 | **ARBF better** | −14.2% | 43/5/0 | 2.7e-8 | +0.6% (p = 0.92) |
| poison-trap | 0.02 | **ARBF better** | −30.1% | 30/14/4 | 0.023 | +30.1% (p = 0.025) |
| poison-trap | 0.0 | **ARBF better** | −17.6% | 36/9/3 | 3.3e-5 | +6.7% (p = 0.19) |
| rep-2 | 0.02 | **ARBF better** | −10.8% | 34/12/2 | 8.4e-4 | +7.8% (p = 0.010) |
| F7-L7380 | 0.02 | **ARBF better** | −6.0% | 26/18/4 | 0.023 | −4.0% (p = 0.035) |
| trap-0.5 | 0.0 | **ARBF worse** | **+8.0%** | 12/34/2 | 8.6e-4 | +6.4% (p = 0.006) |
| stale-trap | unbounded | significant, below threshold | −0.23% footprint | 35/13/0 | 0.004 | +0.1% (p = 0.030) |
| F9 | unbounded | significant, below threshold | −0.02% footprint | 32/15/1 | 0.023 | 0.0% (p = 0.52) |

(Control p-values are raw Wilcoxon, uncorrected. Mean failures per trace: e.g. stale-trap at 0.02, 56.3 → 42.9;
trap-0.5 at 0.0, 61.9 → 66.9.) Note that the tie-break control is *also* worse than Best Fit in `trap-0.5`, so at this
stage the cell could still be a fragile-optimum effect; §9 settles it.

The remaining 29 cells (including every "ARBF worse" hint from Stage 1 in F3, F4-s0.10, rand-uniform, shift-disjoint,
rep-3, F8) are not significant.

**Stale history did not hurt in stochastic traffic** — the family built to exploit it (`stale-trap`: {40,100} for 10W
ticks, then {100,140}) is ARBF's *strongest* win. A deviation timeline explains why. After the change, ARBF's
deviations target the *current* sizes (e.g. a 140 placed to leave 140, a 100 to leave 100; residual used 100%). The
738-request window turns over faster than the heap does (lifetimes exp(1000)), and a bet on the stale size needs a
specific hole geometry that rarely occurs by chance. The strong form needs the adversary of §5.

## 7. Adversarial search (Stage 2)

A genome is a workload: one or two phases of 1–3 size classes (constant, uniform or lognormal sizes; exponential or
transient lifetimes), an optional shift or alternation, and a heap pressure (`adversarial/search.py`). Evolution
maximised the mean ARBF-minus-Best-Fit gap minus half its spread over 4 search seeds. The 12 most distinct winners were
then re-run on 24 fresh seeds.

**ARBF-worse direction — the winner's curse in action.** (Gap = (ARBF failures − Best Fit failures)/(Best Fit failures +
10) per seed; fitness = mean − ½·spread over the 4 search seeds.) The best genome reached fitness 0.94 on its search
seeds and a mean gap of +0.22 on fresh seeds (15 worse / 9 better, p = 0.12). **None of the 12 passes FDR** (best q = 0.095). And on **every** candidate
the tie-break control is *worse than ARBF* (control gap +0.31 to +1.25, p ≤ 0.03). The search did not find an ARBF
weakness. It found workloads where Best Fit's exact address-ordered placement is a **fragile optimum**, so any departure
hurts. In a declared exploratory replication on 48 further seeds, the most promising candidate (`23627427a2bf`: long-lived
lognormal(65.6) objects, then a shift to ~1644-unit short-lived and transient 1497-unit requests, 5% margin) is worse on
32 of 48 seeds, q = 0.029. The control there is three times worse still (+0.76 vs +0.25).

That candidate was then put through the rate-matched control on a *third* block of 48 seeds
(`results/search_worse_informativeness.json`): Best Fit 7,425 failures, ARBF 7,616 (**+2.6%, p = 0.47 — not
significant on this block**), history-blind deviator 6,627; ARBF vs the deviator 21/27 seeds, p = 0.11. So the
search-found effect (a) does not reproduce consistently from one block of seeds to the next, and (b) is
indistinguishable from deviating blindly at the same rate. Classification: **chaotic / expected tradeoff on a workload
where Best Fit is a fragile optimum**, not an ARBF-specific weakness. Contrast this with `trap-0.5`, where ARBF loses
to the same control on 34–38 of 48 seeds (§9): that is what an ARBF-specific weakness looks like.

**ARBF-better direction — the benefit replicates and is ARBF-specific.** Two of the 12 winners validate strongly, and in
both the control is neutral:

| genome | workload | failures Best Fit → ARBF (24 seeds) | seeds ARBF better/worse | q | control |
|---|---|---|---|---|---|
| `6dbea72c34ae` | 34% size 102 exp(2379) + 53% U{176..212} exp(74) + 33% size 72 exp(4); margin 5% | 12,910 → 7,982 (**−38%**) | 23/1 | 2.9e-6 | +0.4% (p = 0.92) |
| `3f73b357d413` | same classes, then a shift to large/transient sizes | 11,425 → 8,384 (**−27%**) | 22/2 | 6.3e-5 | +2.7% (p = 0.97) |

In `6dbea72c34ae` most deviations place long-lived 102s so that the leftover is ≥ 72 (the popular short-lived size)
rather than the 64–68 Best Fit would leave — *just below* a popular size, therefore dead. 77% of those residuals are
used. Best Fit's failures are the medium requests hitting a heap of pinned 64–68 slivers (seed 10000: 557 vs 158
failures).

## 8. Cold start and short workloads (Stage 4)

300 seeds per (family, length, pressure):

* **History cold start is harmless in practice.** Deviations with fewer than 50 remembered requests occurred only in
  `huge-few`, and there ARBF was better and worse about equally often. The 5-event counterexample needs a hand-built
  hole geometry.
* **Heap warm-up is a genuine, but small, weakness on composable sizes.** On {40, 100, 140} sets, 1,000–3,000-event
  traces show ARBF worse with high consistency while the control is balanced: F12 at 3,000 events, 0 margin 59/13
  seeds worse/better, UNBOUNDED 98/15; trap-5 95/26 and 152/25; rep-3 (1,000 events, UNBOUNDED) 23/0. All q ≤ 0.014.
  The history is already full (median n = 738), so this is not small-sample overfitting. The magnitude is tiny: +1.1% to
  +1.9% failures, +0.01% to +0.05% footprint. The culprit is the same pattern as §9 (a 40 placed in a 140-hole instead of
  a 120-hole; 25 of 32 and 26 of 32 analysed failures). At 50k events these families are not significantly different.
* **Short traces on F5 favour ARBF** (3,000 events: 93/51 seeds better/worse at 0 margin, 26/4 at 5% margin).

## 9. Is the history informative? (Stage 3)

The history-blind `random_window` deviator, tuned per trace to make as many deviations as ARBF (mean counts matched to
within 5%, mostly within 1%), separates "benefit or harm from *deviating*" from "benefit or harm from *where ARBF chooses to deviate*". Totals
over 48 seeds (full table in `results/tables.md`):

| family | pressure | ARBF vs Best Fit | random vs Best Fit | ARBF better/worse than random | q (ARBF vs random) |
|---|---|---|---|---|---|
| stale-trap | 0.02 | −25.0% | −8.3% | 39/7 | < 1e-3 |
| stale-trap | 0.0 | −13.7% | −3.6% | 37/10 | < 1e-3 |
| rep-adjacent | 0.0 | −13.9% | −1.0% | 35/10 | < 1e-3 |
| F6 | 0.02 | −12.9% | −3.3% | 33/14 | 0.004 |
| alt-4W | 0.0 | −4.5% | −1.3% | 35/12 | 0.005 |
| F5 | 0.02 | −6.9% | −2.7% | 27/19 | 0.30 |
| F4-s0.02 | 0.02 | +9.6% | +10.1% | 22/21 | 0.92 |
| shift-disjoint | 0.02 | +8.4% | +9.6% | 23/19 | 1.0 |
| poison-90 | 0.02 | +1.5% | −2.3% | 15/29 | 0.35 |
| **trap-0.5** | 0.0 | **+3.8%** | **−8.3%** | **7/38** | < 1e-3 |
| **trap-0.5** | 0.02 | **+12.3%** | **−21.0%** | **8/34** | < 1e-3 |
| **trap-0.5** | unbounded | **+0.16%** (q = 0.009 vs Best Fit) | −0.11% | **11/37** | < 1e-3 |

* Where ARBF helps, **its history is doing the work**: the same number of blind deviations helps much less or not at all.
* In `trap-0.5` the history is **anti-informative**. Random deviation *beats Best Fit*, ARBF loses to Best Fit, and
  ARBF loses to random on 34–38 of 48 seeds. This rules out "deviation per se" or "fragile Best Fit" as the cause: the
  weakness is ARBF's. (The ARBF-vs-Best-Fit gap itself varies by seed block — +3.8% here, q = 0.14; +8.0%, q = 8.6e-4 in
  the confirmatory block of §6.2. The ARBF-vs-random comparison is the stable one, q < 1e-3 at all three pressures.)
* In the frozen benchmark's predicted-benefit family F4-s0.02, ARBF ≈ random ≈ slightly worse than Best Fit (n.s.).

**Why `trap-0.5`?** Its sizes are 40 and 100 (49.75% each) and a rare 140 = 100 + 40 (0.5%). With holes {120, 140}
and a 40 request, K(80) ≈ 80·(2 − 0.5) = 120 > K(100) ≈ 100·(2 − 1.0) = 100, so ARBF takes the 140-hole. Best Fit
leaves {80, 140}, which tile exactly as 40+40 and 100+40; ARBF leaves {100, 120}, and 120 only tiles as 3×40 or as 100
plus a dead 20-sliver. Evidence for this reading:

1. Counterfactual attribution on the worst seeds: the single culprit deviation is "40 into a 140-hole instead of a
   120-hole" in 13 of 24 analysed excess failures (the rest: "100 into 200 instead of 180", or no single culprit).
2. Unusable slivers (< 40 units) track the outcome: ARBF keeps more than Best Fit where it loses (trap-0.5: 55.9 vs
   55.3, random 48.5; trap-5 warm-up: 39.4 vs 38.9) and fewer where it wins (stale-trap: 44.2 vs 47.1).

What the evidence does **not** support: the textbook story that ARBF fails the rare 140s because it destroys the
140-holes. Only 4 of 24 analysed excess failures are 140-requests (20 are 100-requests). The time-averaged count of
holes ≥ 140 is the same under all three policies (6.3–7.3). And culprits precede their failures by thousands of events.
The damage is a *long-range* consequence of the tiling mismatch, not a local sacrifice. That explanation is supported
by the evidence, but not proven.

## 10. Operating envelope

| regime | what ARBF does | evidence |
|---|---|---|
| High-entropy or continuous sizes (uniform, log-uniform, Pareto, lognormal σ ≥ 0.2) | placement-identical or nearly (≤ 0.025% divergence); same outcomes; 1.4–2× search time | §4.1, §6.1, §4.8 |
| Tiny sizes (≤ ~8 units) | never deviates (0.000% on tiny, tiny-geo, tiny-mixed): with r_BF small the deviation condition needs an unreachable history concentration | §4.1, §4.2 |
| Very large blocks, rapid churn, long-lived-only | ≤ 0.06% divergence; no significant difference | §6 |
| Heap margin ≥ 10% | failures rare for both (15 families at 10%, 4 at 25%); no significant difference; footprint within ±0.8% | §6.1 |
| **Few dominant sizes, best-fit leftovers just below a popular size, long-lived pinning, margin ≤ 5%** | **fewer failed allocations: −6% to −38%**, replicated on fresh seeds; history informative | §6.2, §7, §9 |
| Popular sizes that **compose** into another requested size (a + b = c), especially when c is rare | worse: +8% failures at zero margin in steady state, +1–2% during warm-up; loses even to random deviation | §6.2, §8, §9 |
| Adversarially constructed hole geometry | unbounded losses (and, mirrored, unbounded wins) | §5 |

**Is ARBF genuinely useful?** Yes, for a clearly identifiable class. Workloads whose recent requests concentrate on a
few sizes (object pools, fixed-size messages and records), running close to memory capacity, where best-fit leftovers
regularly fall just short of a popular size, and where the objects placed next to those leftovers live long enough to
pin them. There it avoids 6–38% of failed allocations, and the gain comes from the history signal, not from
perturbation. It is **not** a general improvement over Best Fit. On most workloads it is Best Fit with a slower search.
On composable size sets it is measurably, if slightly, worse. And its worst case is unbounded, like any online policy's.

**Practical guidance, if V1 is deployed.** Prefer it only when (a) a handful of sizes carry most requests, (b) memory
is tight, and (c) the sizes do not compose (no popular a + b = c). Budget ~1.4× Best Fit search time (worse with many
distinct free sizes). Do not expect it to fix sliver fragmentation from tiny objects. These are observations about
V1's envelope, not proposals to change it.

## 11. Preserved failures (corpus)

23 traces are preserved, classified as follows — note that **the largest category is "chaotic outlier"**, and that no
entry is an implementation bug:

| classification | entries | examples |
|---|---|---|
| chaotic outlier (family not systematically worse, or search result that did not replicate) | 12 | `outlier-F4-s0.05-0.05` (0 → 14 failures on one seed, cell n.s.), `search-cc7d7e2ce8ee` (340 → 958, did not replicate) |
| theoretical weakness | 5 | `confirmed-trap-0.5-0.0`, `warmup-F12-3000-0.0`, `stale-history-trap`, `sliver-blind-spot` |
| expected tradeoff | 2 | `minimal-counterexample` (5 events), `scan-cost-blowup` (23× search time) |
| design case (ARBF wins) | 2 | `minimal-mirror` (6 events), `reverse-trap` (200 → 0 failures) |
| pathological workload | 1 | `rare-large-trap` (200 → 0 failures, adversary-built geometry) |
| chaotic / fragile Best Fit optimum | 1 | `search-23627427a2bf` (replicated once, then not; ≈ random deviator) |
| **implementation bug** | **0** | — |

`adversarial/corpus/manifest.json` lists every preserved trace. Each entry records its source (construction, family +
seed, or search genome + seed), the gzipped trace (canonical `A id size` / `F id` lines), its SHA-256, the exact arena,
the exact expected outcome for both policies, the classification, the culprit deviation found by counterfactual
replay, and the rate-matched random control. `tests/test_adversarial.py` replays every entry and checks the outcome
bit-for-bit. It also regenerates every generated trace from its seed and checks the hash. See
`adversarial/corpus/CORPUS.md` for the list with explanations.

## 12. Reproducing

```
python -m pytest tests/test_adversarial.py          # frozen-code hashes, constructions, fuzz, corpus
python -m adversarial fuzz                          # Stage 0  (~7 min on 20 cores)
python -m adversarial sweep                         # Stage 1  (~17 min)
python -m adversarial confirm                       # Stage 1b (~10 min)
python -m adversarial search                        # Stage 2  (~25 min, both directions + validation + replication)
python -m adversarial coldstart                     # Stage 4  (~5 min)
python -c "from adversarial import informativeness as i; i.run('adversarial/results/informativeness.jsonl', seeds=range(2000, 2048))"
python -m adversarial summarize                     # results/tables.md
python -m adversarial corpus                        # rebuild corpus/ ; python -m adversarial verify
```

## 13. Limitations

* Synthetic tick-model workloads, not production traces. The families were designed to cover mechanisms, not to match
  a real application's mix.
* FIXED arenas are sized from each trace's own peak live memory. Failures get rare above a 5% margin (15 of 49 families
  at 10%, 4 at 25%), so the failure metric carries most of its information at margin ≤ 5%, and several large relative
  effects rest on baselines of a handful of failures per trace.
* Only Best Fit is used as the comparison policy (plus the two controls); First/Next/Worst Fit were out of scope.
* The random-deviator control matches ARBF's deviation *count*, not the moments at which it deviates, and the match is
  approximate (within ~5%). It bounds the value of the history signal; it is not a perfect counterfactual.
* Failure counts are path-dependent: a FAILed object is never placed, which changes later pressure.
* Timings come from a Python engine and are only meaningful as ratios; inspection counts are the portable measure.
* 12 seeds per sweep cell is low power. The confirmatory stage addresses this for flagged cells only, so small effects
  in unflagged cells cannot be excluded (the sweep bounds them: none reaches significance).
* The §9 mechanism (tiling mismatch) is supported by attribution and sliver counts but not proven; the long lag between
  culprit and failure means other long-range effects may contribute.
