// fetch() with a timeout and, for idempotent requests only, retries with exponential backoff.
//
// Why: on a flaky phone connection a single dropped GET should not turn into an error page,
// but a POST (save a receipt, run the planner) must never be sent twice behind the user's back.

export const DEFAULT_TIMEOUT_MS = 8000;
export const DEFAULT_RETRIES = 2; // so up to 3 attempts in total for a GET
export const BASE_DELAY_MS = 300; // 300 ms, then 600 ms (+/- jitter)

export interface RetryOptions {
  timeoutMs?: number;
  retries?: number;
  baseDelayMs?: number;
}

/** Thrown when an attempt runs past its timeout (distinct from a caller's own abort). */
export class TimeoutError extends Error {
  constructor(ms: number) {
    super(`Request timed out after ${ms} ms`);
    this.name = "TimeoutError";
  }
}

const IDEMPOTENT = new Set(["GET", "HEAD", "OPTIONS"]);

/** Server-side or transient statuses that are worth another try. 4xx means "your request is wrong". */
export function isRetryableStatus(status: number): boolean {
  return status === 408 || status === 429 || status >= 500;
}

/** Delay before retry number `attempt` (0-based): base * 2^attempt, scaled by 0.5-1.0 jitter so
 *  many clients that failed together do not all retry at the same instant. */
export function backoffDelay(attempt: number, baseDelayMs = BASE_DELAY_MS, random = Math.random): number {
  return baseDelayMs * 2 ** attempt * (0.5 + random() / 2);
}

function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(id);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

/** One attempt with its own timeout. The caller's signal (e.g. a typeahead cancelling a stale
 *  query) aborts it too, and that abort is re-thrown as-is so the caller can recognise it. */
async function attempt(input: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new TimeoutError(timeoutMs)), timeoutMs);
  const outer = init.signal;
  const onOuterAbort = () => controller.abort(outer?.reason);
  if (outer?.aborted) onOuterAbort();
  outer?.addEventListener("abort", onOuterAbort, { once: true });
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (err) {
    // fetch rejects with an AbortError; report the timeout instead when that is what fired.
    if (controller.signal.reason instanceof TimeoutError && !outer?.aborted) throw controller.signal.reason;
    throw err;
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onOuterAbort);
  }
}

export async function fetchWithRetry(input: string, init: RequestInit = {}, opts: RetryOptions = {}): Promise<Response> {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const method = (init.method ?? "GET").toUpperCase();
  const retries = IDEMPOTENT.has(method) ? (opts.retries ?? DEFAULT_RETRIES) : 0;

  for (let i = 0; ; i++) {
    let failure: unknown; // the retryable Response or the thrown error of this attempt
    try {
      const res = await attempt(input, init, timeoutMs);
      if (!isRetryableStatus(res.status)) return res;
      failure = res;
    } catch (err) {
      if (init.signal?.aborted) throw err; // the caller cancelled: never retry
      failure = err; // network error or timeout
    }
    // Offline: retrying cannot help, fail now so the UI can fall back to cached data quickly.
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    if (i >= retries || offline) {
      if (failure instanceof Response) return failure;
      throw failure;
    }
    await sleep(backoffDelay(i, opts.baseDelayMs), init.signal);
  }
}
