import { useEffect, useMemo, useRef, useState } from "react";
import { api, type AlgName, type Frame, type Meta, type Metrics, type SimSession } from "../api";
import { DecisionPanel } from "../components/DecisionPanel";
import { LineChart, bucketMean } from "../components/LineChart";
import { MemoryMap, blockAt, rowsFor, type MapBlock } from "../components/MemoryMap";
import { WorkloadForm, toSpec, type WorkloadDraft } from "../components/WorkloadForm";
import { ALG_COLOR, ALG_LABEL, ALG_ORDER, int, pct, units } from "../format";
import { useWidth } from "../hooks";
import { SPEED_MS, usePlayback, type Speed } from "../usePlayback";

interface Props {
  meta: Meta;
  draft: WorkloadDraft;
  setDraft: (d: WorkloadDraft) => void;
  present: boolean;
  active: boolean;
}

export function SimulationView({ meta, draft, setDraft, present, active }: Props) {
  const [algorithm, setAlgorithm] = useState<AlgName>("arbf");
  const [session, setSession] = useState<SimSession | null>(null);
  const [startIndex, setStartIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [explain, setExplain] = useState(false);
  const loadedSpec = useRef<string>("");
  const pb = usePlayback(session, startIndex);
  const autoplay = useRef(false);

  async function load(alg = algorithm, play = false) {
    const spec = toSpec(draft);
    const key = JSON.stringify(spec);
    setLoading(true);
    setError(null);
    try {
      const s = await api.createSim(spec, alg);
      // same workload, different policy: stay on the same operation so decisions can be compared
      setStartIndex(key === loadedSpec.current && session ? pb.index : -1);
      if (key !== loadedSpec.current) setSelected(null);
      loadedSpec.current = key;
      autoplay.current = play;
      setSession(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (session && autoplay.current && pb.frame) { autoplay.current = false; pb.play(); }
  }, [session, pb.frame]);

  // keyboard: space = run/pause, → = step, Home = reset, End = run all
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || !session) return;
      if (e.key === " ") { e.preventDefault(); if (pb.playing) pb.pause(); else pb.play(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); pb.step(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); pb.seek(pb.index - 1); }
      else if (e.key === "Home") pb.reset();
      else if (e.key === "End") pb.runAll();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, session, pb]);

  return (
    <div className="view" hidden={!active}>
      <aside className="sidebar">
        <div className="side-section">
          <h2 className="side-title">Workload</h2>
          <WorkloadForm meta={meta} draft={draft} onChange={setDraft}
                        traceActions={<button className="btn btn-primary" disabled={loading}
                                              onClick={() => load(algorithm, true)}>Run</button>} />
        </div>
        <div className="side-section">
          <h2 className="side-title">Algorithm</h2>
          <div className="field">
            <select aria-label="Algorithm" value={algorithm} onChange={(e) => {
              const a = e.target.value as AlgName;
              setAlgorithm(a);
              if (session) void load(a);
            }}>
              {ALG_ORDER.map((a) => <option key={a} value={a}>{ALG_LABEL[a]}</option>)}
            </select>
            <div className="hint">{meta.algorithms.find((a) => a.name === algorithm)?.rule}
              {session && " Switching keeps the current operation, so you can compare decisions."}</div>
          </div>
          <button className="btn btn-primary btn-block" disabled={loading} onClick={() => load()}>
            {loading ? "Loading…" : "Load simulation"}
          </button>
          {error && <div className="error-box" style={{ marginTop: "0.6rem" }}><b>Could not load.</b> {error}</div>}
        </div>
      </aside>

      <main className="main">
        {!session ? (
          <div className="empty">
            <b>{loading ? "Preparing simulation…" : "No simulation loaded"}</b>
            {error ? error : "Configure a workload and press Load simulation."}
          </div>
        ) : (
          <SimulationBody session={session} pb={pb} meta={meta} present={present} selected={selected}
                          setSelected={setSelected} explain={explain || present} setExplain={setExplain} />
        )}
      </main>
    </div>
  );
}

type Playback = ReturnType<typeof usePlayback>;

function SimulationBody({ session, pb, meta, present, selected, setSelected, explain, setExplain }: {
  session: SimSession; pb: Playback; meta: Meta; present: boolean; selected: number | null;
  setSelected: (a: number | null) => void; explain: boolean; setExplain: (v: boolean) => void;
}) {
  const { workload, timeline, events } = session;
  const frame = pb.frame;
  const [mapRef, mapWidth] = useWidth<HTMLDivElement>();
  const rows = useMemo(() => rowsFor(timeline.max_blocks, mapWidth - 74), [timeline.max_blocks, mapWidth]);

  const allocIndex = useMemo(() => {
    const m = new Map<number, number>();
    events.forEach((e, i) => { if (e[0] === "A") m.set(e[1], i); });
    return m;
  }, [events]);
  const labelOf = useMemo(() => {
    const labels = new Map<number, string>();
    for (const e of events) if (e[0] === "A") labels.set(e[1], e[2]);
    return (id: number) => labels.get(id) ?? `#${id}`;
  }, [events]);

  const metrics: Metrics = frame?.metrics ?? timeline.initial;
  const efBefore = frame && frame.index > 0 ? timeline.ef[frame.index - 1] : timeline.initial.ef;
  const change = frame && frame.index >= 0
    ? frame.status === "ok" ? { primary: frame.placed, secondary: frame.residual }
      : frame.status === "free" ? { primary: frame.merged } : undefined
    : undefined;
  const animateMs = pb.playing ? Math.min(220, SPEED_MS[pb.speed] * 0.8) : 220;

  return (
    <>
      <div className="page-title">
        <h1>{ALG_LABEL[session.algorithm]} · {workload.name}</h1>
        <span className="sub">{int(workload.n_events)} operations · arena {units(workload.capacity)}
          {" "}· peak live {units(workload.peak_live)} · 1 u = {meta.unit_bytes} bytes</span>
      </div>

      <section className="panel" aria-label="Playback">
        <Transport pb={pb} session={session} />
        <Scrubber pb={pb} session={session} />
      </section>

      {pb.error && <div className="error-box"><b>Playback stopped.</b> {pb.error}</div>}

      <section className="panel" aria-label="Live metrics">
        <div className="metrics">
          <Metric label="Allocation success" value={metrics.allocs ? pct(metrics.ok / metrics.allocs) : "—"}
                  note={`${int(metrics.ok)} of ${int(metrics.allocs)} allocations`} />
          <Metric label="External fragmentation" value={pct(metrics.ef)}
                  note={metrics.ef == null ? "undefined: no free memory" : "1 − largest free ÷ total free"} />
          <Metric label="Memory utilization" value={pct(metrics.util)} note={`${units(metrics.live)} live`} />
          <Metric label="Largest free block" value={units(metrics.largest)} note={`of ${units(metrics.total_free)} free`} />
          <Metric label="Free blocks" value={int(metrics.free_blocks)} note={`${int(metrics.allocated_blocks)} allocated blocks`} />
          <Metric label="Failed allocations" value={int(metrics.allocs - metrics.ok)}
                  note={`run total: ${int(session.summary.failed_allocations)}`} />
        </div>
      </section>

      <section className="panel" aria-label="Memory state">
        <div className="panel-h">
          <h2>Memory state</h2>
          <div className="legend" style={{ marginLeft: "auto" }}>
            <span className="legend-item"><span className="key key-alloc" />Allocated</span>
            <span className="legend-item"><span className="key key-free" />Free</span>
            <span className="legend-item"><span className="key key-change" />Changed by this operation</span>
            <span className="legend-item hide-present"><span className="key key-select" />Selected</span>
          </div>
        </div>
        <div className="panel-b" ref={mapRef}>
          {frame ? (
            <MemoryMap blocks={frame.blocks} capacity={workload.capacity} rows={rows} labelOf={labelOf}
                       change={change} changeKey={frame.index} animateMs={animateMs}
                       selectedAddr={selected} present={present}
                       onSelect={(b) => setSelected(b ? b.addr : null)} />
          ) : <div className="muted" style={{ height: 80 }}>Loading heap…</div>}
          <p className="note" style={{ margin: "0.5rem 0 0" }}>
            Address space from 0 to {int(workload.capacity)} u{rows > 1 ? `, wrapped onto ${rows} rows of ${int(workload.capacity / rows)} u (row start addresses on the left)` : ""}.
            Hover a block for details; click to inspect it.
          </p>
        </div>
      </section>

      <div className="grid-2">
        <DecisionPanel session={session} frame={frame} efBefore={efBefore} explain={explain}
                       onExplain={setExplain} arbfWindow={meta.arbf_window} />
        <div className="side-stack" style={{ display: "grid", gap: "0.9rem" }}>
          <BlockDetail frame={frame} selected={selected} labelOf={labelOf} allocIndex={allocIndex}
                       onClear={() => setSelected(null)} />
          <OpLog session={session} index={pb.index} onSeek={pb.seek} />
        </div>
      </div>

      <FragmentationChart session={session} index={pb.index} onSeek={(x) => pb.seek(x - 1)} />
    </>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

// ---------------------------------------------------------------- transport

function opText(s: SimSession, i: number): string {
  if (i < 0) return "Empty heap";
  const [op, , label, size] = s.events[i];
  return op === "A" ? `ALLOC ${label} · ${int(size)} u` : `FREE ${label}`;
}

function StatusBadge({ frame }: { frame: Frame | null }) {
  if (!frame || frame.index < 0) return <span className="status neutral">Ready</span>;
  switch (frame.status) {
    case "ok":
      return <span className="status ok">✓ Allocated at {int(frame.placed?.addr)}
        {frame.residual ? <span className="secondary" style={{ fontWeight: 400 }}>&nbsp;· split, {int(frame.residual.size)} u left free</span> : null}</span>;
    case "fail-frag":
      return <span className="status fail">✕ Failed — fragmentation</span>;
    case "fail-cap":
      return <span className="status fail">✕ Failed — out of memory</span>;
    case "free":
      return <span className="status neutral">Released
        {frame.merged_left || frame.merged_right ? " · merged with free neighbour" : ""}</span>;
    case "free-noop":
      return <span className="status neutral">No-op (allocation had failed)</span>;
    default:
      return null;
  }
}

function Transport({ pb, session }: { pb: Playback; session: SimSession }) {
  const atEnd = pb.index >= pb.n - 1;
  return (
    <div className="transport">
      <div className="btn-row">
        <button className="btn" onClick={pb.reset} title="Reset (Home)" disabled={pb.index < 0}>Reset</button>
        <button className="btn" onClick={pb.step} title="Step (→)" disabled={atEnd}>Step</button>
        {pb.playing
          ? <button className="btn btn-primary" style={{ minWidth: "4.6rem" }} onClick={pb.pause} title="Pause (Space)">Pause</button>
          : <button className="btn btn-primary" style={{ minWidth: "4.6rem" }} onClick={pb.play} title="Run (Space)">Run</button>}
        <button className="btn" onClick={pb.runAll} title="Run all (End)" disabled={atEnd}>Run all</button>
      </div>
      <div className="seg" role="group" aria-label="Speed">
        {(["slow", "normal", "fast"] as Speed[]).map((s) => (
          <button key={s} aria-pressed={pb.speed === s} onClick={() => pb.setSpeed(s)}>
            {s[0].toUpperCase() + s.slice(1)}</button>
        ))}
      </div>
      <span className="sep" />
      <div className="op-readout">
        <span className="op-count">Operation <b>{int(pb.index + 1)}</b> / {int(pb.n)}</span>
        <span className="op-main">{opText(session, pb.index)}</span>
        <StatusBadge frame={pb.frame} />
      </div>
    </div>
  );
}

function Scrubber({ pb, session }: { pb: Playback; session: SimSession }) {
  const n = pb.n;
  const failures = useMemo(() => {
    const out: number[] = [];
    session.timeline.status.forEach((s, i) => { if (s === "fail-frag" || s === "fail-cap") out.push(i); });
    return out.length > 400 ? out.filter((_, k) => k % Math.ceil(out.length / 400) === 0) : out;
  }, [session]);
  const frac = n ? (pb.index + 1) / n : 0;
  function seekTo(e: React.PointerEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    pb.seek(Math.round(((e.clientX - box.left) / box.width) * n) - 1);
  }
  return (
    <div className="scrub" role="slider" aria-label="Operation" aria-valuemin={0} aria-valuemax={n}
         aria-valuenow={pb.index + 1} tabIndex={-1}
         onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekTo(e); }}
         onPointerMove={(e) => { if (e.buttons === 1) seekTo(e); }}
         title={failures.length ? "Red ticks mark failed allocations" : undefined}>
      <div className="scrub-track" />
      <div className="scrub-fill" style={{ width: `${100 * frac}%` }} />
      {failures.map((i) => <div key={i} className="scrub-fail" style={{ left: `${(100 * (i + 1)) / n}%` }} />)}
      <div className="scrub-head" style={{ left: `${100 * frac}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------- side panels

function BlockDetail({ frame, selected, labelOf, allocIndex, onClear }: {
  frame: Frame | null; selected: number | null; labelOf: (id: number) => string;
  allocIndex: Map<number, number>; onClear: () => void;
}) {
  const b: MapBlock | null = frame && selected != null ? blockAt(frame.blocks, selected) : null;
  return (
    <section className="panel hide-present" aria-label="Selected block">
      <div className="panel-h">
        <h3>Selected block</h3>
        {b && <div className="aside"><button className="btn" onClick={onClear}>Clear</button></div>}
      </div>
      <div className="panel-b">
        {!b ? (
          <p className="muted" style={{ margin: 0 }}>Click a block in the memory map to inspect it.</p>
        ) : (
          <dl className="kv">
            <dt>State</dt><dd><b>{b.id < 0 ? "Free" : "Allocated"}</b></dd>
            {b.id >= 0 && <><dt>Allocation ID</dt><dd className="mono">{labelOf(b.id)}</dd></>}
            <dt>Start</dt><dd className="mono">{int(b.addr)}</dd>
            <dt>End</dt><dd className="mono">{int(b.addr + b.size)} <span className="muted">(exclusive)</span></dd>
            <dt>Size</dt><dd>{units(b.size)}</dd>
            {b.id >= 0 && <>
              <dt>Requested</dt><dd>{units(b.size)} <span className="muted">— the engine places exactly the request;
                any leftover is split off as a free block</span></dd>
              <dt>Allocated at</dt><dd>operation {int((allocIndex.get(b.id) ?? -1) + 1)}</dd>
            </>}
            {b.id < 0 && frame && <><dt>Share of free memory</dt>
              <dd>{pct(b.size / Math.max(1, frame.metrics.total_free))}</dd></>}
          </dl>
        )}
      </div>
    </section>
  );
}

function OpLog({ session, index, onSeek }: { session: SimSession; index: number; onSeek: (i: number) => void }) {
  const start = Math.max(0, Math.min(index - 5, session.events.length - 9));
  const rows = session.events.slice(start, start + 9).map((e, k) => ({ e, i: start + k }));
  const st = session.timeline.status;
  return (
    <section className="panel hide-present" aria-label="Operation log">
      <div className="panel-h"><h3>Operations</h3><div className="aside">click to jump</div></div>
      <div className="table-wrap">
        <table className="data oplog">
          <tbody>
            {rows.map(({ e, i }) => (
              <tr key={i} className={`clickable ${i === index ? "current" : i > index ? "dim" : ""}`} onClick={() => onSeek(i)}>
                <td className="r" style={{ width: "3.5rem" }}>{int(i + 1)}</td>
                <td>{e[0] === "A" ? "ALLOC" : "FREE"}</td>
                <td>{e[2]}</td>
                <td className="r">{e[0] === "A" ? units(e[3]) : ""}</td>
                <td className="st">{i > index ? "" : st[i] === "ok" ? <span className="secondary">ok</span>
                  : st[i].startsWith("fail") ? <span className="status fail" style={{ fontWeight: 600 }}>✕ failed</span>
                  : <span className="muted">freed</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FragmentationChart({ session, index, onSeek }: { session: SimSession; index: number; onSeek: (x: number) => void }) {
  const data = useMemo(() => {
    const x = session.timeline.ef.map((_, i) => i + 1);
    return bucketMean(x, session.timeline.ef, 500);
  }, [session]);
  const color = ALG_COLOR[session.algorithm];
  return (
    <section className="panel" aria-label="Fragmentation over time">
      <div className="panel-h">
        <h2>External fragmentation over time — {ALG_LABEL[session.algorithm]}</h2>
        <div className="aside">time-average over the run: {pct(session.summary.ef_mean)}</div>
      </div>
      <div className="panel-b">
        <LineChart x={data.x} height={170} yFormat={(v) => `${Math.round(v * 100)}%`} yDomain={[0, 1]}
                   series={[{ key: "ef", label: "External fragmentation", color, values: data.values }]}
                   xLabel="Operation" playhead={index + 1} onSeek={onSeek} />
        <p className="note" style={{ margin: "0.3rem 0 0" }}>
          1 − largest free block ÷ total free memory, after each operation{data.x.length < session.timeline.ef.length
            ? ` (averaged over windows of ${Math.ceil(session.timeline.ef.length / data.x.length)} operations)` : ""}.
          The vertical line is the current operation; click the chart to jump.
        </p>
      </div>
    </section>
  );
}
