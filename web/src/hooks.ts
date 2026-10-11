import { useEffect, useRef, useState } from "react";

/** Width of an element, tracked with a ResizeObserver. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Re-render when the OS colour scheme flips, so canvas drawings pick up new CSS tokens. */
export function useColorScheme(): string {
  const query = "(prefers-color-scheme: dark)";
  const [scheme, setScheme] = useState(() => (matchMedia(query).matches ? "dark" : "light"));
  useEffect(() => {
    const mq = matchMedia(query);
    const on = () => setScheme(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return scheme;
}
