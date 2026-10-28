"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Calls ``fn`` immediately and then every ``intervalMs`` while ``enabled``. Returns a manual refresh. */
export function usePolling(fn: () => Promise<void> | void, intervalMs: number, enabled = true) {
  const ref = useRef(fn);
  ref.current = fn;
  const run = useCallback(() => ref.current(), []);
  useEffect(() => {
    run();
    if (!enabled) return;
    const id = setInterval(run, intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs, run]);
  return run;
}

export function useDebounced<T>(value: T, delay = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}
