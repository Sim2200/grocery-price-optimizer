// "Last good" cache: the most recent successful response for a read-only view, kept in
// localStorage so prices and insights still render (read-only, marked stale) when offline.
// Storage can be missing or throw (private mode, quota), so every access is wrapped and a
// failure simply means "no cache".

const PREFIX = "gpo:lastgood:";

export interface Cached<T> {
  data: T;
  savedAt: number; // epoch ms
}

export function saveLastGood<T>(key: string, data: T): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ data, savedAt: Date.now() }));
  } catch {
    // quota exceeded or storage disabled: the app still works, just without an offline copy
  }
}

export function loadLastGood<T>(key: string): Cached<T> | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw ? (JSON.parse(raw) as Cached<T>) : null;
  } catch {
    return null;
  }
}
