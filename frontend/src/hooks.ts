import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

/** Fetch ``path`` (and re-fetch every ``intervalMs`` if given). ``null`` path = skip. */
export function useApi<T>(path: string | null, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const latest = useRef(path);
  latest.current = path;

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const result = await api.get<T>(path);
      if (latest.current === path) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (latest.current === path) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (latest.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(path !== null);
    void reload();
    if (!intervalMs || !path) return;
    const id = window.setInterval(() => void reload(), intervalMs);
    return () => window.clearInterval(id);
  }, [path, intervalMs, reload]);

  return { data, error, loading, reload };
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
