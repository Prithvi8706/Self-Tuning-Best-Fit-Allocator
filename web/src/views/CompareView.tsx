import { useRef, useState } from "react";
import { api, waitForJob, type AlgName, type CompareResult, type Meta, type MetricKey } from "../api";
import { Legend, LineChart } from "../components/LineChart";
import { WorkloadForm, toSpec, type WorkloadDraft } from "../components/WorkloadForm";
import { ALG_COLOR, ALG_LABEL, ALG_ORDER, compact, int, num, pct, plural, pp, units } from "../format";

interface Props {
  meta: Meta;
  draft: WorkloadDraft;
  setDraft: (d: WorkloadDraft) => void;
  active: boolean;
}

export function AlgorithmChecks({ value, onChange }: { value: AlgName[]; onChange: (v: AlgName[]) => void }) {
  return (
    <div className="field" role="group" aria-label="Algorithms">
      {ALG_ORDER.map((a) => (
        <label className="check" key={a}>
          <input type="checkbox" checked={value.includes(a)}
                 onChange={(e) => onChange(e.target.checked ? ALG_ORDER.filter((x) => x === a || value.includes(x))
                                                            : value.filter((x) => x !== a))} />
          <span className="swatch" style={{ background: ALG_COLOR[a] }} />
          {ALG_LABEL[a]}
        </label>
      ))}
    </div>
  );
}

export function CompareView({ meta, draft, setDraft, active }: Props) {
  const [algorithms, setAlgorithms] = useState<AlgName[]>(ALG_ORDER);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const [error, setError] = useState<string | null>(null);
  const token = useRef({ cancelled: false });

  async function run() {
    token.current.cancelled = true;
    const signal = { cancelled: false };
    token.current = signal;
    setRunning(true);
    setError(null);
    setProgress([0, algorithms.length]);
    try {
      const { job } = await api.compare(toSpec(draft), algorithms);
      const res = await waitForJob<CompareResult>(job, (d, t) => setProgress([d, t]), signal);
      setResult(res);
    } catch (e) {
      if (!signal.cancelled) setError((e as Error).message);
    } finally {
      if (!signal.cancelled) setRunning(false);
    }
  }

  return (
    <div className="view" hidden={!active}>
      <aside className="sidebar">
        <div className="side-section">
          <h2 className="side-title">Workload</h2>
          <WorkloadForm meta={meta} draft={draft} onChange={setDraft} />
          <p className="hint" style={{ margin: 0 }}>Shared with the Simulation tab. The trace is generated once and
            replayed by every selected algorithm.</p>
        </div>
        <div className="side-section">
          <h2 className="side-title">Algorithms</h2>
          <AlgorithmChecks value={algorithms} onChange={setAlgorithms} />
          <button className="btn btn-primary btn-block" onClick={run} disabled={running || algorithms.length === 0}>
            {running ? "Running…" : "Run comparison"}
          </button>
          {running && (
            <div style={{ marginTop: "0.6rem" }}>
              <div className="progress"><div style={{ width: `${progress[1] ? (100 * progress[0]) / progress[1] : 0}%` }} /></div>
              <div className="hint" style={{ marginTop: "0.3rem" }}>{progress[0]} of {progress[1]} algorithms replayed</div>
            </div>
          )}
          {error && <div className="error-box" style={{ marginTop: "0.6rem" }}><b>Comparison failed.</b> {error}</div>}
        </div>
      </aside>
      <main className="main" style={{ opacity: running && result ? 0.6 : 1 }}>
        {!result ? (
          <div className="empty">
            <b>{running ? "Running comparison…" : "No comparison yet"}</b>
            Choose a workload and press Run comparison. Every algorithm replays the same trace.
          </div>
        ) : <CompareBody result={result} />}
      </main>
    </div>
  );
}

function bestOf(result: CompareResult, key: MetricKey): Set<AlgName> {
  const lower = result.metric_info[key].lower_is_better;
  const vals = result.results.map((r) => r.metrics[key]).filter((v): v is number => v != null);
  if (vals.length < 2) return new Set();
  const best = lower ? Math.min(...vals) : Math.max(...vals);
  if (vals.every((v) => v === best)) return new Set();     // all tied: nothing to highlight
  return new Set(result.results.filter((r) => r.metrics[key] === best).map((r) => r.algorithm));
}

function CompareBody({ result }: { result: CompareResult }) {
  const w = result.workload;
  const rs = result.results;
  const columns: { key: MetricKey; label: string; fmt: (v: number | null) => string; title: string }[] = [
    { key: "failed_allocations", label: "Failed", fmt: int, title: "ALLOC requests that found no fitting block" },
    { key: "success_rate", label: "Success", fmt: (v) => pct(v, 2), title: "Successful ÷ requested allocations" },
    { key: "ef_mean", label: "Avg ext. frag.", fmt: (v) => pct(v), title: "Time-average of 1 − largest free ÷ total free" },
    { key: "utilization_mean", label: "Avg utilization", fmt: (v) => pct(v), title: "Time-average of live memory ÷ arena" },
    { key: "largest_free_mean", label: "Avg largest free", fmt: units, title: "Time-average size of the largest free block" },
    { key: "free_blocks_mean", label: "Avg free blocks", fmt: (v) => num(v, 1), title: "Time-average number of free fragments" },
    { key: "blocks_inspected_mean", label: "Search cost", fmt: (v) => num(v), title: "Free blocks inspected per allocation" },
  ];
  const best = Object.fromEntries(columns.map((c) => [c.key, bestOf(result, c.key)])) as Record<MetricKey, Set<AlgName>>;
  const legend = rs.map((r) => ({ key: r.algorithm, label: ALG_LABEL[r.algorithm], color: ALG_COLOR[r.algorithm] }));
  const x = rs[0]?.series.x ?? [];
  const lineSeries = (pick: (s: CompareResult["results"][number]["series"]) => (number | null)[]) =>
    rs.map((r) => ({ key: r.algorithm, label: ALG_LABEL[r.algorithm], color: ALG_COLOR[r.algorithm], values: pick(r.series) }));
  const few = rs.length <= 4;

  return (
    <>
      <div className="page-title">
        <h1>Comparison · {w.name}</h1>
        <span className="sub">{int(w.n_events)} operations · arena {units(w.capacity)} · peak live {units(w.peak_live)}</span>
      </div>
      <p className="note" style={{ marginTop: "0.3rem" }}>
        Same trace for every algorithm — SHA-256 <span className="mono">{w.sha256.slice(0, 16)}…</span>.
        {" "}{w.description}
      </p>

      <section className="panel" aria-label="Findings">
        <div className="panel-h"><h2>What the measurements say</h2></div>
        <div className="panel-b">
          <ul className="findings">{findings(result).map((f, i) => <li key={i}>{f}</li>)}</ul>
          <p className="note" style={{ margin: "0.5rem 0 0" }}>
            This is one trace. Allocation is chaotic — one different placement reshapes the rest of the run — so a
            difference here is not evidence on its own. Use <b>Experiments</b> to check it across seeds.
          </p>
        </div>
      </section>

      <section className="panel" aria-label="Comparison table">
        <div className="panel-h"><h2>Results</h2><div className="aside">bold = best in column (ties not highlighted)</div></div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Algorithm</th>
                {columns.map((c) => <th key={c.key} className="r" title={c.title}>{c.label}</th>)}
                <th className="r" title="ARBF only: allocations where ARBF picked a different block than Best Fit's rule would in the same heap">Deviations</th>
              </tr>
            </thead>
            <tbody>
              {rs.map((r) => (
                <tr key={r.algorithm}>
                  <td><span className="legend-item"><span className="swatch" style={{ background: ALG_COLOR[r.algorithm] }} />
                    {ALG_LABEL[r.algorithm]}</span></td>
                  {columns.map((c) => (
                    <td key={c.key} className={`r${best[c.key].has(r.algorithm) ? " best" : ""}`}>{c.fmt(r.metrics[c.key])}</td>
                  ))}
                  <td className="r">{r.record.arbf ? `${int(r.record.arbf.deviations)} (${pct(r.record.arbf.divergence_rate, 2)})` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="panel" style={{ padding: "0.6rem 0.85rem" }}>
        <Legend items={legend} />
        <p className="note" style={{ margin: "0.3rem 0 0" }}>
          Each point is the mean over {plural(result.bucket, "operation")}.
        </p>
      </div>

      <div className="grid-charts">
        <ChartPanel title="External fragmentation over time" sub="1 − largest free ÷ total free (lower is better)">
          <LineChart x={x} series={lineSeries((s) => s.ef)} yDomain={[0, 1]} endLabels={few}
                     yFormat={(v) => `${Math.round(v * 100)}%`} xLabel="Operation" />
        </ChartPanel>
        <ChartPanel title="Memory utilization over time" sub="Live memory ÷ arena">
          <LineChart x={x} series={lineSeries((s) => s.util)} yDomain={[0, 1]} endLabels={few}
                     yFormat={(v) => `${Math.round(v * 100)}%`} xLabel="Operation" />
        </ChartPanel>
        <ChartPanel title="Largest free block over time" sub="Units (higher means larger requests can still be served)">
          <LineChart x={x} series={lineSeries((s) => s.largest)} endLabels={few} yFormat={compact} xLabel="Operation" />
        </ChartPanel>
        <ChartPanel title="Allocation failures" sub="Failed ALLOC requests over the whole run">
          <FailureBars result={result} />
        </ChartPanel>
      </div>
    </>
  );
}

function ChartPanel({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-b">
        <h3 className="chart-title">{title}</h3>
        <p className="chart-sub">{sub}</p>
        {children}
      </div>
    </section>
  );
}

function FailureBars({ result }: { result: CompareResult }) {
  const max = Math.max(...result.results.map((r) => r.record.failed_allocations));
  if (max === 0) {
    return <p className="secondary" style={{ margin: "1rem 0" }}>No allocation failed under any algorithm on this trace
      ({int(result.results[0]?.record.alloc_requests)} requests each). Try a smaller margin or a study trace.</p>;
  }
  return (
    <div style={{ display: "grid", gap: "0.55rem", paddingTop: "0.3rem" }}>
      {result.results.map((r) => {
        const f = r.record.failed_allocations;
        return (
          <div key={r.algorithm} style={{ display: "grid", gridTemplateColumns: "6rem minmax(0, 1fr)", alignItems: "center", gap: "0.6rem" }}
               title={`${ALG_LABEL[r.algorithm]}: ${int(f)} failed of ${int(r.record.alloc_requests)}`}>
            <span className="secondary">{ALG_LABEL[r.algorithm]}</span>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
              <div style={{ height: 18, width: `${(70 * f) / max}%`, minWidth: f ? 2 : 0, background: ALG_COLOR[r.algorithm],
                            borderRadius: "0 4px 4px 0" }} />
              <span className="num nowrap">{int(f)} <span className="muted">· {pct(r.metrics.success_rate, 2)} success</span></span>
            </div>
          </div>
        );
      })}
      <p className="note" style={{ margin: 0 }}>{failureKinds(result)}</p>
    </div>
  );
}

function failureKinds(result: CompareResult): string {
  const cap = result.results.reduce((t, r) => t + r.record.capacity_failures, 0);
  const frag = result.results.reduce((t, r) => t + r.record.fragmentation_failures, 0);
  if (cap === 0) return "Every failure was a fragmentation failure: enough memory was free in total, but no single block was large enough.";
  if (frag === 0) return "Every failure was a capacity failure: not enough memory was free in total.";
  return result.results.map((r) => `${ALG_LABEL[r.algorithm]}: ${int(r.record.fragmentation_failures)} fragmentation, ${int(r.record.capacity_failures)} capacity`).join(" · ");
}

// ------------------------------------------------------------- findings

/** Plain-English statements derived only from the measured records. */
function findings(result: CompareResult): React.ReactNode[] {
  const by = Object.fromEntries(result.results.map((r) => [r.algorithm, r])) as Partial<Record<AlgName, CompareResult["results"][number]>>;
  const out: React.ReactNode[] = [];
  const a = by.arbf, b = by.best_fit;
  if (a && b) {
    const fa = a.record.failed_allocations, fb = b.record.failed_allocations;
    out.push(fa === fb
      ? <>ARBF and Best Fit failed the same number of allocations: <b>{int(fa)}</b>.</>
      : <>ARBF failed <b>{int(fa)}</b> allocation{fa === 1 ? "" : "s"}, Best Fit <b>{int(fb)}</b> — ARBF had{" "}
        <b>{int(Math.abs(fa - fb))} {fa < fb ? "fewer" : "more"}</b> failures
        ({pp((a.metrics.success_rate ?? 0) - (b.metrics.success_rate ?? 0))} in success rate).</>);
    const ea = a.metrics.ef_mean, eb = b.metrics.ef_mean;
    if (ea != null && eb != null) {
      const d = ea - eb;
      out.push(Math.abs(d) < 0.0005
        ? <>Time-averaged external fragmentation was essentially equal: ARBF {pct(ea, 2)}, Best Fit {pct(eb, 2)} (within 0.05 pp).</>
        : <>ARBF's time-averaged external fragmentation was <b>{Math.abs(100 * d).toFixed(2)} percentage points {d < 0 ? "lower" : "higher"}</b>{" "}
          than Best Fit's ({pct(ea, 2)} vs {pct(eb, 2)}).</>);
    }
    const ia = a.metrics.blocks_inspected_mean, ib = b.metrics.blocks_inspected_mean;
    if (ia != null && ib != null && ib > 0) {
      out.push(<>ARBF inspected <b>{(ia / ib).toFixed(2)}×</b> as many free blocks per allocation as Best Fit
        ({num(ia)} vs {num(ib)}) — its extra search cost.</>);
    }
    const dev = a.record.arbf;
    if (dev) {
      out.push(dev.deviations === 0
        ? <>ARBF picked the same block as Best Fit's rule on every allocation, so on this trace the two runs are identical.</>
        : <>ARBF chose a different block than Best Fit's rule would have, in the same heap state, on{" "}
          <b>{int(dev.deviations)}</b> of {int(a.record.alloc_requests)} allocations ({pct(dev.divergence_rate, 2)}).
          {" "}Of the leftovers those choices created, {int(dev.residual_used)} were later reused, {int(dev.residual_merged)} merged
          {" "}and {int(dev.residual_survived)} were still unused at the end.</>);
    }
  }
  for (const [key, what] of [["failed_allocations", "Fewest failed allocations"], ["ef_mean", "Lowest average external fragmentation"]] as const) {
    const best = bestOf(result, key);
    if (best.size) {
      const v = by[[...best][0]]!.metrics[key];
      out.push(<>{what}: <b>{[...best].map((x) => ALG_LABEL[x]).join(", ")}</b> ({key === "ef_mean" ? pct(v, 2) : int(v)}).</>);
    }
  }
  if (!out.length) out.push(<>All selected algorithms measured identically on these metrics.</>);
  return out;
}
