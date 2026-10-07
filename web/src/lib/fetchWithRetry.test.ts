import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  fetchWithRetry,
  TimeoutError,
  backoffDelay,
  isRetryableStatus,
} from "./fetchWithRetry";

describe("fetchWithRetry", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a 200 on the first try", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValueOnce(new Response("ok", { status: 200 }));

    const res = await fetchWithRetry("http://test.com/api");

    expect(res.status).toBe(200);
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("GET: 503 then 200 -> resolves 200, fetch called twice", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValueOnce(new Response("", { status: 503 }));
    mockFetch.mockResolvedValueOnce(new Response("ok", { status: 200 }));

    const res = await fetchWithRetry("http://test.com/api", {}, { baseDelayMs: 1, retries: 2 });

    expect(res.status).toBe(200);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("returns the last 503 after the retries run out", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValue(new Response("", { status: 503 }));

    const res = await fetchWithRetry("http://test.com/api", {}, { baseDelayMs: 1, retries: 2 });

    expect(res.status).toBe(503);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it("GET: network error then 200 -> 200, called twice", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    mockFetch.mockResolvedValueOnce(new Response("ok", { status: 200 }));

    const res = await fetchWithRetry("http://test.com/api", {}, { baseDelayMs: 1, retries: 2 });

    expect(res.status).toBe(200);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("POST with 503 -> returns 503, called once", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValueOnce(new Response("", { status: 503 }));

    const res = await fetchWithRetry("http://test.com/api", { method: "POST" });

    expect(res.status).toBe(503);
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("POST network error -> rejects, called once", async () => {
    const mockFetch = global.fetch as any;
    const error = new TypeError("Failed to fetch");
    mockFetch.mockRejectedValueOnce(error);

    await expect(
      fetchWithRetry("http://test.com/api", { method: "POST" })
    ).rejects.toThrow(error);
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("404 is not retried (called once)", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValueOnce(new Response("", { status: 404 }));

    const res = await fetchWithRetry("http://test.com/api", {}, { retries: 2 });

    expect(res.status).toBe(404);
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("throws TimeoutError when an attempt runs too long", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            reject(init.signal!.reason);
          });
        }
      });
    });

    await expect(
      fetchWithRetry("http://test.com/api", {}, { timeoutMs: 20, retries: 0 })
    ).rejects.toBeInstanceOf(TimeoutError);
  });

  it("never retries after the caller aborts", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            reject(init.signal!.reason);
          });
        }
      });
    });

    const controller = new AbortController();
    const promise = fetchWithRetry("http://test.com/api", { signal: controller.signal }, { retries: 2 });
    controller.abort();

    await expect(promise).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it("offline: GET with 503 -> called once", async () => {
    const mockFetch = global.fetch as any;
    mockFetch.mockResolvedValueOnce(new Response("", { status: 503 }));
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);

    const res = await fetchWithRetry("http://test.com/api", {}, { baseDelayMs: 1, retries: 2 });

    expect(res.status).toBe(503);
    expect(mockFetch).toHaveBeenCalledOnce();
  });
});

describe("backoffDelay", () => {
  it("backoffDelay(0, 300, () => 0) === 150", () => {
    const delay = backoffDelay(0, 300, () => 0);
    expect(delay).toBe(150);
  });

  it("backoffDelay(1, 300, () => 1) === 600", () => {
    const delay = backoffDelay(1, 300, () => 1);
    expect(delay).toBe(600);
  });

  it("backoffDelay(2, 300, () => 0.5) === 900", () => {
    const delay = backoffDelay(2, 300, () => 0.5);
    expect(delay).toBe(900);
  });
});

describe("isRetryableStatus", () => {
  it("returns true for 500, 503, 408, 429", () => {
    expect(isRetryableStatus(500)).toBe(true);
    expect(isRetryableStatus(503)).toBe(true);
    expect(isRetryableStatus(408)).toBe(true);
    expect(isRetryableStatus(429)).toBe(true);
  });

  it("returns false for 400, 404, 200", () => {
    expect(isRetryableStatus(400)).toBe(false);
    expect(isRetryableStatus(404)).toBe(false);
    expect(isRetryableStatus(200)).toBe(false);
  });
});
