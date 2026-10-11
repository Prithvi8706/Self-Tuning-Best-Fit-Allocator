import { useMemo, useState } from "react";
import { useWidth } from "../hooks";

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

interface Props {
  x: number[];
  series: LineSeries[];
  height?: number;
  yFormat: (v: number) => string;
  /** Fixed y-domain; defaults to [0, nice(max)]. */
  yDomain?: [number, number];
  xLabel?: string;
  playhead?: number;
  onSeek?: (x: number) => void;
  /** Direct labels at the line ends (used for <= 4 series). */
  endLabels?: boolean;
}

/** Nice tick values covering [lo, hi] with about `count` steps. */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

/** Bucket-mean downsampling for display (nulls skipped). */
export function bucketMean(x: number[], values: (number | null)[], maxPoints: number) {
  if (x.length <= maxPoints) return { x, values };
  const size = Math.ceil(x.length / maxPoints);
  const bx: number[] = [];
  const bv: (number | null)[] = [];
  for (let i = 0; i < x.length; i += size) {
    let sum = 0;
    let n = 0;
    for (let j = i; j < Math.min(i + size, x.length); j++) {
      const v = values[j];
      if (v != null) { sum += v; n++; }
    }
    bx.push(x[Math.min(i + size, x.length) - 1]);
    bv.push(n ? sum / n : null);
  }
  return { x: bx, values: bv };
}

const M = { top: 10, right: 14, bottom: 30, left: 52 };
const X_LABEL_BAND = 16;

export function LineChart({ x, series, height = 200, yFormat, yDomain, xLabel, playhead, onSeek, endLabels }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const right = endLabels ? 74 : M.right;
  const pw = Math.max(10, width - M.left - right);
  const ph = height - M.top - M.bottom - (xLabel ? X_LABEL_BAND : 0);

  const [y0, y1] = useMemo(() => {
    if (yDomain) return yDomain;
    let max = 0;
    for (const s of series) for (const v of s.values) if (v != null && v > max) max = v;
    const ticks = niceTicks(0, max || 1);
    const step = ticks.length > 1 ? ticks[1] - ticks[0] : max || 1;
    return [0, Math.ceil((max || 1) / step - 1e-9) * step];      // round up so no line leaves the plot
  }, [series, yDomain]);
  const xMin = x.length ? Math.min(0, x[0]) : 0;
  const xMax = x.length ? x[x.length - 1] : 1;
  const sx = (v: number) => M.left + ((v - xMin) / (xMax - xMin || 1)) * pw;
  const sy = (v: number) => M.top + ph - ((v - y0) / (y1 - y0 || 1)) * ph;

  const paths = useMemo(() => series.map((s) => {
    let d = "";
    let pen = false;
    s.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  }), [series, x, pw, ph, y0, y1, xMin, xMax]);

  const yTicks = niceTicks(y0, y1);
  const xTicks = niceTicks(xMin, xMax, Math.max(2, Math.floor(pw / 110)));

  function nearest(px: number): number {
    const target = xMin + ((px - M.left) / pw) * (xMax - xMin);
    let lo = 0, hi = x.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (x[mid] < target) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(x[lo - 1] - target) < Math.abs(x[lo] - target)) lo--;
    return lo;
  }

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    setHover(nearest(e.clientX - box.left));
  }

  // end labels: last defined value per series, nudged apart vertically
  const ends = endLabels ? series.map((s) => {
    let i = s.values.length - 1;
    while (i >= 0 && s.values[i] == null) i--;
    return { s, y: i >= 0 ? sy(s.values[i] as number) : null };
  }).filter((e) => e.y != null).sort((a, b) => (a.y as number) - (b.y as number)) : [];
  for (let i = 1; i < ends.length; i++) {
    if ((ends[i].y as number) - (ends[i - 1].y as number) < 13) ends[i].y = (ends[i - 1].y as number) + 13;
  }

  const hx = hover != null && x.length ? sx(x[hover]) : null;
  const tooltipLeft = hx != null ? (hx > width - 200 ? hx - 12 : hx + 12) : 0;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg height={height} role="img" aria-label={series.map((s) => s.label).join(", ")}>
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line className="gridline" x1={M.left} x2={M.left + pw} y1={sy(t)} y2={sy(t)} />
              <text x={M.left - 8} y={sy(t)} dy="0.32em" textAnchor="end">{yFormat(t)}</text>
            </g>
          ))}
          <line className="axis" x1={M.left} x2={M.left + pw} y1={M.top + ph} y2={M.top + ph} />
          {xTicks.map((t) => (
            <text key={`x${t}`} x={sx(t)} y={M.top + ph + 16} textAnchor="middle">{t.toLocaleString("en-US")}</text>
          ))}
          {xLabel && <text x={M.left + pw / 2} y={height - 3} textAnchor="middle">{xLabel}</text>}
          {series.map((s, i) => (
            <path key={s.key} d={paths[i]} fill="none" stroke={s.color} strokeWidth={2}
                  strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {ends.map((e) => (
            <text key={`end-${e.s.key}`} x={M.left + pw + 8} y={e.y as number} dy="0.32em"
                  style={{ fill: "var(--text-2)" }}>{e.s.label}</text>
          ))}
          {playhead != null && playhead >= xMin && (
            <line className="playhead" x1={sx(playhead)} x2={sx(playhead)} y1={M.top} y2={M.top + ph} />
          )}
          {hx != null && (
            <g>
              <line className="crosshair" x1={hx} x2={hx} y1={M.top} y2={M.top + ph} />
              {series.map((s) => {
                const v = s.values[hover as number];
                return v == null ? null : (
                  <circle key={s.key} cx={hx} cy={sy(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                );
              })}
            </g>
          )}
          <rect x={M.left} y={M.top} width={pw} height={ph} fill="transparent"
                style={{ cursor: onSeek ? "pointer" : "crosshair" }}
                onPointerMove={onMove} onPointerLeave={() => setHover(null)}
                onClick={() => { if (onSeek && hover != null) onSeek(x[hover]); }} />
        </svg>
      )}
      {hover != null && hx != null && (
        <div className="tooltip" style={{ top: M.top, left: tooltipLeft,
                                           transform: hx > width - 200 ? "translateX(-100%)" : undefined }}>
          <div className="tt-title">{xLabel ? `${xLabel} ` : ""}{x[hover].toLocaleString("en-US")}</div>
          {series.map((s) => (
            <div className="tt-row" key={s.key}>
              <span className="swatch-line" style={{ background: s.color }} />
              <span>{s.label}</span>
              <span>{s.values[hover] == null ? "—" : yFormat(s.values[hover] as number)}</span>
            </div>
          ))}
          {onSeek && <div className="muted" style={{ marginTop: 2 }}>Click to jump here</div>}
        </div>
      )}
    </div>
  );
}

export function Legend({ items }: { items: { key: string; label: string; color: string }[] }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <span className="legend-item" key={it.key}>
          <span className="swatch-line" style={{ background: it.color, height: 3 }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
