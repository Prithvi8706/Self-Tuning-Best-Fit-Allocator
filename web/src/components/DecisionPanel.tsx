import type { ArbfDecision, ArbfRow, Decision, Frame, SimSession } from "../api";
import { ALG_LABEL, int, num, pct, plural } from "../format";

interface Props {
  session: SimSession;
  frame: Frame | null;
  efBefore: number | null;  // external fragmentation just before this operation
  explain: boolean;
  onExplain: (on: boolean) => void;
  arbfWindow: number;
}

const PATH_TEXT: Record<ArbfDecision["path"], string> = {
  none: "no free block fits (FAIL)",
  exact: "P2 — exact fit, taken immediately",
  shortcut: "P5 — no remembered size between r_BF and 2·r_BF − 1, so Best Fit's block is taken without a scan",
  scan: "P4 — scan of distinct block sizes while r < 2·r_BF, lowest K wins",
};

export function DecisionPanel({ session, frame, efBefore, explain, onExplain, arbfWindow }: Props) {
  const label = ALG_LABEL[session.algorithm];
  const ev = frame && frame.index >= 0 ? session.events[frame.index] : null;
  const isArbf = session.algorithm === "arbf";
  const canExplain = isArbf && !!frame?.decision?.arbf && frame.decision.arbf.path !== "none";

  return (
    <section className="panel" aria-label="Allocator decision">
      <div className="panel-h">
        <h2>{isArbf ? "Why did ARBF choose this block?" : "Allocator decision"}</h2>
        <div className="aside">
          <span>{label}</span>
          {canExplain && (
            <button className="btn" onClick={() => onExplain(!explain)} aria-pressed={explain}>
              {explain ? "Hide score breakdown" : "Show score breakdown"}
            </button>
          )}
        </div>
      </div>
      <div className="panel-b">
        {!frame || !ev ? (
          <p className="secondary" style={{ margin: 0 }}>
            The heap is empty. Press <b>Step</b> or <b>Run</b> to apply the first operation; each allocation's
            placement decision is explained here.
          </p>
        ) : ev[0] === "F" ? (
          <FreeDetail frame={frame} labelText={ev[2]} />
        ) : (
          <AllocDetail frame={frame} size={ev[3] as number} efBefore={efBefore} label={label} explain={explain}
                       arbfWindow={arbfWindow} />
        )}
      </div>
    </section>
  );
}

function FreeDetail({ frame, labelText }: { frame: Frame; labelText: string }) {
  if (frame.status === "free-noop") {
    return <p style={{ margin: 0 }}>The allocation <b className="mono">{labelText}</b> had failed, so there is nothing to
      release. The heap is unchanged.</p>;
  }
  const { freed, merged } = frame;
  if (!freed || !merged) return null;
  const sides = [frame.merged_left && "left", frame.merged_right && "right"].filter(Boolean);
  return (
    <>
      <div className="request-line">
        <div><span className="label">Released</span><span className="v">{int(freed.size)} u</span></div>
        <div><span className="label">At address</span><span className="v mono">{int(freed.addr)}</span></div>
        <div><span className="label">Resulting free block</span><span className="v">{int(merged.size)} u</span></div>
      </div>
      <p style={{ margin: 0 }}>
        {sides.length === 0
          ? "Neither address neighbour is free, so the released block stays a separate free block."
          : `Coalesced with the free ${sides.join(" and ")} neighbour${sides.length > 1 ? "s" : ""} into one block
             [${int(merged.addr)}, ${int(merged.addr + merged.size)}).`}
      </p>
      <p className="note" style={{ margin: "0.5rem 0 0" }}>
        A FREE involves no placement decision: every policy releases and coalesces in the same way.
      </p>
    </>
  );
}

function AllocDetail({ frame, size, efBefore, label, explain, arbfWindow }: {
  frame: Frame; size: number; efBefore: number | null; label: string; explain: boolean; arbfWindow: number;
}) {
  const d = frame.decision;
  if (!d) return null;
  const failed = frame.status !== "ok";
  const a = d.arbf;
  return (
    <>
      <div className="request-line">
        <div><span className="label">Request</span><span className="v">{int(size)} u</span></div>
        <div><span className="label">Free blocks that fit</span><span className="v">{int(d.fitting_count)}</span></div>
        <div><span className="label">Fragmentation before</span><span className="v">{pct(efBefore)}</span></div>
        {a && <div><span className="label">Requests remembered</span>
          <span className="v">{int(a.n)} <span className="muted" style={{ fontSize: "0.8em", fontWeight: 400 }}>of {arbfWindow}</span></span></div>}
        {frame.inspected != null && <div><span className="label">Blocks inspected</span>
          <span className="v">{int(frame.inspected)}</span></div>}
      </div>

      {failed && (
        <div className="error-box" style={{ marginBottom: "0.6rem" }}>
          <b>✕ Allocation failed.</b> No free block holds {int(size)} u. The largest free block is{" "}
          {int(frame.metrics.largest)} u, with {int(frame.metrics.total_free)} u free in total
          {frame.status === "fail-frag"
            ? " — enough memory in total, but not in one contiguous block (a fragmentation failure)."
            : " — not enough free memory in total (a capacity failure)."}
        </div>
      )}

      {a ? <ArbfDetail a={a} explain={explain} arbfWindow={arbfWindow} /> : !failed && <PolicyDetail d={d} label={label} />}
    </>
  );
}

function PolicyDetail({ d, label }: { d: Decision; label: string }) {
  const rows = d.candidates ?? [];
  return (
    <>
      <p style={{ margin: "0 0 0.6rem" }}><b>{label}</b>: {d.rule}
        {d.rover != null && <> The pointer was at address <span className="mono">{int(d.rover)}</span>.</>}</p>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Candidate block</th><th className="r">Address</th><th className="r">Size</th>
            <th className="r">Leftover</th><th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.addr} className={r.chosen ? "chosen" : undefined}>
                <td>{i + 1}</td><td className="r mono">{int(r.addr)}</td><td className="r">{int(r.size)} u</td>
                <td className="r">{int(r.residual)} u</td><td>{r.chosen && <span className="tag solid">chosen</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ margin: "0.4rem 0 0" }}>
        Fitting blocks in the order the rule ranks them
        {d.fitting_count > rows.length ? ` (first ${rows.length} of ${int(d.fitting_count)})` : ""}.
        The leftover is split off and stays free.
      </p>
    </>
  );
}

function ArbfDetail({ a, explain, arbfWindow }: { a: ArbfDecision; explain: boolean; arbfWindow: number }) {
  if (a.path === "none") return null;
  const hidden = a.distinct_sizes - a.rows.length;
  return (
    <>
      <p className="reason" style={{ marginTop: 0 }}>{a.reason}</p>
      <div className="table-wrap" style={{ marginTop: "0.7rem" }}>
        <table className="data">
          <thead>
            <tr>
              <th className="r">Block size</th>
              <th className="r" title="Immediate fit: units left over after the request">Leftover r</th>
              <th className="r" title="c(r): remembered requests that would fit in r">Fits c(r)</th>
              <th className="r" title="Residual usefulness Ĝ(r) = c(r) / (n + 1)">Usefulness Ĝ</th>
              <th className="r" title="Learned weight 2 − Ĝ(r)">Weight</th>
              <th className="r" title="K(r) = r · (2(n+1) − c(r)); lowest wins">Score K</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {a.rows.map((r) => (
              <tr key={r.addr} className={r.chosen ? "chosen" : r.evaluated ? undefined : "dim"}>
                <td className="r">{int(r.size)} u</td>
                <td className="r">{int(r.residual)}</td>
                <td className="r">{int(r.fits)}</td>
                <td className="r">{num(r.g)}</td>
                <td className="r">{num(r.weight)}</td>
                <td className="r">{r.evaluated ? int(r.cost) : <span title={`K would be ${int(r.cost)}`}>not scanned</span>}</td>
                <td>
                  {r.chosen && <span className="tag solid">chosen</span>}
                  {a.best_fit && r.addr === a.best_fit.addr && <span className="tag">Best Fit's pick</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ margin: "0.4rem 0 0" }}>
        One row per distinct free-block size that fits (lowest address of each size).
        {a.window != null && a.path === "scan" && <> ARBF scans only leftovers below 2·r_BF = {int(a.window + 1)}; greyed rows lie outside that window.</>}
        {hidden > 0 && <> {plural(hidden, "more size")} not shown.</>}
      </p>

      {explain && <Breakdown a={a} arbfWindow={arbfWindow} />}

      <details className="tech hide-present">
        <summary>Technical details</summary>
        <dl className="kv">
          <dt>Decision path</dt><dd>{PATH_TEXT[a.path]}</dd>
          <dt>Cost function</dt><dd className="formula">K(r) = r · (2(n+1) − c(r)) = (n+1) · r · (2 − Ĝ(r))</dd>
          <dt>History size n</dt><dd>{int(a.n)}</dd>
          <dt>Best Fit leftover r_BF</dt><dd>{a.rbf == null ? "—" : `${int(a.rbf)} u`}</dd>
          <dt>Distinct fitting sizes</dt><dd>{int(a.distinct_sizes)} ({int(a.evaluated_count)} scored by the engine)</dd>
          <dt>History count queries</dt><dd>{int(a.count_queries)}</dd>
          <dt>Deviated from Best Fit</dt><dd>{a.deviated ? "yes" : "no"}</dd>
          <dt>Consistency check</dt>
          <dd>{a.consistent
            ? <span className="check-ok">✓ lowest (K, size, address) above equals the engine's choice</span>
            : <span className="check-bad">✕ explanation disagrees with the engine — please report</span>}</dd>
        </dl>
      </details>
    </>
  );
}

function Breakdown({ a, arbfWindow }: { a: ArbfDecision; arbfWindow: number }) {
  const scored = a.rows.filter((r) => r.evaluated).slice(0, 4);
  const chosen = a.rows.find((r) => r.chosen);
  const n1 = a.n + 1;
  const name = (r: ArbfRow) => `${int(r.size)} u block`;
  return (
    <div className="why">
      <div className="why-step"><span className="k">Request</span>
        <span>ARBF remembers n = {int(a.n)} recent request sizes (window W = {int(arbfWindow)}). Each candidate is scored on
          the leftover it would create.</span></div>
      <div className="why-step"><span className="k">Immediate fit</span>
        <span>{scored.map((r) => `${name(r)} → leftover ${int(r.residual)} u`).join(" · ")}
          <span className="muted"> — smaller is better; this is all Best Fit looks at.</span></span></div>
      <div className="why-step"><span className="k">Usefulness</span>
        <span>{scored.map((r) => `Ĝ(${int(r.residual)}) = ${int(r.fits)}/${int(n1)} = ${num(r.g)}`).join(" · ")}
          <span className="muted"> — share of remembered requests that would fit in the leftover.</span></span></div>
      <div className="why-step"><span className="k">Learned weight</span>
        <span>{scored.map((r) => `2 − ${num(r.g)} = ${num(r.weight)}`).join(" · ")}
          <span className="muted"> — a reusable leftover is discounted by up to half.</span></span></div>
      <div className="why-step"><span className="k">Final score</span>
        <span className="formula">{scored.map((r) =>
          `K(${int(r.residual)}) = ${int(r.residual)} × (2·${int(n1)} − ${int(r.fits)}) = ${int(r.cost)}`).join("   ·   ")}
          <span className="muted" style={{ fontFamily: "var(--font)" }}> — leftover × learned weight, scaled by n + 1; lowest wins.</span></span></div>
      {chosen && <div className="why-step"><span className="k">Selected</span>
        <span><b>{name(chosen)}</b> at address <span className="mono">{int(chosen.addr)}</span> — lowest score
          {a.deviated ? ", not the tightest block" : ", which is also the tightest block (same as Best Fit)"}.</span></div>}
    </div>
  );
}
