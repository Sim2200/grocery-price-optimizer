import { describe, it, expect } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useOnline } from "./useOnline";
import { useCachedQuery } from "./useCachedQuery";
import { saveLastGood } from "./lastGood";

describe("useCachedQuery", () => {
  it("saves successful data for later", async () => {
    const mockData = { test: "data" };
    const fetcher = async () => mockData;
    const cacheKey = "test-cache";

    const { result } = renderHook(() => useCachedQuery(cacheKey, fetcher, []));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual(mockData);
    expect(result.current.staleSince).toBeNull();
    expect(result.current.error).toBeNull();
    expect(localStorage.getItem(`gpo:lastgood:${cacheKey}`)).toBeTruthy();
  });

  it("falls back to the cached copy and marks it stale", async () => {
    const cachedData = { cached: "value" };
    const cacheKey = "test-cache-2";
    saveLastGood(cacheKey, cachedData);

    const fetcher = async () => {
      throw new Error("Network error");
    };

    const { result } = renderHook(() => useCachedQuery(cacheKey, fetcher, []));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual(cachedData);
    expect(typeof result.current.staleSince).toBe("number");
    expect(result.current.staleSince).toBeGreaterThan(0);
    expect(result.current.error).toBe("Network error");
  });

  it("shows the error without a cache, and retry() refetches", async () => {
    const cacheKey = "test-cache-3";
    let shouldFail = true;

    const fetcher = async () => {
      if (shouldFail) {
        throw new Error("Temporary error");
      }
      return { retried: true };
    };

    const { result } = renderHook(() => useCachedQuery(cacheKey, fetcher, []));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("Temporary error");

    shouldFail = false;
    await act(async () => {
      result.current.retry();
    });

    await waitFor(() => {
      expect(result.current.data).toEqual({ retried: true });
    });

    expect(result.current.error).toBeNull();
  });
});

describe("useOnline", () => {
  it("useOnline follows the offline and online events", async () => {
    const { result } = renderHook(() => useOnline());

    expect(result.current).toBe(true);

    await act(async () => {
      Object.defineProperty(navigator, "onLine", {
        writable: true,
        value: false,
      });
      window.dispatchEvent(new Event("offline"));
    });

    await waitFor(() => {
      expect(result.current).toBe(false);
    });

    await act(async () => {
      Object.defineProperty(navigator, "onLine", {
        writable: true,
        value: true,
      });
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => {
      expect(result.current).toBe(true);
    });
  });
});
