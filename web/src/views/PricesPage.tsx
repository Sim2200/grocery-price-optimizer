"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  unitPrice,
  type PriceMethod,
  type PricePoint,
  type PriceTable,
  type WatchItem,
} from "../api";
import Watchlist from "../components/Watchlist";

const STORE_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2"];

/** Product x store comparison table, charts for the selected product, and the watchlist. */
export default function PricesPage({
  version,
  onWatchlistChanged,
}: {
  version: number;
  onWatchlistChanged: () => void;
}) {
  const [method, setMethod] = useState<PriceMethod>("weighted");
  const [table, setTable] = useState<PriceTable | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<PricePoint[]>([]);
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.prices(method).then(setTable).catch((e: Error) => setError(e.message));
  }, [method, version]);

  useEffect(() => {
    api.watchlist().then(setWatchlist).catch((e: Error) => setError(e.message));
  }, [version]);

  function updateWatchlist(items: WatchItem[]) {
    setWatchlist(items);
    onWatchlistChanged();
  }

  useEffect(() => {
    if (!selected) return;
    api.priceHistory(selected).then(setHistory).catch((e: Error) => setError(e.message));
  }, [selected, version]);

  const rows = useMemo(
    () =>
      (table?.rows ?? []).filter(
        (r) =>
          r.product.toLowerCase().includes(filter.toLowerCase()) ||
          r.category.toLowerCase().includes(filter.toLowerCase()),
      ),
    [table, filter],
  );
  const stores = table?.stores ?? [];
  const selectedRow = table?.rows.find((r) => r.product === selected) ?? null;
  const selectedWatch = watchlist.find((w) => w.product === selected) ?? null;

  const barData = selectedRow
    ? stores
        .filter((s) => selectedRow.prices[s])
        .map((s) => ({ store: s, price: selectedRow.prices[s].price }))
    : [];

  // One series per store on a real time axis (dates are sparse and differ per store).
  const historySeries = useMemo(() => {
    const byStore = new Map<string, { t: number; price: number }[]>();
    for (const p of history) {
      const points = byStore.get(p.store) ?? [];
      points.push({ t: new Date(p.date).getTime(), price: p.unit_price });
      byStore.set(p.store, points);
    }
    return Array.from(byStore.entries()).map(([store, points]) => ({
      store,
      points: points.sort((a, b) => a.t - b.t),
    }));
  }, [history]);

  if (error) return <div className="alert error">{error}</div>;
  if (!table) return <p className="muted">Loading prices...</p>;
  if (table.rows.length === 0)
    return <p className="muted">No prices yet. Save a receipt or load the synthetic demo data.</p>;

  return (
    <div className="stack">
      <section className="card">
        <div className="row gap spread">
          <h2>Price comparison</h2>
          <div className="row gap">
            <input
              type="search"
              aria-label="Filter products or categories"
              placeholder="Filter products or categories"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <select
              aria-label="Price method"
              value={method}
              onChange={(e) => setMethod(e.target.value as PriceMethod)}
            >
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
          <table>
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
                  <td>
                    {r.product} <span className="muted small">{r.category}</span>
                  </td>
                  {stores.map((s) => {
                    const cell = r.prices[s];
                    return (
                      <td
                        key={s}
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
        </div>
      </section>

      {selectedRow && (
        <section className="card">
          <h2>{selectedRow.product}</h2>
          <div className="charts">
            <div>
              <h3>Current price by store ($/{selectedRow.unit.replace("_", " ")})</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="store" />
                  <YAxis />
                  <Tooltip formatter={(v) => unitPrice(Number(v), selectedRow.unit)} />
                  <Bar dataKey="price" fill="#2563eb" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div>
              <h3>Observed prices over time</h3>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="t"
                    type="number"
                    scale="time"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={(t) => new Date(t).toISOString().slice(5, 10)}
                  />
                  <YAxis />
                  <Tooltip
                    labelFormatter={(t) => new Date(Number(t)).toISOString().slice(0, 10)}
                    formatter={(v) => unitPrice(Number(v), selectedRow.unit)}
                  />
                  <Legend />
                  {selectedWatch && (
                    <ReferenceLine
                      y={selectedWatch.target_price}
                      stroke="#b91c1c"
                      strokeDasharray="4 4"
                      label={{ value: "your target", position: "insideTopRight", fontSize: 12 }}
                    />
                  )}
                  {historySeries.map((series, i) => (
                    <Line
                      key={series.store}
                      name={series.store}
                      data={series.points}
                      dataKey="price"
                      stroke={STORE_COLORS[i % STORE_COLORS.length]}
                      dot
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      <Watchlist
        items={watchlist}
        products={table.rows.map((r) => ({ product: r.product, unit: r.unit }))}
        onChange={updateWatchlist}
      />
    </div>
  );
}
