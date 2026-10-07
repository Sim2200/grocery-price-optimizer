"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api, type ProductSearchHit } from "../api";

/** Wait this long after the last keystroke before searching. Typing "chicken" sends one request
 *  instead of seven; results/typeahead.json has the measured difference. */
export const DEBOUNCE_MS = 200;

declare global {
  interface Window {
    /** Measurement hook only: perf/typeahead.mjs sets 0 to measure the no-debounce baseline. */
    __GPO_TYPEAHEAD_DEBOUNCE_MS?: number;
  }
}

function debounceMs(): number {
  const override = typeof window !== "undefined" ? window.__GPO_TYPEAHEAD_DEBOUNCE_MS : undefined;
  return typeof override === "number" ? override : DEBOUNCE_MS;
}

export type SearchFn = (query: string, signal: AbortSignal) => Promise<ProductSearchHit[]>;

const defaultSearch: SearchFn = (q, signal) => api.searchProducts(q, 8, signal);

/** Wrap the first case-insensitive occurrence of `query` in <mark>. Fuzzy hits may not contain
 *  the query at all, and then the name is shown as is. */
export function highlight(text: string, query: string) {
  const q = query.trim();
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  );
}

interface Props {
  label: string;
  value: string;
  onChange: (text: string) => void;
  /** Called when a suggestion is picked with Enter or a click. */
  onSelect: (hit: ProductSearchHit) => void;
  placeholder?: string;
  search?: SearchFn;
  /** Drop suggestions the caller cannot use (e.g. products with no prices yet). */
  accept?: (hit: ProductSearchHit) => boolean;
  required?: boolean;
  /** Hide the label visually (it is still the accessible name). */
  hideLabel?: boolean;
}

/**
 * Product search box following the WAI-ARIA combobox pattern: the input keeps focus, the
 * highlighted option is announced through aria-activedescendant, and
 * ArrowUp/ArrowDown move, Enter picks, Escape closes.
 *
 * Every keystroke restarts a DEBOUNCE_MS timer; when it fires, the previous in-flight request
 * is aborted so a slow, stale response can never overwrite the results of a newer query.
 */
export default function Typeahead({
  label, value, onChange, onSelect, placeholder, search = defaultSearch, accept, required, hideLabel,
}: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const [hits, setHits] = useState<ProductSearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);
  // Picking a suggestion writes its name into the box; that change must not trigger a search.
  const skipNextSearch = useRef(false);
  // Callers often pass inline functions; keep the latest in refs so they don't restart the search.
  const searchRef = useRef(search);
  const acceptRef = useRef(accept);
  searchRef.current = search;
  acceptRef.current = accept;

  useEffect(() => {
    if (skipNextSearch.current) {
      skipNextSearch.current = false;
      return;
    }
    const q = value.trim();
    if (!q) {
      inflight.current?.abort();
      setHits([]);
      setLoading(false);
      return;
    }
    const timer = setTimeout(() => {
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;
      setLoading(true);
      setError(null);
      searchRef.current(q, controller.signal)
        .then((results) => {
          if (controller.signal.aborted) return;
          const keep = acceptRef.current;
          setHits(keep ? results.filter(keep) : results);
          setActive(-1);
        })
        .catch((err: Error) => {
          if (err.name !== "AbortError" && !controller.signal.aborted) setError(err.message);
        })
        .finally(() => {
          if (inflight.current === controller) setLoading(false);
        });
    }, debounceMs());
    return () => clearTimeout(timer);
  }, [value]);

  // Abort anything still in flight when the component goes away.
  useEffect(() => () => inflight.current?.abort(), []);

  function pick(hit: ProductSearchHit) {
    skipNextSearch.current = true;
    onChange(hit.name);
    onSelect(hit);
    setOpen(false);
    setActive(-1);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && active >= 0 && hits[active]) {
      e.preventDefault(); // pick the option instead of submitting the form
      pick(hits[active]);
    } else if (e.key === "Escape") {
      if (open) e.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  }

  const showList = open && value.trim() !== "" && (hits.length > 0 || (!loading && !error));
  const optionId = (i: number) => `${id}-opt-${i}`;

  return (
    <div className="typeahead">
      <label htmlFor={`${id}-input`} className={hideLabel ? "sr-only" : "label"}>
        {label}
      </label>
      <input
        id={`${id}-input`}
        type="text"
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && active >= 0 ? optionId(active) : undefined}
        aria-busy={loading}
        placeholder={placeholder}
        required={required}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="typeahead-list" hidden={!showList}>
        {hits.length === 0 ? (
          <li className="typeahead-empty" role="presentation">
            No matching products
          </li>
        ) : (
          hits.map((hit, i) => (
            <li
              key={hit.name}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              // mousedown, not click: it fires before the input's blur closes the list.
              onMouseDown={(e) => {
                e.preventDefault();
                pick(hit);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>{highlight(hit.name, value)}</span>
              <span className="muted small">{hit.category}</span>
            </li>
          ))
        )}
      </ul>
      <span className="sr-only" role="status" aria-live="polite">
        {showList ? `${hits.length} suggestion${hits.length === 1 ? "" : "s"}` : ""}
      </span>
      {error && <span className="small typeahead-error">{error}</span>}
    </div>
  );
}
