import { useEffect, useState } from "react";
import { api, money, unitPrice, type Product, type ReceiptSummary, type SavedLineItem } from "../api";

interface Props {
  version: number;
  onChanged: () => void;
}

/** Saved receipts, their line items, and in-place product corrections. */
export default function ReceiptsPage({ version, onChanged }: Props) {
  const [receipts, setReceipts] = useState<ReceiptSummary[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [items, setItems] = useState<SavedLineItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.receipts(), api.products()])
      .then(([r, p]) => {
        setReceipts(r);
        setProducts(p);
      })
      .catch((e: Error) => setError(e.message));
  }, [version]);

  useEffect(() => {
    if (selected == null) {
      setItems([]);
      return;
    }
    api.receiptItems(selected).then(setItems).catch((e: Error) => setError(e.message));
  }, [selected, version]);

  async function rematch(item: SavedLineItem, product: string) {
    try {
      const updated = await api.rematch(item.id, product || null, true);
      setItems((all) => all.map((i) => (i.id === item.id ? updated : i)));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Delete this receipt and its prices?")) return;
    await api.deleteReceipt(id);
    if (selected === id) setSelected(null);
    onChanged();
  }

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <section className="card">
        <h2>Saved receipts</h2>
        {receipts.length === 0 ? (
          <p className="muted">No receipts yet. Upload one, or load the synthetic demo data.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Store</th>
                  <th>Items</th>
                  <th>Unmatched</th>
                  <th>Total</th>
                  <th>Source</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {receipts.map((r) => (
                  <tr key={r.id} className={selected === r.id ? "row-selected" : ""}>
                    <td>{r.purchase_date}</td>
                    <td>{r.store}</td>
                    <td>{r.n_items}</td>
                    <td>{r.n_unmatched > 0 ? <span className="badge badge-bad">{r.n_unmatched}</span> : 0}</td>
                    <td>{r.total != null ? money(r.total) : "-"}</td>
                    <td className="muted small">{r.source}</td>
                    <td className="row gap">
                      <button className="link" onClick={() => setSelected(r.id)}>
                        view
                      </button>
                      <button className="link danger" onClick={() => remove(r.id)}>
                        delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected != null && (
        <section className="card">
          <h2>Receipt #{selected}</h2>
          <p className="muted small">
            Changing a product recomputes that line's comparable price and remembers the printed
            name for future receipts.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Printed name</th>
                  <th>Qty</th>
                  <th>Size</th>
                  <th>Line total</th>
                  <th>Product</th>
                  <th>Comparable price</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} className={it.product ? "" : "row-unmatched"}>
                    <td>{it.raw_name}</td>
                    <td>
                      {it.quantity} {it.unit}
                    </td>
                    <td>{it.size ?? "-"}</td>
                    <td>{money(it.line_total)}</td>
                    <td>
                      <select
                        aria-label={`Product for ${it.raw_name}`}
                        value={it.product ?? ""}
                        onChange={(e) => rematch(it, e.target.value)}
                      >
                        <option value="">(not a tracked product)</option>
                        {products.map((p) => (
                          <option key={p.name}>{p.name}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {it.comparable_price != null && it.product_unit
                        ? unitPrice(it.comparable_price, it.product_unit)
                        : it.product
                          ? "size needed"
                          : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
