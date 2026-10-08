// Typed client for the Python simulator API (simulator/server.py).
// Every number the UI shows comes from these responses; nothing is computed
// about allocation here.

export type AlgName = "first_fit" | "best_fit" | "worst_fit" | "next_fit" | "arbf";

export interface AlgorithmInfo { name: AlgName; label: string; rule: string }
export interface FamilyInfo { name: string; role: string; description: string }
export interface CorpusInfo {
  name: string;
  classification: string;
  n_events: number;
  memory: number;
  explanation: string;
  expected: Partial<Record<AlgName, number>>;
}
export interface Meta {
  algorithms: AlgorithmInfo[];
  families: FamilyInfo[];
  corpus: CorpusInfo[];
  corpus_error?: string;
  margins: number[];
  arbf_window: number;
  unit_bytes: number;
  max_events: number;
  experiment_event_budget: number;
}

export type MemorySpec = { margin: number; memory?: undefined } | { memory: number; margin?: undefined };
export type WorkloadSpec =
  | ({ kind: "family"; family: string; seed: number; n_events: number } & MemorySpec)
  | { kind: "trace"; text: string; memory: number }
  | { kind: "corpus"; name: string };

export interface WorkloadInfo {
  kind: "family" | "trace" | "corpus";
  name: string;
  description: string;
  n_events: number;
  alloc_events: number;
  free_events: number;
  capacity: number;
  sha256: string;
  peak_live: number;
  params: Record<string, unknown>;
}

export type EventRow = ["A" | "F", number, string, number | null]; // op, id, label, size
export type Status = "ok" | "fail-frag" | "fail-cap" | "free" | "free-noop" | "initial";

export interface Metrics {
  ef: number | null;
  util: number;
  largest: number;
  free_blocks: number;
  allocated_blocks: number;
  live: number;
  total_free: number;
  allocs: number;
  ok: number;
}

export interface Timeline {
  initial: Metrics;
  max_blocks: number;
  status: Status[];
  inspected: (number | null)[];
  ef: (number | null)[];
  util: number[];
  largest: number[];
  free_blocks: number[];
  allocated_blocks: number[];
  ok: number[];
  allocs: number[];
}

/** One record of framework.replay.replay — the benchmark's own measurement. */
export interface ReplayRecord {
  operation_count: number;
  alloc_requests: number;
  successful_allocations: number;
  failed_allocations: number;
  fragmentation_failures: number;
  capacity_failures: number;
  ef_mean: number | null;
  ef_peak: number | null;
  utilization_mean: number | null;
  utilization_peak: number | null;
  free_blocks_mean: number | null;
  free_blocks_final: number | null;
  largest_free_mean: number | null;
  largest_free_final: number | null;
  blocks_inspected_mean: number | null;
  blocks_inspected_total: number;
  arbf: null | {
    deviations: number;
    divergence_rate: number | null;
    residual_used: number;
    residual_merged: number;
    residual_survived: number;
  };
}

export interface SimSession {
  id: string;
  algorithm: AlgName;
  workload: WorkloadInfo;
  events: EventRow[];
  timeline: Timeline;
  summary: ReplayRecord;
}

export interface BlockRef { addr: number; size: number }
export interface CandidateRow { addr: number; size: number; residual: number; chosen: boolean }
export interface ArbfRow extends CandidateRow {
  fits: number;
  g: number;
  weight: number;
  cost: number;
  evaluated: boolean;
}
export interface ArbfDecision {
  path: "none" | "exact" | "shortcut" | "scan";
  n: number;
  rbf: number | null;
  window: number | null;
  distinct_sizes: number;
  evaluated_count: number;
  count_queries: number;
  best_fit: (BlockRef & { residual: number }) | null;
  deviated: boolean;
  rows: ArbfRow[];
  consistent: boolean;
  reason: string;
}
export interface Decision {
  rule: string;
  fitting_count: number;
  chosen: (BlockRef & { residual: number }) | null;
  rover?: number;
  candidates?: CandidateRow[];
  arbf?: ArbfDecision;
}

export interface Frame {
  index: number;
  status: Status;
  metrics: Metrics;
  blocks: number[]; // flattened [addr, size, id (-1 = free)]
  inspected?: number;
  placed?: BlockRef;
  residual?: BlockRef;
  freed?: BlockRef;
  merged?: BlockRef;
  merged_left?: boolean;
  merged_right?: boolean;
  decision?: Decision;
}

export interface Series { x: number[]; ef: (number | null)[]; util: number[]; largest: number[]; failed: number[] }
export interface MetricInfo { label: string; lower_is_better: boolean }
export type MetricKey =
  | "ef_mean" | "success_rate" | "failed_allocations" | "utilization_mean"
  | "blocks_inspected_mean" | "free_blocks_mean" | "largest_free_mean";

export interface CompareResult {
  workload: WorkloadInfo;
  bucket: number;
  results: { algorithm: AlgName; record: ReplayRecord; metrics: Record<MetricKey, number | null>; series: Series }[];
  metric_info: Record<MetricKey, MetricInfo>;
}

export interface Paired {
  mean_diff: number;
  ci_low: number | null;
  ci_high: number | null;
  n: number;
  better: number;
  worse: number;
  ties: number;
  p: number | null;
}
export interface Described {
  n: number;
  mean?: number;
  median?: number;
  sd?: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  min?: number;
  max?: number;
  values: (number | null)[];
  paired?: Paired | null;
}
export interface ExperimentSpec {
  family: string;
  first_seed: number;
  seed_count: number;
  n_events: number;
  margin?: number;
  memory?: number;
  algorithms: AlgName[];
}
export interface ExperimentResult {
  config: {
    family: string; description: string; role: string; seeds: number[]; n_events: number;
    memory: number | null; margin: number | null; algorithms: AlgName[];
  };
  per_seed: { seed: number; memory_size: number; trace_sha256: string }[];
  stats: Record<MetricKey, Partial<Record<AlgName, Described>>>;
  reference: AlgName | null;
  metric_info: Record<MetricKey, MetricInfo>;
}

export interface Job<T> { state: "running" | "done" | "error"; done: number; total: number; result?: T; error?: string }

export interface TraceValidation {
  ok: boolean;
  issues: { line: number; message: string }[];
  summary?: { events: number; allocs: number; frees: number; peak_live: number; largest_request: number };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new Error(`Simulator backend unavailable (${res.status}). Is \`python -m simulator\` running?`);
  }
  if (!res.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  return body as T;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  validateTrace: (text: string) => post<TraceValidation>("/api/trace/validate", { text }),
  createSim: (workload: WorkloadSpec, algorithm: AlgName) => post<SimSession>("/api/sim", { workload, algorithm }),
  frames: (id: string, start: number, count: number) =>
    request<{ frames: Frame[] }>(`/api/sim/${id}/frames?start=${start}&count=${count}`).then((r) => r.frames),
  compare: (workload: WorkloadSpec, algorithms: AlgName[]) =>
    post<{ job: string }>("/api/compare", { workload, algorithms }),
  experiment: (spec: ExperimentSpec) => post<{ job: string }>("/api/experiment", spec),
  job: <T,>(id: string) => request<Job<T>>(`/api/jobs/${id}`),
};

/** Poll a background job until it finishes, reporting progress. */
export async function waitForJob<T>(id: string, onProgress: (done: number, total: number) => void,
                                    signal: { cancelled: boolean }): Promise<T> {
  for (;;) {
    const job = await api.job<T>(id);
    if (signal.cancelled) throw new Error("cancelled");
    onProgress(job.done, job.total);
    if (job.state === "done") return job.result as T;
    if (job.state === "error") throw new Error(job.error ?? "job failed");
    await new Promise((r) => setTimeout(r, 300));
  }
}
