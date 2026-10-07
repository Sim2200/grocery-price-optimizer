"use client";

import { useCallback, useState } from "react";
import { api, money, type Insights } from "../api";
import SpendChart from "../components/SpendChart";
import { ErrorState, Skeleton, StaleBanner } from "../components/Status";
import { useCachedQuery } from "../lib/useCachedQuery";

/** Where the money went, and what past trips would have cost if planned. */
export default function InsightsPage({ version }: { version: number }) {
  const [tripCost, setTripCost] = useState(5);
  const fetchInsights = useCallback(() => api.insights(tripCost), [tripCost]);
  const query = useCachedQuery<Insights>(`insights:${tripCost}`, fetchInsights, [version]);
  const data = query.data;

  if (!data && query.loading) return <Skeleton rows={6} label="Loading insights" />;
  if (!data) return <ErrorState message={query.error ?? "Could not load insights."} onRetry={query.retry} />;
  if (data.receipts === 0)
    return <p className="muted">No receipts yet. Save a receipt or load the synthetic demo data.</p>;

  return (
    <div className="stack">
      {query.staleSince !== null && <StaleBanner since={query.staleSince} onRetry={query.retry} />}
      <section className="card" aria-labelledby="spend-heading">
        <h2 id="spend-heading">Spending</h2>
        <p>
          <span className="big">{money(data.total_spend)}</span>{" "}
          <span className="muted">across {data.receipts} receipts (item totals, before tax)</span>
        </p>
        <div className="charts">
          <SpendChart title="By store" data={data.by_store} color="#2563eb" />
          <SpendChart title="By category" data={data.by_category} color="#16a34a" />
          <SpendChart title="By month" data={data.by_month} color="#d97706" />
        </div>
      </section>

      <section className="card" aria-labelledby="savings-heading">
        <div className="row gap spread">
          <h2 id="savings-heading">What if you had used the planner?</h2>
          <label className="inline-label">
            Trip cost per store ($)
            <input
              className="num"
              type="number"
              min="0"
              step="0.5"
              inputMode="decimal"
              value={tripCost}
              onChange={(e) => setTripCost(Math.max(0, Number(e.target.value)))}
            />
          </label>
        </div>
        <p>
          Estimated savings: <strong className="big">{money(data.estimated_savings)}</strong>{" "}
          <span className="muted">
            ({data.estimated_savings_percent}% of {money(data.actual_total)})
          </span>
        </p>
        <p className="muted small">
          Each past trip is re-planned with only the prices known on that day. The store you
          visited keeps the prices you actually paid, so a trip can never look worse than what you
          did. Lines without a comparable price are left out.
        </p>
        <div className="table-wrap">
          <table className="responsive-table">
            <caption className="sr-only">Savings per past trip</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Store</th>
                <th scope="col" className="num">Paid (+ trip)</th>
                <th scope="col" className="num">Planned</th>
                <th scope="col" className="num">Saved</th>
                <th scope="col">Plan would visit</th>
              </tr>
            </thead>
            <tbody>
              {data.trips.map((t) => (
                <tr key={t.receipt_id}>
                  <td className="cell-title">{t.date}</td>
                  <td data-label="Store">{t.store}</td>
                  <td data-label="Paid (+ trip)" className="num">{money(t.actual)}</td>
                  <td data-label="Planned" className="num">{money(t.optimal)}</td>
                  <td data-label="Saved" className={`num ${t.saved > 0 ? "cheapest" : ""}`}>{money(t.saved)}</td>
                  <td data-label="Plan would visit">{t.stores_in_plan.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
