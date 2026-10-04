import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

/** Fetch ``path`` (and re-fetch every ``intervalMs`` if given). ``null`` path = skip. */
export function useApi<T>(path: string | null, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const latest = useRef(path);
  const active = useRef<AbortController | null>(null);
  latest.current = path;

  const reload = useCallback(async () => {
    if (!path || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const timeout = window.setTimeout(() => controller.abort("timeout"), 15000);
    try {
      const result = await api.get<T>(path, controller.signal);
      if (latest.current === path && !controller.signal.aborted) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (latest.current === path && (!controller.signal.aborted || controller.signal.reason === "timeout")) {
        setError(controller.signal.reason === "timeout" ? "The API is taking too long to respond. Try refreshing." : e instanceof Error ? e.message : String(e));
      }
    } finally {
      window.clearTimeout(timeout);
      if (active.current === controller) { active.current = null; if (latest.current === path) setLoading(false); }
    }
  }, [path]);

  useEffect(() => {
    setLoading(path !== null);
    setData(null);
    setError(null);
    void reload();
    const id = intervalMs && path ? window.setInterval(() => { if (!document.hidden) void reload(); }, intervalMs) : undefined;
    return () => { window.clearInterval(id); active.current?.abort(); active.current = null; };
  }, [path, intervalMs, reload]);

  return { data, error, loading, reload };
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
