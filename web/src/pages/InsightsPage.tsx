import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, money, type Amount, type Insights } from "../api";

function SpendChart({ title, data, color }: { title: string; data: Amount[]; color: string }) {
  return (
    <figure className="chart-figure">
      <figcaption>
        <h3>{title}</h3>
      </figcaption>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" interval={0} tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={(v) => `$${v}`} width={50} />
          <Tooltip formatter={(v) => money(Number(v))} />
          <Bar dataKey="amount" fill={color} />
        </BarChart>
      </ResponsiveContainer>
      {/* The same numbers as text, for screen readers and small screens. */}
      <ul className="sr-only">
        {data.map((d) => (
          <li key={d.label}>
            {d.label}: {money(d.amount)}
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** Where the money went, and what past trips would have cost if planned. */
export default function InsightsPage({ version }: { version: number }) {
  const [tripCost, setTripCost] = useState(5);
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .insights(tripCost)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [tripCost, version]);

  if (error) return <div className="alert error" role="alert">{error}</div>;
  if (!data) return <p className="muted">Loading insights...</p>;
  if (data.receipts === 0)
    return <p className="muted">No receipts yet. Save a receipt or load the synthetic demo data.</p>;

  return (
    <div className="stack">
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
          <table>
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
                  <td>{t.date}</td>
                  <td>{t.store}</td>
                  <td className="num">{money(t.actual)}</td>
                  <td className="num">{money(t.optimal)}</td>
                  <td className={`num ${t.saved > 0 ? "cheapest" : ""}`}>{money(t.saved)}</td>
                  <td>{t.stores_in_plan.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
