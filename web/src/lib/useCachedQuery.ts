"use client";

import { useCallback, useEffect, useState } from "react";
import { loadLastGood, saveLastGood } from "./lastGood";

export interface QueryState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** Set when `data` came from the offline cache because the live request failed. */
  staleSince: number | null;
  retry: () => void;
}

/**
 * Load a read-only view, remember the last good result, and fall back to it on failure.
 *
 * - success: show live data and save it under `cacheKey`
 * - failure with a cached copy: show the copy, `staleSince` set, `error` kept for a banner
 * - failure without a copy: `error` set, and `retry()` re-runs the request
 */
export function useCachedQuery<T>(cacheKey: string, fetcher: () => Promise<T>, deps: unknown[]): QueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [staleSince, setStaleSince] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((fresh) => {
        if (cancelled) return;
        setData(fresh);
        setStaleSince(null);
        saveLastGood(cacheKey, fresh);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        const cached = loadLastGood<T>(cacheKey);
        if (cached) {
          setData(cached.data);
          setStaleSince(cached.savedAt);
        }
        setError(err.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey, attempt, ...deps]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, loading, staleSince, retry };
}
