import type { AlgName, MetricKey } from "./api";

export const ALG_LABEL: Record<AlgName, string> = {
  first_fit: "First Fit",
  best_fit: "Best Fit",
  worst_fit: "Worst Fit",
  next_fit: "Next Fit",
  arbf: "ARBF",
};

/** Canonical order of the engine's ALGORITHMS tuple (tables, selectors). */
export const ALG_ORDER: AlgName[] = ["first_fit", "best_fit", "worst_fit", "next_fit", "arbf"];

/** Series colour follows the algorithm, never its rank (CSS vars defined in styles.css). */
export const ALG_COLOR: Record<AlgName, string> = {
  arbf: "var(--series-1)",
  best_fit: "var(--series-2)",
  first_fit: "var(--series-3)",
  next_fit: "var(--series-4)",
  worst_fit: "var(--series-5)",
};

const grouped = new Intl.NumberFormat("en-US");

export function int(n: number | null | undefined): string {
  return n == null ? "—" : grouped.format(Math.round(n));
}

export function units(n: number | null | undefined): string {
  return n == null ? "—" : `${grouped.format(Math.round(n))} u`;
}

export function pct(x: number | null | undefined, digits = 1): string {
  return x == null ? "—" : `${(100 * x).toFixed(digits)}%`;
}

export function num(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  return Math.abs(x) >= 1000 ? grouped.format(Number(x.toFixed(0))) : x.toFixed(digits);
}

/** Signed percentage-point difference, e.g. "+0.42 pp". */
export function pp(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  const v = 100 * x;
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)} pp`;
}

export function signed(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  return `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(digits)}`;
}

export function pValue(p: number | null | undefined): string {
  if (p == null) return "—";
  return p < 0.001 ? "< 0.001" : p.toFixed(3);
}

export function plural(n: number, word: string, pluralWord = `${word}s`): string {
  return `${grouped.format(n)} ${n === 1 ? word : pluralWord}`;
}

export function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${+(n / 1e3).toFixed(0)}k`;
  if (a >= 1e3) return `${+(n / 1e3).toFixed(1)}k`;
  return `${+n.toFixed(2)}`;
}

/** How each benchmark metric is shown, and how a difference in it is phrased. */
export const METRIC_FMT: Record<MetricKey, { short: string; value: (v: number | null) => string; diff: (d: number | null) => string; noun: string }> = {
  ef_mean: { short: "Ext. fragmentation", value: (v) => pct(v), diff: (d) => pp(d), noun: "time-averaged external fragmentation" },
  success_rate: { short: "Success rate", value: (v) => pct(v, 2), diff: (d) => pp(d), noun: "allocation success rate" },
  failed_allocations: { short: "Failed allocations", value: (v) => int(v), diff: (d) => signed(d, 1), noun: "number of failed allocations" },
  utilization_mean: { short: "Utilization", value: (v) => pct(v), diff: (d) => pp(d), noun: "time-averaged memory utilization" },
  blocks_inspected_mean: { short: "Search cost", value: (v) => num(v), diff: (d) => signed(d), noun: "search cost (blocks inspected per allocation)" },
  free_blocks_mean: { short: "Fragment count", value: (v) => num(v, 1), diff: (d) => signed(d, 1), noun: "time-averaged number of free fragments" },
  largest_free_mean: { short: "Largest free block", value: (v) => units(v), diff: (d) => (d == null ? "—" : `${signed(d, 0)} u`), noun: "time-averaged largest free block" },
};
