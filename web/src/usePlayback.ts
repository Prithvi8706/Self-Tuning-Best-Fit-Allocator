import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Frame, type SimSession } from "./api";

export type Speed = "slow" | "normal" | "fast";
export const SPEED_MS: Record<Speed, number> = { slow: 1000, normal: 250, fast: 33 };
const CHUNK = 64;

/**
 * Playback over a simulation session. Frames (heap snapshot + decision after an
 * event) are produced by the backend engine on demand and cached around the
 * playhead; index -1 is the empty heap before the first operation.
 */
export function usePlayback(session: SimSession | null, startIndex: number) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>("normal");
  const [error, setError] = useState<string | null>(null);
  const cache = useRef(new Map<number, Frame>());
  const inflight = useRef(new Set<number>());
  const target = useRef(-1);
  const indexRef = useRef(-1);
  const sessionRef = useRef(session);
  const n = session?.events.length ?? 0;

  const show = useCallback((f: Frame) => {
    indexRef.current = f.index;
    setFrame(f);
    for (const k of cache.current.keys()) if (k < f.index - 64 || k > f.index + 4 * CHUNK) cache.current.delete(k);
  }, []);

  const fetchFrom = useCallback(async (start: number, count: number) => {
    const s = sessionRef.current;
    if (!s || inflight.current.has(start)) return;
    inflight.current.add(start);
    try {
      const frames = await api.frames(s.id, start, count);
      if (sessionRef.current !== s) return;
      for (const f of frames) cache.current.set(f.index, f);
      const want = cache.current.get(target.current);
      if (want && want.index !== indexRef.current) show(want);
    } catch (e) {
      setError((e as Error).message);
      setPlaying(false);
    } finally {
      inflight.current.delete(start);
    }
  }, [show]);

  const seek = useCallback((i: number) => {
    const s = sessionRef.current;
    if (!s) return;
    const idx = Math.max(-1, Math.min(s.events.length - 1, Math.round(i)));
    target.current = idx;
    const f = cache.current.get(idx);
    if (f) show(f);
    else void fetchFrom(idx, 8);
  }, [fetchFrom, show]);

  // new session: reset cache, jump to the requested start
  useEffect(() => {
    sessionRef.current = session;
    cache.current.clear();
    inflight.current.clear();
    setFrame(null);
    setError(null);
    setPlaying(false);
    indexRef.current = -2;
    if (session) seek(Math.min(startIndex, session.events.length - 1));
  }, [session]);

  // playback clock
  useEffect(() => {
    if (!playing || !session) return;
    const id = window.setInterval(() => {
      const next = indexRef.current + 1;
      if (next >= n) { setPlaying(false); return; }
      target.current = next;
      const f = cache.current.get(next);
      if (!f) { void fetchFrom(next, CHUNK); return; }   // shown when it arrives
      show(f);
      // keep a chunk of frames ahead of the playhead
      let ahead = next + 1;
      while (cache.current.has(ahead) && ahead < next + CHUNK / 2) ahead++;
      if (ahead < n && ahead < next + CHUNK / 2) void fetchFrom(ahead, CHUNK);
    }, SPEED_MS[speed]);
    return () => window.clearInterval(id);
  }, [playing, speed, session, n, fetchFrom, show]);

  const index = frame?.index ?? -1;
  return {
    frame, index, n, playing, speed, error,
    setSpeed,
    play: () => { if (index >= n - 1) seek(-1); setPlaying(true); },
    pause: () => setPlaying(false),
    step: () => { setPlaying(false); seek(index + 1); },
    reset: () => { setPlaying(false); seek(-1); },
    runAll: () => { setPlaying(false); seek(n - 1); },
    seek: (i: number) => { setPlaying(false); seek(i); },
  };
}
