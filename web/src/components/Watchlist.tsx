"use client";

import { useState } from "react";
import { api, unitPrice, type WatchItem } from "../api";

interface Props {
  items: WatchItem[];
  /** Products that have prices, for the "add" dropdown. */
  products: { product: string; unit: string }[];
  onChange: (items: WatchItem[]) => void;
}

/** Products the user wants a price-drop alert for, and which ones are currently triggered. */
export default function Watchlist({ items, products, onChange }: Props) {
  const [product, setProduct] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      onChange(await api.watch(product, Number(target)));
      setProduct("");
      setTarget("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(name: string) {
    await api.unwatch(name);
    onChange(items.filter((i) => i.product !== name));
  }

  const unit = products.find((p) => p.product === product)?.unit;

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
            <li key={w.product} className="watch-row">
              <div>
                <strong>{w.product}</strong>{" "}
                <span className="muted small">target {unitPrice(w.target_price, w.unit)}</span>
                <div className="small">
                  {w.alerts.length > 0 ? (
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
              <button
                className="link danger"
                onClick={() => remove(w.product)}
                aria-label={`Stop watching ${w.product}`}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="row gap watch-form" onSubmit={add}>
        <label>
          Product
          <select value={product} onChange={(e) => setProduct(e.target.value)} required>
            <option value="">choose a product</option>
            {products.map((p) => (
              <option key={p.product}>{p.product}</option>
            ))}
          </select>
        </label>
        <label>
          Target price{unit ? ` ($/${unit.replace("_", " ")})` : ""}
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
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
