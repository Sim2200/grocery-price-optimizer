"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, unitPrice, type PriceMethod, type PricePoint, type PriceTable, type WatchItem } from "../api";
import { ErrorState, Skeleton, StaleBanner } from "../components/Status";
import Typeahead from "../components/Typeahead";
import Watchlist from "../components/Watchlist";
import { useCachedQuery } from "../lib/useCachedQuery";

// Charts pull in the charting library; load it only when a product is selected.
const PriceCharts = dynamic(() => import("../components/PriceCharts"), {
  ssr: false,
  loading: () => <div className="skeleton skeleton-chart" aria-hidden="true" />,
});

/** Product x store comparison table, charts for the selected product, and the watchlist. */
export default function PricesPage({
  version,
  onWatchlistChanged,
}: {
  version: number;
  onWatchlistChanged: () => void;
}) {
  const [method, setMethod] = useState<PriceMethod>("weighted");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<PricePoint[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const fetchPrices = useCallback(() => api.prices(method), [method]);
  const prices = useCachedQuery<PriceTable>(`prices:${method}`, fetchPrices, [version]);
  const watchQuery = useCachedQuery<WatchItem[]>("watchlist", api.watchlist, [version]);
  // Local copy so the watchlist can be updated optimistically.
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  useEffect(() => {
    if (watchQuery.data) setWatchlist(watchQuery.data);
  }, [watchQuery.data]);

  function updateWatchlist(items: WatchItem[]) {
    setWatchlist(items);
    onWatchlistChanged();
  }

  useEffect(() => {
    if (!selected) return;
    setHistoryError(null);
    api.priceHistory(selected).then(setHistory).catch((e: Error) => setHistoryError(e.message));
  }, [selected, version]);

  const table = prices.data;
  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (table?.rows ?? []).filter(
      (r) => r.product.toLowerCase().includes(f) || r.category.toLowerCase().includes(f),
    );
  }, [table, filter]);

  if (!table && prices.loading) return <Skeleton rows={8} label="Loading prices" />;
  if (!table) return <ErrorState message={prices.error ?? "Could not load prices."} onRetry={prices.retry} />;
  if (table.rows.length === 0)
    return <p className="muted">No prices yet. Save a receipt or load the synthetic demo data.</p>;

  const stores = table.stores;
  const readOnly = prices.staleSince !== null;
  const selectedRow = table.rows.find((r) => r.product === selected) ?? null;
  const selectedWatch = watchlist.find((w) => w.product === selected) ?? null;

  return (
    <div className="stack">
      {prices.staleSince !== null && <StaleBanner since={prices.staleSince} onRetry={prices.retry} />}
      <section className="card" aria-labelledby="prices-heading">
        <div className="row gap spread toolbar">
          <h2 id="prices-heading">Price comparison</h2>
          <div className="row gap toolbar-controls">
            <Typeahead
              label="Filter products or categories"
              hideLabel
              placeholder="Filter products or categories"
              value={filter}
              onChange={setFilter}
              onSelect={(hit) => setSelected(hit.name)}
              accept={(hit) => table.rows.some((r) => r.product === hit.name)}
            />
            <label className="sr-only" htmlFor="price-method">
              Price method
            </label>
            <select id="price-method" value={method} onChange={(e) => setMethod(e.target.value as PriceMethod)}>
              <option value="weighted">Recency-weighted price</option>
              <option value="latest">Latest price</option>
            </select>
          </div>
        </div>
        <p className="muted small">
          Prices are per comparable unit, so a 12-count and an 18-count carton of eggs compare
          fairly. Cheapest store is highlighted. Select a row (click, or Tab then Enter) for charts.
        </p>
        <div className="table-wrap">
          {/* On phones the table turns into one card per product (see .responsive-table in CSS);
              data-label gives each cell its column name there. */}
          <table className="responsive-table">
            <thead>
              <tr>
                <th>Product</th>
                {stores.map((s) => (
                  <th key={s} className="num">
                    {s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.product}
                  className={`clickable ${selected === r.product ? "row-selected" : ""}`}
                  onClick={() => setSelected(r.product)}
                  // Rows are focusable and open the charts with Enter/Space too.
                  tabIndex={0}
                  aria-selected={selected === r.product}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(r.product);
                    }
                  }}
                >
                  <td className="cell-title">
                    {r.product} <span className="muted small">{r.category}</span>
                  </td>
                  {stores.map((s) => {
                    const cell = r.prices[s];
                    return (
                      <td
                        key={s}
                        data-label={s}
                        className={`num ${r.cheapest_store === s ? "cheapest" : ""}`}
                        title={cell ? `${cell.n_observations} observation(s), last ${cell.last_seen}` : ""}
                      >
                        {cell ? unitPrice(cell.price, r.unit) : <span className="muted">-</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p className="muted">No products match "{filter}".</p>}
        </div>
      </section>

      {selectedRow && (
        <section className="card" aria-labelledby="selected-heading">
          <h2 id="selected-heading">{selectedRow.product}</h2>
          {historyError && <div className="alert error" role="alert">{historyError}</div>}
          <PriceCharts row={selectedRow} stores={stores} history={history} watch={selectedWatch} />
        </section>
      )}

      <Watchlist
        items={watchlist}
        products={table.rows.map((r) => ({ product: r.product, unit: r.unit }))}
        onChange={updateWatchlist}
        readOnly={readOnly}
      />
    </div>
  );
}
