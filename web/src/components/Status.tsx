"use client";

// Loading, error and stale-data states shared by the pages.

/** Grey placeholder blocks in the shape of the content that is loading, so the layout does not
 *  jump when data arrives (and Lighthouse's CLS stays near zero). */
export function Skeleton({ rows = 6, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <section className="card" aria-busy="true" aria-label={label}>
      <div className="skeleton skeleton-title" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton skeleton-row" />
      ))}
      <span className="sr-only" role="status">{label}...</span>
    </section>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="alert error row gap spread" role="alert">
      <span>{message}</span>
      <button className="secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** Shown above cached data when the live request failed (usually: offline). */
export function StaleBanner({ since, onRetry }: { since: number; onRetry: () => void }) {
  return (
    <div className="alert warn row gap spread" role="status">
      <span>
        Showing saved data from {new Date(since).toLocaleString()}. It is read-only until the
        connection is back.
      </span>
      <button className="secondary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
