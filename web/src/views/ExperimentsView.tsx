import { useRef, useState } from "react";
import { api, waitForJob, type AlgName, type ExperimentResult, type Meta, type MetricKey } from "../api";
import { niceTicks } from "../components/LineChart";
import { useWidth } from "../hooks";
import { ALG_COLOR, ALG_LABEL, ALG_ORDER, METRIC_FMT, int, pValue, pct } from "../format";
import { AlgorithmChecks } from "./CompareView";

const METRICS: MetricKey[] = ["ef_mean", "success_rate", "failed_allocations", "utilization_mean",
  "blocks_inspected_mean", "free_blocks_mean"];

interface Draft {
  family: string; firstSeed: number; seedCount: number; nEvents: number;
  memoryMode: "margin" | "memory"; margin: number; memory: number; algorithms: AlgName[];
}

export function ExperimentsView({ meta, active }: { meta: Meta; active: boolean }) {
  const [d, setD] = useState<Draft>({
    family: "F5", firstSeed: 1, seedCount: 10, nEvents: 5000, memoryMode: "margin", margin: 0.1, memory: 100000,
    algorithms: ALG_ORDER,
  });
  const set = (p: Partial<Draft>) => setD({ ...d, ...p });
  const [result, setResult] = useState<ExperimentResult | null>(null);
  const [metric, setMetric] = useState<MetricKey>("ef_mean");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const [error, setError] = useState<string | null>(null);
  const token = useRef({ cancelled: false });
  const budget = d.seedCount * d.nEvents;
  const family = meta.families.find((f) => f.name === d.family);

  async function run() {
    token.current.cancelled = true;
    const signal = { cancelled: false };
    token.current = signal;
    setRunning(true);
    setError(null);
    setProgress([0, d.seedCount]);
    try {
      const { job } = await api.experiment({
        family: d.family, first_seed: d.firstSeed, seed_count: d.seedCount, n_events: d.nEvents,
        ...(d.memoryMode === "margin" ? { margin: d.margin } : { memory: d.memory }), algorithms: d.algorithms,
      });
      setResult(await waitForJob<ExperimentResult>(job, (x, t) => setProgress([x, t]), signal));
    } catch (e) {
      if (!signal.cancelled) setError((e as Error).message);
    } finally {
      if (!signal.cancelled) setRunning(false);
    }
  }

  const numInput = (v: number, on: (n: number) => void, id: string, min = 0) => (
    <input id={id} type="number" min={min} value={Number.isFinite(v) ? v : ""}
           onChange={(e) => on(e.target.value === "" ? NaN : Number(e.target.value))} />
  );

  return (
    <div className="view" hidden={!active}>
      <aside className="sidebar">
        <div className="side-section">
          <h2 className="side-title">Experiment</h2>
          <div className="field">
            <label htmlFor="ex-family">Workload family</label>
            <select id="ex-family" value={d.family} onChange={(e) => set({ family: e.target.value })}>
              {meta.families.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
            {family && <div className="hint">{family.description}</div>}
          </div>
          <div className="field-row">
            <div className="field"><label htmlFor="ex-seed">First seed</label>{numInput(d.firstSeed, (v) => set({ firstSeed: v }), "ex-seed")}</div>
            <div className="field"><label htmlFor="ex-count">Seeds</label>{numInput(d.seedCount, (v) => set({ seedCount: v }), "ex-count", 2)}</div>
          </div>
          <div className="field">
            <label htmlFor="ex-n">Operations per seed</label>{numInput(d.nEvents, (v) => set({ nEvents: v }), "ex-n", 100)}
            <div className="hint">Seeds × operations: {int(budget)} of {int(meta.experiment_event_budget)} allowed.</div>
          </div>
          <div className="field">
            <span className="label">Memory size</span>
            <div className="seg full" role="group" aria-label="Memory sizing">
              <button aria-pressed={d.memoryMode === "margin"} onClick={() => set({ memoryMode: "margin" })}>Margin over peak</button>
              <button aria-pressed={d.memoryMode === "memory"} onClick={() => set({ memoryMode: "memory" })}>Fixed units</button>
            </div>
            {d.memoryMode === "margin" ? (
              <select aria-label="Margin" value={d.margin} onChange={(e) => set({ margin: Number(e.target.value) })}>
                {meta.margins.map((m) => <option key={m} value={m}>+{pct(m, 0)} over peak live</option>)}
              </select>
            ) : numInput(d.memory, (v) => set({ memory: v }), "ex-mem", 1)}
          </div>
        </div>
        <div className="side-section">
          <h2 className="side-title">Algorithms</h2>
          <AlgorithmChecks value={d.algorithms} onChange={(a) => set({ algorithms: a })} />
          <button className="btn btn-primary btn-block" onClick={run}
                  disabled={running || d.algorithms.length === 0 || budget > meta.experiment_event_budget}>
            {running ? "Running…" : "Run experiment"}
          </button>
          {running && (
            <div style={{ marginTop: "0.6rem" }}>
              <div className="progress"><div style={{ width: `${progress[1] ? (100 * progress[0]) / progress[1] : 0}%` }} /></div>
              <div className="hint" style={{ marginTop: "0.3rem" }}>{progress[0]} of {progress[1]} seeds done</div>
            </div>
          )}
          {error && <div className="error-box" style={{ marginTop: "0.6rem" }}><b>Experiment failed.</b> {error}</div>}
          <p className="hint" style={{ marginBottom: 0 }}>Each seed generates one trace, replayed by every algorithm
            (<span className="mono">framework.experiment.run_experiment</span>). Differences against Best Fit are paired
            by seed.</p>
        </div>
      </aside>
      <main className="main" style={{ opacity: running && result ? 0.6 : 1 }}>
        {!result ? (
          <div className="empty"><b>{running ? "Running experiment…" : "No experiment yet"}</b>
            Configure a workload family and a number of seeds, then press Run experiment.</div>
        ) : <ExperimentBody r={result} metric={metric} setMetric={setMetric} />}
      </main>
    </div>
  );
}

function ExperimentBody({ r, metric, setMetric }: { r: ExperimentResult; metric: MetricKey; setMetric: (m: MetricKey) => void }) {
  const c = r.config;
  const stats = r.stats[metric];
  const fmt = METRIC_FMT[metric];
  const info = r.metric_info[metric];
  const algs = c.algorithms.filter((a) => stats[a]);
  return (
    <>
      <div className="page-title">
        <h1>Experiment · {c.family}</h1>
        <span className="sub">{c.seeds.length} seeds ({c.seeds[0]}–{c.seeds[c.seeds.length - 1]}) · {int(c.n_events)} operations each ·{" "}
          {c.margin != null ? `arena +${pct(c.margin, 0)} over peak live` : `arena ${int(c.memory)} u`}</span>
      </div>
      <p className="note" style={{ marginTop: "0.3rem" }}>{c.description}</p>

      <div className="seg" role="group" aria-label="Metric" style={{ flexWrap: "wrap" }}>
        {METRICS.map((m) => (
          <button key={m} aria-pressed={metric === m} onClick={() => setMetric(m)}>{METRIC_FMT[m].short}</button>
        ))}
      </div>

      <section className="panel">
        <div className="panel-h">
          <h2>{info.label}</h2>
          <div className="aside">{info.lower_is_better ? "lower is better" : "higher is better"}</div>
        </div>
        <div className="panel-b">
          <Interpretation r={r} metric={metric} />
          <StripPlot r={r} metric={metric} algs={algs} />
          <p className="note" style={{ margin: "0.3rem 0 0" }}>
            Dots: one per seed. Vertical tick: mean. Horizontal bar: 95% confidence interval of the mean (t distribution).
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-h"><h2>Statistics</h2>
          {r.reference && <div className="aside">differences are paired by seed against {ALG_LABEL[r.reference]}</div>}</div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Algorithm</th><th className="r">Mean</th><th className="r">Median</th><th className="r">Std. dev.</th>
                <th className="r">95% CI</th>
                {r.reference && <><th className="r">Δ vs {ALG_LABEL[r.reference]}</th><th className="r">95% CI of Δ</th>
                  <th className="r" title="Seeds where the algorithm was better / worse / tied">Better / worse / tie</th>
                  <th className="r" title="Two-sided Wilcoxon signed-rank test (adversarial.stats)">Wilcoxon p</th></>}
              </tr>
            </thead>
            <tbody>
              {algs.map((a) => {
                const s = stats[a]!;
                const p = s.paired;
                return (
                  <tr key={a}>
                    <td><span className="legend-item"><span className="swatch" style={{ background: ALG_COLOR[a] }} />{ALG_LABEL[a]}</span></td>
                    <td className="r">{fmt.value(s.mean ?? null)}</td>
                    <td className="r">{fmt.value(s.median ?? null)}</td>
                    <td className="r">{s.sd == null ? "—" : fmt.diff(s.sd).replace(/^[+±]/, "")}</td>
                    <td className="r">{s.ci_low == null ? "—" : `${fmt.value(s.ci_low)} – ${fmt.value(s.ci_high ?? null)}`}</td>
                    {r.reference && (a === r.reference || !p ? <td className="r muted" colSpan={4}>{a === r.reference ? "reference" : "—"}</td> : <>
                      <td className="r">{fmt.diff(p.mean_diff)}</td>
                      <td className="r">{p.ci_low == null ? "—" : `${fmt.diff(p.ci_low)} … ${fmt.diff(p.ci_high)}`}</td>
                      <td className="r">{p.better} / {p.worse} / {p.ties}</td>
                      <td className="r">{pValue(p.p)}</td>
                    </>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <details className="panel hide-present" style={{ padding: "0.55rem 0.85rem" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Per-seed values</summary>
        <div className="table-wrap" style={{ marginTop: "0.5rem" }}>
          <table className="data">
            <thead><tr><th>Seed</th><th className="r">Arena</th><th>Trace SHA-256</th>
              {algs.map((a) => <th key={a} className="r">{ALG_LABEL[a]}</th>)}</tr></thead>
            <tbody>
              {r.per_seed.map((s, i) => (
                <tr key={s.seed}><td>{s.seed}</td><td className="r">{int(s.memory_size)} u</td>
                  <td className="mono">{s.trace_sha256.slice(0, 12)}…</td>
                  {algs.map((a) => <td key={a} className="r">{fmt.value(stats[a]!.values[i])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

function Interpretation({ r, metric }: { r: ExperimentResult; metric: MetricKey }) {
  const p = r.stats[metric].arbf?.paired;
  const fmt = METRIC_FMT[metric];
  if (!r.reference || !p) {
    return <p className="secondary" style={{ marginTop: 0 }}>Select both ARBF and Best Fit to see a paired comparison.</p>;
  }
  const lower = r.metric_info[metric].lower_is_better;
  const n = p.n;
  if (p.better === 0 && p.worse === 0) {
    return <p className="reason" style={{ marginTop: 0 }}>ARBF and Best Fit measured exactly the same {fmt.noun} on all {n} seeds.</p>;
  }
  const better = (p.mean_diff < 0) === lower;
  const known = p.ci_low != null && p.ci_high != null;
  const excludesZero = known && ((p.ci_low as number) > 0 || (p.ci_high as number) < 0);
  return (
    <p className="reason" style={{ marginTop: 0 }}>
      Across {n} seeds, ARBF's mean {fmt.noun} differed from Best Fit's by <b>{fmt.diff(p.mean_diff)}</b>
      {" "}({lower ? "lower" : "higher"} is better). ARBF was better on {p.better} seed{p.better === 1 ? "" : "s"},
      worse on {p.worse} and tied on {p.ties}.{" "}
      {known && (excludesZero
        ? <><b>ARBF measured {better ? "better" : "worse"} than Best Fit on this workload</b>: the 95% confidence interval of
            the paired difference ({fmt.diff(p.ci_low)} to {fmt.diff(p.ci_high)}) excludes zero</>
        : <><b>No difference is established</b>: the 95% confidence interval of the paired difference
            ({fmt.diff(p.ci_low)} to {fmt.diff(p.ci_high)}) includes zero</>)}
      {known && p.p != null && <> (Wilcoxon signed-rank p = {pValue(p.p)})</>}{known && "."}
    </p>
  );
}

function StripPlot({ r, metric, algs }: { r: ExperimentResult; metric: MetricKey; algs: AlgName[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const stats = r.stats[metric];
  const fmt = METRIC_FMT[metric];
  const left = 92, right = 16, rowH = 38, top = 6, bottom = 28;
  const all: number[] = [];
  for (const a of algs) {
    const s = stats[a]!;
    for (const v of s.values) if (v != null) all.push(v);
    if (s.ci_low != null) all.push(s.ci_low, s.ci_high as number);
  }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (!(hi > lo)) { lo -= Math.abs(lo) * 0.05 || 1; hi += Math.abs(hi) * 0.05 || 1; }
  const pad = (hi - lo) * 0.06;
  const ticks = niceTicks(lo - pad, hi + pad, Math.max(2, Math.floor((width - left) / 120)));
  const x0 = Math.min(ticks[0], lo - pad), x1 = Math.max(ticks[ticks.length - 1], hi + pad);
  const pw = Math.max(10, width - left - right);
  const sx = (v: number) => left + ((v - x0) / (x1 - x0)) * pw;
  const height = top + algs.length * rowH + bottom;

  return (
    <div className="chart" ref={ref} style={{ marginTop: "0.6rem" }}>
      {width > 0 && (
        <svg height={height} role="img" aria-label={`${r.metric_info[metric].label} per seed`}>
          {ticks.filter((t) => t >= x0 && t <= x1).map((t) => (
            <g key={t}>
              <line className="gridline" x1={sx(t)} x2={sx(t)} y1={top} y2={top + algs.length * rowH} />
              <text x={sx(t)} y={height - 8} textAnchor="middle">{fmt.value(t)}</text>
            </g>
          ))}
          {algs.map((a, k) => {
            const s = stats[a]!;
            const cy = top + k * rowH + rowH / 2;
            return (
              <g key={a}>
                <text x={left - 10} y={cy} dy="0.32em" textAnchor="end" style={{ fill: "var(--text-2)", fontSize: 12.5 }}>{ALG_LABEL[a]}</text>
                {s.values.map((v, i) => v == null ? null : (
                  <circle key={i} cx={sx(v)} cy={cy + (((i * 7) % 5) - 2) * 2.2} r={4} fill={ALG_COLOR[a]} fillOpacity={0.75}
                          stroke="var(--surface)" strokeWidth={1.5}
                          onPointerEnter={() => setHover({ x: sx(v), y: cy, text: `${ALG_LABEL[a]} · seed ${r.config.seeds[i]}: ${fmt.value(v)}` })}
                          onPointerLeave={() => setHover(null)} style={{ cursor: "default" }} />
                ))}
                {s.ci_low != null && s.ci_high != null && (
                  <g stroke="var(--ink)" strokeWidth={2}>
                    <line x1={sx(s.ci_low)} x2={sx(s.ci_high)} y1={cy + 13} y2={cy + 13} />
                    <line x1={sx(s.ci_low)} x2={sx(s.ci_low)} y1={cy + 10} y2={cy + 16} />
                    <line x1={sx(s.ci_high)} x2={sx(s.ci_high)} y1={cy + 10} y2={cy + 16} />
                  </g>
                )}
                {s.mean != null && (
                  <line x1={sx(s.mean)} x2={sx(s.mean)} y1={cy - 11} y2={cy + 16} stroke="var(--ink)" strokeWidth={2}>
                    <title>{`mean ${fmt.value(s.mean)}`}</title>
                  </line>
                )}
                <rect x={left} y={cy - rowH / 2} width={pw} height={rowH} fill="transparent" pointerEvents="none" />
              </g>
            );
          })}
        </svg>
      )}
      {hover && <div className="tooltip" style={{ left: Math.min(hover.x + 10, width - 220), top: hover.y - 40 }}>{hover.text}</div>}
    </div>
  );
}
