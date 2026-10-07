// A horizontal bar list for one spending breakdown. Plain HTML and CSS instead of the charting
// library: these are simple totals, the labels stay readable at 360 px (no angled axis text),
// the numbers are real text for screen readers, and the Insights page no longer downloads the
// charting library at all (results/lighthouse_after.json has the JS difference).

import { money, type Amount } from "../api";

export default function SpendChart({ title, data, color }: { title: string; data: Amount[]; color: string }) {
  const max = Math.max(...data.map((d) => d.amount), 0);
  return (
    <figure className="chart-figure">
      <figcaption>
        <h3>{title}</h3>
      </figcaption>
      <ul className="bar-list">
        {data.map((d) => (
          <li key={d.label}>
            <span className="bar-label">{d.label}</span>
            <span className="bar-track" aria-hidden="true">
              <span className="bar-fill" style={{ width: `${max ? (d.amount / max) * 100 : 0}%`, background: color }} />
            </span>
            <span className="bar-value">{money(d.amount)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
