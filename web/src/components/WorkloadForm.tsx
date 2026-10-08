import { useId, useState } from "react";
import { api, type Meta, type TraceValidation, type WorkloadSpec } from "../api";
import { int, pct } from "../format";

export interface WorkloadDraft {
  kind: "family" | "trace" | "corpus";
  family: string;
  seed: number;
  nEvents: number;
  memoryMode: "margin" | "memory";
  margin: number;
  memory: number;
  traceText: string;
  traceMemory: number;
  corpus: string;
}

export const DEFAULT_TRACE = `# One operation per line: ALLOC <id> <size> | FREE <id>
ALLOC A1 100
ALLOC A2 200
FREE A1
ALLOC A3 80
ALLOC A4 150
FREE A2
`;

export function defaultDraft(meta: Meta): WorkloadDraft {
  return {
    kind: "family", family: meta.families.some((f) => f.name === "F5") ? "F5" : meta.families[0].name,
    seed: 1, nEvents: 1000, memoryMode: "margin", margin: 0.1, memory: 100000,
    traceText: DEFAULT_TRACE, traceMemory: 1024, corpus: meta.corpus[0]?.name ?? "",
  };
}

export function toSpec(d: WorkloadDraft): WorkloadSpec {
  if (d.kind === "trace") return { kind: "trace", text: d.traceText, memory: d.traceMemory };
  if (d.kind === "corpus") return { kind: "corpus", name: d.corpus };
  return d.memoryMode === "margin"
    ? { kind: "family", family: d.family, seed: d.seed, n_events: d.nEvents, margin: d.margin }
    : { kind: "family", family: d.family, seed: d.seed, n_events: d.nEvents, memory: d.memory };
}

const ROLE: Record<string, string> = {
  P: "predicted ARBF effect", boundary: "boundary case", N: "predicted ≈ Best Fit", X: "exploratory / risk",
};

export function NumberInput({ value, onChange, min, max, id }: {
  value: number; onChange: (v: number) => void; min: number; max?: number; id?: string;
}) {
  return (
    <input id={id} type="number" value={Number.isFinite(value) ? value : ""} min={min} max={max}
           onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} />
  );
}

interface Props {
  meta: Meta;
  draft: WorkloadDraft;
  onChange: (d: WorkloadDraft) => void;
  /** Rendered under the trace editor, e.g. a Run button. */
  traceActions?: React.ReactNode;
}

export function WorkloadForm({ meta, draft, onChange, traceActions }: Props) {
  const uid = useId();
  const set = (patch: Partial<WorkloadDraft>) => onChange({ ...draft, ...patch });
  const family = meta.families.find((f) => f.name === draft.family);
  const corpus = meta.corpus.find((c) => c.name === draft.corpus);

  return (
    <>
      <div className="field">
        <span className="label">Source</span>
        <div className="seg full" role="group" aria-label="Workload source">
          {([["family", "Generated"], ["trace", "Custom"], ["corpus", "Study trace"]] as const).map(([k, l]) => (
            <button key={k} aria-pressed={draft.kind === k} onClick={() => set({ kind: k })}
                    disabled={k === "corpus" && meta.corpus.length === 0}>{l}</button>
          ))}
        </div>
      </div>

      {draft.kind === "family" && (
        <>
          <div className="field">
            <label htmlFor={`${uid}wf-family`}>Workload family</label>
            <select id={`${uid}wf-family`} value={draft.family} onChange={(e) => set({ family: e.target.value })}>
              {meta.families.map((f) => <option key={f.name} value={f.name}>{f.name} — {ROLE[f.role] ?? f.role}</option>)}
            </select>
            {family && <div className="hint">{family.description}</div>}
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor={`${uid}wf-seed`}>Seed</label>
              <NumberInput id={`${uid}wf-seed`} value={draft.seed} min={0} onChange={(v) => set({ seed: v })} />
            </div>
            <div className="field">
              <label htmlFor={`${uid}wf-n`}>Operations</label>
              <NumberInput id={`${uid}wf-n`} value={draft.nEvents} min={1} max={meta.max_events}
                           onChange={(v) => set({ nEvents: v })} />
            </div>
          </div>
          <div className="field">
            <span className="label">Memory size</span>
            <div className="seg full" role="group" aria-label="Memory sizing">
              <button aria-pressed={draft.memoryMode === "margin"} onClick={() => set({ memoryMode: "margin" })}>
                Margin over peak</button>
              <button aria-pressed={draft.memoryMode === "memory"} onClick={() => set({ memoryMode: "memory" })}>
                Fixed units</button>
            </div>
            {draft.memoryMode === "margin" ? (
              <>
                <select aria-label="Margin" value={draft.margin} onChange={(e) => set({ margin: Number(e.target.value) })}>
                  {meta.margins.map((m) => <option key={m} value={m}>+{pct(m, 0)} over peak live</option>)}
                </select>
                <div className="hint">Arena = ⌈(1 + margin) × peak live⌉. Smaller margins put more pressure on placement.</div>
              </>
            ) : (
              <NumberInput value={draft.memory} min={1} onChange={(v) => set({ memory: v })} />
            )}
          </div>
        </>
      )}

      {draft.kind === "trace" && (
        <TraceEditor draft={draft} set={set} actions={traceActions} />
      )}

      {draft.kind === "corpus" && (
        <>
          <div className="field">
            <label htmlFor={`${uid}wf-corpus`}>Preserved trace</label>
            <select id={`${uid}wf-corpus`} value={draft.corpus} onChange={(e) => set({ corpus: e.target.value })}>
              {meta.corpus.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          {corpus && (
            <div className="hint" style={{ display: "grid", gap: "0.4rem", marginBottom: "0.75rem" }}>
              <div><b className="secondary">{corpus.classification}</b></div>
              <div>{int(corpus.n_events)} operations · arena {int(corpus.memory)} u</div>
              <div>Recorded in the study: Best Fit {int(corpus.expected.best_fit)} failed,
                ARBF {int(corpus.expected.arbf)} failed.</div>
              <details>
                <summary style={{ cursor: "pointer" }}>Study notes</summary>
                <p style={{ margin: "0.4rem 0 0" }}>{corpus.explanation}</p>
              </details>
            </div>
          )}
        </>
      )}
    </>
  );
}

function TraceEditor({ draft, set, actions }: {
  draft: WorkloadDraft; set: (p: Partial<WorkloadDraft>) => void; actions?: React.ReactNode;
}) {
  const uid = useId();
  const [result, setResult] = useState<TraceValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lines = draft.traceText.split("\n").length;
  const bad = new Set(result?.issues.map((i) => i.line) ?? []);

  async function validate() {
    setError(null);
    try { setResult(await api.validateTrace(draft.traceText)); } catch (e) { setError((e as Error).message); }
  }

  return (
    <>
      <div className="field">
        <label htmlFor={`${uid}wf-trace`}>Trace</label>
        <div className="editor">
          <div className="editor-gutter" aria-hidden>
            {Array.from({ length: lines }, (_, i) => (
              <div key={i} className={bad.has(i + 1) ? "bad" : undefined}>{i + 1}</div>
            ))}
          </div>
          <textarea id={`${uid}wf-trace`} spellCheck={false} value={draft.traceText} rows={Math.max(10, lines + 1)}
                    onChange={(e) => { set({ traceText: e.target.value }); setResult(null); }} />
        </div>
        <div className="hint"><span className="mono">ALLOC &lt;id&gt; &lt;size&gt;</span> or{" "}
          <span className="mono">FREE &lt;id&gt;</span>, one per line. Sizes in units; <span className="mono">#</span> starts a comment.</div>
      </div>
      <div className="field">
        <label htmlFor={`${uid}wf-tmem`}>Memory size (units)</label>
        <NumberInput id={`${uid}wf-tmem`} value={draft.traceMemory} min={1} onChange={(v) => set({ traceMemory: v })} />
      </div>
      <div className="btn-row" style={{ marginBottom: "0.6rem" }}>
        {actions}
        <button className="btn" onClick={validate}>Validate</button>
        <button className="btn" onClick={() => { set({ traceText: "" }); setResult(null); }}>Clear</button>
      </div>
      {error && <div className="error-box">{error}</div>}
      {result && (result.ok ? (
        <div className="hint">
          <span className="check-ok">✓ Valid</span> — {int(result.summary?.events)} operations
          ({int(result.summary?.allocs)} ALLOC, {int(result.summary?.frees)} FREE),
          peak live {int(result.summary?.peak_live)} u
          {result.summary && result.summary.peak_live > draft.traceMemory &&
            <> — <b>exceeds the {int(draft.traceMemory)} u arena</b>, so some allocations must fail</>}.
        </div>
      ) : (
        <ul className="issues">
          {result.issues.map((i, k) => (
            <li key={k}>{i.line ? <>Line {i.line}: </> : null}<span>{i.message}</span></li>
          ))}
        </ul>
      ))}
    </>
  );
}
