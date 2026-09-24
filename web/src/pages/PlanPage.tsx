import { useEffect, useState } from "react";
import {
  api,
  money,
  unitPrice,
  type Plan,
  type PlanResult,
  type PriceMethod,
  type Product,
  type ShoppingItem,
} from "../api";
import ListAssistant from "../components/ListAssistant";

function PlanCard({ plan, title, highlight }: { plan: Plan; title: string; highlight?: boolean }) {
  return (
    <div className={`card plan-card ${highlight ? "highlight" : ""}`}>
      <h3>{title}</h3>
      <p className="big">{money(plan.total)}</p>
      <p className="muted small">
        items {money(plan.items_total)} + trips {money(plan.trips_total)} ({plan.stops.length}{" "}
        {plan.stops.length === 1 ? "store" : "stores"})
      </p>
      {plan.stops.map((stop) => (
        <div key={stop.store} className="stop">
          <div className="row spread">
            <strong>{stop.store}</strong>
            <span className="muted small">
              {money(stop.subtotal)} + trip {money(stop.trip_cost)}
            </span>
          </div>
          <ul>
            {stop.items.map((l) => (
              <li key={l.product} className="row spread">
                <span>
                  {l.product}{" "}
                  <span className="muted small">
                    {l.quantity} {l.unit.replace("_", " ")} @ {unitPrice(l.unit_price, l.unit)}
                  </span>
                </span>
                <span>{money(l.cost)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Build a shopping list, choose stores and trip cost, and get the optimal plan. */
export default function PlanPage({ version }: { version: number }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [stores, setStores] = useState<string[]>([]);
  const [chosenStores, setChosenStores] = useState<string[]>([]);
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [tripCost, setTripCost] = useState(5);
  const [maxStores, setMaxStores] = useState<string>("");
  const [method, setMethod] = useState<PriceMethod>("weighted");
  const [result, setResult] = useState<PlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.products(), api.stores()])
      .then(([p, s]) => {
        setProducts(p);
        setStores(s);
        setChosenStores(s);
      })
      .catch((e: Error) => setError(e.message));
  }, [version]);

  const unitOf = (name: string) => products.find((p) => p.name === name)?.unit ?? "";

  function updateItem(index: number, patch: Partial<ShoppingItem>) {
    setItems((all) => all.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  function toggleStore(store: string) {
    setChosenStores((s) => (s.includes(store) ? s.filter((x) => x !== store) : [...s, store]));
  }

  async function loadSample() {
    setItems(await api.sampleShoppingList());
  }

  async function optimize() {
    setLoading(true);
    setError(null);
    try {
      setResult(
        await api.plan({
          items: items.filter((i) => i.product && i.quantity > 0),
          stores: chosenStores,
          trip_cost: tripCost,
          max_stores: maxStores ? Number(maxStores) : null,
          price_method: method,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <ListAssistant onAdd={(added) => setItems((all) => [...all, ...added])} />

      <section className="card">
        <div className="row spread">
          <h2>Shopping list</h2>
          <button className="secondary" onClick={loadSample}>
            Use sample list
          </button>
        </div>
        {items.length === 0 && <p className="muted">Add items or use the sample list.</p>}
        {items.map((it, i) => (
          <div key={i} className="row gap list-row">
            <select value={it.product} onChange={(e) => updateItem(i, { product: e.target.value })}>
              <option value="">choose a product</option>
              {products.map((p) => (
                <option key={p.name}>{p.name}</option>
              ))}
            </select>
            <input
              className="num"
              type="number"
              min="0"
              step="0.5"
              value={it.quantity}
              onChange={(e) => updateItem(i, { quantity: Number(e.target.value) })}
            />
            <span className="muted small unit">{unitOf(it.product).replace("_", " ")}</span>
            <button className="link" onClick={() => setItems((all) => all.filter((_, j) => j !== i))}>
              remove
            </button>
          </div>
        ))}
        <button className="secondary" onClick={() => setItems((all) => [...all, { product: "", quantity: 1 }])}>
          Add item
        </button>
      </section>

      <section className="card">
        <h2>Options</h2>
        <div className="options">
          <div>
            <div className="label">Stores I'm willing to visit</div>
            {stores.length === 0 && <p className="muted small">No stores yet.</p>}
            {stores.map((s) => (
              <label key={s} className="check">
                <input type="checkbox" checked={chosenStores.includes(s)} onChange={() => toggleStore(s)} />
                {s}
              </label>
            ))}
          </div>
          <label>
            Trip cost per store ($ for time and gas)
            <input
              type="number"
              min="0"
              step="0.5"
              value={tripCost}
              onChange={(e) => setTripCost(Number(e.target.value))}
            />
          </label>
          <label>
            Max stores
            <select value={maxStores} onChange={(e) => setMaxStores(e.target.value)}>
              <option value="">no limit</option>
              {[1, 2, 3, 4].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Prices
            <select value={method} onChange={(e) => setMethod(e.target.value as PriceMethod)}>
              <option value="weighted">Recency-weighted</option>
              <option value="latest">Latest</option>
            </select>
          </label>
        </div>
        <button onClick={optimize} disabled={loading || items.length === 0 || chosenStores.length === 0}>
          {loading ? "Optimizing..." : "Plan my trip"}
        </button>
      </section>

      {error && <div className="alert error">{error}</div>}

      {result && (
        <>
          <section className="summary card">
            {result.savings_vs_single_store ? (
              <p>
                The optimal plan saves <strong>{money(result.savings_vs_single_store.amount)}</strong> (
                {result.savings_vs_single_store.percent}%) compared with the cheapest single store,
                including trip costs.
              </p>
            ) : (
              <p>No single chosen store carries every item, so there is no one-stop baseline.</p>
            )}
            {result.unavailable.length > 0 && (
              <p className="muted">
                No price data at the chosen stores for: {result.unavailable.join(", ")}.
              </p>
            )}
          </section>
          <div className="plans">
            <PlanCard plan={result.optimal} title="Optimal plan (MILP)" highlight />
            {result.single_store && <PlanCard plan={result.single_store} title="Cheapest single store" />}
            <PlanCard plan={result.greedy} title="Cheapest per item (ignores trips)" />
          </div>
        </>
      )}
    </div>
  );
}
