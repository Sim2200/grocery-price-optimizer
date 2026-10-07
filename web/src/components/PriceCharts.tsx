"use client";

// The charts for one selected product. Kept in its own module so the charting library
// (the largest dependency in the app) is only downloaded once a product is selected;
// PricesPage loads this with next/dynamic.

import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { unitPrice, type PricePoint, type PriceRow, type WatchItem } from "../api";

const STORE_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2"];

interface Props {
  row: PriceRow;
  stores: string[];
  history: PricePoint[];
  watch: WatchItem | null;
}

export default function PriceCharts({ row, stores, history, watch }: Props) {
  const barData = stores.filter((s) => row.prices[s]).map((s) => ({ store: s, price: row.prices[s].price }));

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

  return (
    <div className="charts">
      <div>
        <h3>Current price by store ($/{row.unit.replace("_", " ")})</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={barData}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="store" />
            <YAxis />
            <Tooltip formatter={(v) => unitPrice(Number(v), row.unit)} />
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
              formatter={(v) => unitPrice(Number(v), row.unit)}
            />
            <Legend />
            {watch && (
              <ReferenceLine
                y={watch.target_price}
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
  );
}
