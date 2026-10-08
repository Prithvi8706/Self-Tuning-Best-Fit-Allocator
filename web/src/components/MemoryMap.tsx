import { useEffect, useRef, useState } from "react";
import type { BlockRef } from "../api";
import { useColorScheme, useWidth } from "../hooks";
import { int } from "../format";

export interface MapBlock { addr: number; size: number; id: number } // id -1 = free

interface Props {
  blocks: number[];          // flattened [addr, size, id]
  capacity: number;
  rows: number;
  labelOf: (id: number) => string;
  /** Blocks changed by the current operation: primary (placed / merged) and secondary (split leftover). */
  change?: { primary?: BlockRef; secondary?: BlockRef };
  changeKey: number;
  animateMs: number;
  selectedAddr: number | null;
  onSelect: (block: MapBlock | null) => void;
  present?: boolean;
}

const ROW_GAP = 4;
const AXIS_H = 20;

/** Rows needed so the average block is at least ~6px wide. */
export function rowsFor(maxBlocks: number, width: number): number {
  if (width <= 0) return 1;
  return Math.max(1, Math.min(16, Math.ceil((maxBlocks * 6) / width)));
}

export function blockAt(blocks: number[], addr: number): MapBlock | null {
  let lo = 0, hi = blocks.length / 3 - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const a = blocks[3 * mid], s = blocks[3 * mid + 1];
    if (addr < a) hi = mid - 1;
    else if (addr >= a + s) lo = mid + 1;
    else return { addr: a, size: s, id: blocks[3 * mid + 2] };
  }
  return null;
}

function rowHeight(rows: number, present?: boolean) {
  if (rows === 1) return present ? 104 : 80;
  if (rows <= 4) return present ? 52 : 42;
  return Math.max(18, Math.floor((present ? 380 : 320) / rows));
}

export function MemoryMap(props: Props) {
  const { blocks, capacity, rows, changeKey, animateMs, selectedAddr, present } = props;
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const propsRef = useRef(props);
  propsRef.current = props;
  const scheme = useColorScheme();
  const [hover, setHover] = useState<{ x: number; y: number; b: MapBlock } | null>(null);

  const gutter = rows > 1 ? 74 : 0;
  const rowH = rowHeight(rows, present);
  const plotH = rows * rowH + (rows - 1) * ROW_GAP;
  const height = plotH + (rows === 1 ? AXIS_H : 0);
  const plotW = Math.max(10, width - gutter);
  const span = capacity / rows;

  function draw(flash: number) {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0) return;
    const p = propsRef.current;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(canvas);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const c = {
      alloc: color("--alloc"), allocText: color("--alloc-text"), free: color("--free"),
      hatch: color("--free-hatch"), freeText: color("--free-text"), surface: color("--surface"),
      change: color("--change"), select: color("--select"), muted: color("--text-3"),
      border: color("--border-strong"),
    };
    const font = css.getPropertyValue("--font");
    const mono = css.getPropertyValue("--mono");
    ctx.clearRect(0, 0, width, height);

    // hatch pattern for free memory: 45° hairlines
    const tile = document.createElement("canvas");
    tile.width = tile.height = 6;
    const tctx = tile.getContext("2d")!;
    tctx.fillStyle = c.free;
    tctx.fillRect(0, 0, 6, 6);
    tctx.strokeStyle = c.hatch;
    tctx.lineWidth = 1;
    tctx.beginPath();
    tctx.moveTo(0, 6); tctx.lineTo(6, 0);
    tctx.moveTo(-1, 1); tctx.lineTo(1, -1);
    tctx.moveTo(5, 7); tctx.lineTo(7, 5);
    tctx.stroke();
    const hatch = ctx.createPattern(tile, "repeat")!;

    const rowY = (r: number) => r * (rowH + ROW_GAP);
    const xOf = (offset: number) => gutter + (offset / span) * plotW;

    /** Calls fn for each row segment of [addr, addr+size). */
    function segments(addr: number, size: number, fn: (x0: number, x1: number, y: number, first: boolean) => void) {
      const end = addr + size;
      let r = Math.min(rows - 1, Math.floor(addr / span));
      let first = true;
      while (r < rows && r * span < end) {
        const s = Math.max(addr, r * span), e = Math.min(end, (r + 1) * span);
        if (e > s) { fn(xOf(s - r * span), xOf(e - r * span), rowY(r), first); first = false; }
        r++;
      }
    }

    // row backgrounds (frame)
    ctx.strokeStyle = c.border;
    ctx.lineWidth = 1;
    for (let r = 0; r < rows; r++) ctx.strokeRect(gutter + 0.5, rowY(r) + 0.5, plotW - 1, rowH - 1);

    const labelFont = `${present ? 13 : 12}px ${font}`;
    const smallFont = `${present ? 12 : 11}px ${mono}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    const n = p.blocks.length / 3;
    for (let i = 0; i < n; i++) {
      const addr = p.blocks[3 * i], size = p.blocks[3 * i + 1], id = p.blocks[3 * i + 2];
      const free = id < 0;
      segments(addr, size, (x0, x1, y, first) => {
        const left = Math.round(x0), w = Math.max(1, Math.round(x1) - left);
        ctx.fillStyle = free ? hatch : c.alloc;
        ctx.fillRect(left, y, w, rowH);
        if (!free && w >= 3) {               // 1px surface gap separates touching allocations
          ctx.fillStyle = c.surface;
          ctx.fillRect(left, y, 1, rowH);
        }
        if (!first || w < 28 || rowH < 18) return;      // label a wrapped block once, on its first row
        const label = free ? "free" : p.labelOf(id);
        const sizeText = `${int(size)} u`;
        ctx.font = labelFont;
        const lw = ctx.measureText(label).width;
        ctx.font = smallFont;
        const sw = ctx.measureText(sizeText).width;
        const cx = left + w / 2;
        ctx.fillStyle = free ? c.freeText : c.allocText;
        if (rowH >= 38 && Math.max(lw, sw) + 10 <= w) {
          ctx.font = labelFont;
          ctx.fillText(label, cx, y + rowH / 2 - 8);
          ctx.font = smallFont;
          ctx.fillText(sizeText, cx, y + rowH / 2 + 9);
        } else if (lw + sw + 18 <= w) {
          ctx.font = labelFont;
          ctx.fillText(`${label} · ${int(size)} u`, cx, y + rowH / 2);
        } else if (lw + 8 <= w) {
          ctx.font = labelFont;
          ctx.fillText(label, cx, y + rowH / 2);
        }
      });
    }

    // operation highlight: outline + a brief fading wash
    const outline = (b: BlockRef, stroke: string, lw: number, wash: number, alpha = 1) => {
      segments(b.addr, b.size, (x0, x1, y) => {
        const left = Math.round(x0), w = Math.max(2, Math.round(x1) - left);
        if (wash > 0) {
          ctx.globalAlpha = wash;
          ctx.fillStyle = stroke;
          ctx.fillRect(left, y, w, rowH);
          ctx.globalAlpha = 1;
        }
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lw;
        ctx.strokeRect(left + lw / 2, y + lw / 2, Math.max(1, w - lw), rowH - lw);
        ctx.globalAlpha = 1;
      });
    };
    if (p.change?.secondary) outline(p.change.secondary, c.change, 1, 0, 0.55);   // split-off leftover
    if (p.change?.primary) outline(p.change.primary, c.change, 2.5, 0.35 * (1 - flash));
    if (p.selectedAddr != null) {
      const b = blockAt(p.blocks, p.selectedAddr);
      if (b) outline(b, c.select, 2, 0);
    }

    // address labels: row starts (multi-row) or an axis (single row)
    ctx.fillStyle = c.muted;
    ctx.font = smallFont;
    if (rows > 1) {
      ctx.textAlign = "right";
      for (let r = 0; r < rows; r++) ctx.fillText(int(r * span), gutter - 8, rowY(r) + rowH / 2);
    } else {
      ctx.textBaseline = "alphabetic";
      for (let k = 0; k <= 4; k++) {
        const x = gutter + (k / 4) * plotW;
        ctx.textAlign = k === 0 ? "left" : k === 4 ? "right" : "center";
        ctx.fillText(int((k / 4) * capacity), x, plotH + 15);
      }
    }
  }

  // redraw on data / size / theme change, with a short wash on the changed block
  useEffect(() => {
    if (animateMs <= 0) { draw(1); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / animateMs);
      draw(k);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [changeKey, blocks, width, height, rows, capacity, selectedAddr, scheme, present]);

  function hit(e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number; b: MapBlock } | null {
    const box = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - box.left, y = e.clientY - box.top;
    const r = Math.floor(y / (rowH + ROW_GAP));
    if (x < gutter || r < 0 || r >= rows || y - r * (rowH + ROW_GAP) > rowH) return null;
    const addr = Math.floor(r * span + ((x - gutter) / plotW) * span);
    const b = blockAt(props.blocks, Math.min(capacity - 1, Math.max(0, addr)));
    return b ? { x, y, b } : null;
  }

  const tip = hover && (
    <div className="tooltip" style={{
      left: Math.min(hover.x + 14, Math.max(0, width - 230)), top: hover.y + 16,
    }}>
      <div className="tt-title">{hover.b.id < 0 ? "Free block" : `Allocation ${props.labelOf(hover.b.id)}`}</div>
      <div className="tt-row"><span>Size</span><span>{int(hover.b.size)} u</span></div>
      <div className="tt-row"><span>Address</span>
        <span className="mono">{int(hover.b.addr)} – {int(hover.b.addr + hover.b.size)}</span></div>
      <div className="muted" style={{ marginTop: 2 }}>Click to inspect</div>
    </div>
  );

  return (
    <div className="memmap" ref={wrapRef}>
      <canvas ref={canvasRef} role="img"
              aria-label={`Memory layout: ${blocks.length / 3} blocks over ${int(capacity)} units`}
              onPointerMove={(e) => setHover(hit(e))}
              onPointerLeave={() => setHover(null)}
              onClick={(e) => props.onSelect(hit(e)?.b ?? null)} />
      {tip}
    </div>
  );
}
