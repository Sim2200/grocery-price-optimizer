"use client";

import { useState } from "react";
import { api, unitPrice, type WatchItem } from "../api";
import Typeahead from "./Typeahead";

interface Props {
  items: WatchItem[];
  /** Products that have prices; only these can be watched. */
  products: { product: string; unit: string }[];
  onChange: (items: WatchItem[]) => void;
  /** Read-only mode (offline / showing cached data): no add or remove. */
  readOnly?: boolean;
}

/**
 * Products the user wants a price-drop alert for, and which ones are currently triggered.
 *
 * Add and remove are optimistic: the list changes immediately, the request runs in the
 * background, and if it fails the previous list is put back and the error is shown.
 */
export default function Watchlist({ items, products, onChange, readOnly }: Props) {
  const [product, setProduct] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  const known = products.find((p) => p.product === product);

  function markPending(name: string, on: boolean) {
    setPending((s) => {
      const next = new Set(s);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!known) {
      setError("Pick a product from the suggestions.");
      return;
    }
    setError(null);
    const before = items;
    const targetPrice = Number(target);
    // Placeholder row until the server answers with best price and alerts.
    const optimistic: WatchItem = {
      product: known.product, unit: known.unit, target_price: targetPrice,
      best_price: null, best_store: null, alerts: [],
    };
    onChange([...before.filter((i) => i.product !== known.product), optimistic]);
    markPending(known.product, true);
    setProduct("");
    setTarget("");
    try {
      onChange(await api.watch(known.product, targetPrice));
    } catch (err) {
      onChange(before); // roll back
      setError(`Could not watch ${known.product}: ${(err as Error).message}`);
    } finally {
      markPending(known.product, false);
    }
  }

  async function remove(name: string) {
    setError(null);
    const before = items;
    onChange(before.filter((i) => i.product !== name));
    try {
      await api.unwatch(name);
    } catch (err) {
      onChange(before); // roll back
      setError(`Could not remove ${name}: ${(err as Error).message}`);
    }
  }

  return (
    <section className="card" aria-labelledby="watchlist-heading">
      <h2 id="watchlist-heading">Watchlist and price-drop alerts</h2>
      <p className="muted small">
        You get an alert when the latest price at any store is at or below your target.
      </p>
      {items.length === 0 ? (
        <p className="muted">Nothing watched yet.</p>
      ) : (
        <ul className="watchlist">
          {items.map((w) => (
            <li key={w.product} className="watch-row" aria-busy={pending.has(w.product)}>
              <div>
                <strong>{w.product}</strong>{" "}
                <span className="muted small">target {unitPrice(w.target_price, w.unit)}</span>
                <div className="small">
                  {pending.has(w.product) ? (
                    <span className="muted">Saving...</span>
                  ) : w.alerts.length > 0 ? (
                    <span className="badge badge-ok" role="status">
                      Price drop: {unitPrice(w.alerts[0].price, w.unit)} at {w.alerts[0].store}
                      {w.alerts.length > 1 && ` (+${w.alerts.length - 1} more)`}
                    </span>
                  ) : w.best_price !== null ? (
                    <span className="muted">
                      Cheapest now {unitPrice(w.best_price, w.unit)} at {w.best_store}
                    </span>
                  ) : (
                    <span className="muted">No prices yet</span>
                  )}
                </div>
              </div>
              {!readOnly && (
                <button
                  className="link danger"
                  onClick={() => remove(w.product)}
                  disabled={pending.has(w.product)}
                  aria-label={`Remove ${w.product} from watchlist`}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <form className="row gap watch-form" onSubmit={add}>
          <Typeahead
            label="Product"
            placeholder="Search products"
            value={product}
            onChange={setProduct}
            onSelect={() => setError(null)}
            accept={(hit) => products.some((p) => p.product === hit.name)}
            required
          />
          <label>
            Target price{known ? ` ($/${known.unit.replace("_", " ")})` : ""}
            <input
              className="num"
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              required
            />
          </label>
          <button type="submit">Watch</button>
        </form>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
