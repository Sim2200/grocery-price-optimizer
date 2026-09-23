import { useState } from "react";
import {
  RECEIPT_UNITS,
  type DraftReceipt,
  type LineItem,
  type LineMatch,
  type Product,
  type ReceiptUnit,
} from "../api";

interface Props {
  draft: DraftReceipt;
  products: Product[];
  onChange: (draft: DraftReceipt) => void;
  onSave: () => void;
  onDiscard: () => void;
  onCreateProduct: (product: Product) => Promise<void>;
  saving: boolean;
}

function MatchBadge({ line }: { line: LineMatch }) {
  if (line.match_method === "user") return <span className="badge badge-ok">you</span>;
  if (!line.product) return <span className="badge badge-bad">unmatched</span>;
  const score = line.match_score != null ? ` ${Math.round(line.match_score)}` : "";
  const cls = line.needs_review ? "badge-warn" : "badge-ok";
  return <span className={`badge ${cls}`}>{line.match_method + score}</span>;
}

const EMPTY_ITEM: LineItem = {
  raw_name: "",
  quantity: 1,
  unit: "each",
  size: null,
  unit_price: 0,
  line_total: 0,
};

/** Editable table for reviewing one extracted receipt before it is saved. */
export default function DraftEditor(props: Props) {
  const { draft, products, onChange } = props;
  const [newProduct, setNewProduct] = useState<Product>({ name: "", unit: "oz", category: "other" });
  const [showNewProduct, setShowNewProduct] = useState(false);

  const itemsSum = draft.lines.reduce((sum, l) => sum + (Number(l.item.line_total) || 0), 0);
  const unresolved = draft.lines.filter((l) => !l.product).length;

  function updateLine(index: number, patch: Partial<LineMatch>) {
    const lines = draft.lines.map((l, i) => (i === index ? { ...l, ...patch } : l));
    onChange({ ...draft, lines });
  }

  function updateItem(index: number, patch: Partial<LineItem>) {
    updateLine(index, { item: { ...draft.lines[index].item, ...patch } });
  }

  function setProduct(index: number, product: string) {
    updateLine(index, {
      product: product || null,
      match_method: "user",
      match_score: 100,
      needs_review: false,
    });
  }

  function addLine() {
    const line: LineMatch = {
      item: { ...EMPTY_ITEM },
      product: null,
      match_method: "user",
      match_score: null,
      needs_review: true,
      candidates: [],
    };
    onChange({ ...draft, lines: [...draft.lines, line] });
  }

  function removeLine(index: number) {
    onChange({ ...draft, lines: draft.lines.filter((_, i) => i !== index) });
  }

  async function createProduct() {
    if (!newProduct.name.trim()) return;
    await props.onCreateProduct({ ...newProduct, name: newProduct.name.trim() });
    setNewProduct({ name: "", unit: "oz", category: "other" });
    setShowNewProduct(false);
  }

  return (
    <div className="card">
      <div className="draft-header">
        <label>
          Store
          <input value={draft.store} onChange={(e) => onChange({ ...draft, store: e.target.value })} />
        </label>
        <label>
          Date
          <input
            type="date"
            value={draft.date ?? ""}
            onChange={(e) => onChange({ ...draft, date: e.target.value || null })}
          />
        </label>
        <label>
          Receipt total
          <input
            type="number"
            step="0.01"
            value={draft.total ?? ""}
            onChange={(e) =>
              onChange({ ...draft, total: e.target.value === "" ? null : Number(e.target.value) })
            }
          />
        </label>
        <div className="muted small">
          Source: {draft.source}
          {draft.file_name ? ` (${draft.file_name})` : ""}
          <br />
          Lines sum to ${itemsSum.toFixed(2)}
        </div>
      </div>

      {draft.warnings.length > 0 && (
        <div className="alert warn">
          <strong>Please double-check:</strong>
          <ul>
            {draft.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="table-wrap">
        <table className="edit-table">
          <thead>
            <tr>
              <th>Printed name</th>
              <th>Qty</th>
              <th>Unit</th>
              <th>Size</th>
              <th>Unit price</th>
              <th>Line total</th>
              <th>Product</th>
              <th>Match</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {draft.lines.map((line, i) => {
              const suggested = line.candidates.map((c) => c.product);
              const others = products.map((p) => p.name).filter((n) => !suggested.includes(n));
              return (
                <tr key={i} className={line.product ? "" : "row-unmatched"}>
                  <td>
                    <input
                      value={line.item.raw_name}
                      onChange={(e) => updateItem(i, { raw_name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="num"
                      type="number"
                      step="0.01"
                      value={line.item.quantity}
                      onChange={(e) => updateItem(i, { quantity: Number(e.target.value) })}
                    />
                  </td>
                  <td>
                    <select
                      value={line.item.unit}
                      onChange={(e) => updateItem(i, { unit: e.target.value as ReceiptUnit })}
                    >
                      {RECEIPT_UNITS.map((u) => (
                        <option key={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      className="short"
                      value={line.item.size ?? ""}
                      placeholder="e.g. 16 oz"
                      onChange={(e) => updateItem(i, { size: e.target.value || null })}
                    />
                  </td>
                  <td>
                    <input
                      className="num"
                      type="number"
                      step="0.01"
                      value={line.item.unit_price}
                      onChange={(e) => updateItem(i, { unit_price: Number(e.target.value) })}
                    />
                  </td>
                  <td>
                    <input
                      className="num"
                      type="number"
                      step="0.01"
                      value={line.item.line_total}
                      onChange={(e) => updateItem(i, { line_total: Number(e.target.value) })}
                    />
                  </td>
                  <td>
                    <select value={line.product ?? ""} onChange={(e) => setProduct(i, e.target.value)}>
                      <option value="">(not a tracked product)</option>
                      {suggested.length > 0 && (
                        <optgroup label="Suggestions">
                          {line.candidates.map((c) => (
                            <option key={c.product} value={c.product}>
                              {c.product} ({Math.round(c.score)})
                            </option>
                          ))}
                        </optgroup>
                      )}
                      <optgroup label="All products">
                        {others.map((n) => (
                          <option key={n}>{n}</option>
                        ))}
                      </optgroup>
                    </select>
                  </td>
                  <td>
                    <MatchBadge line={line} />
                  </td>
                  <td>
                    <button className="link" title="Remove line" onClick={() => removeLine(i)}>
                      remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="row gap">
        <button className="secondary" onClick={addLine}>
          Add line
        </button>
        <button className="secondary" onClick={() => setShowNewProduct((s) => !s)}>
          New product
        </button>
        {showNewProduct && (
          <div className="row gap inline-form">
            <input
              placeholder="product name, e.g. kimchi"
              value={newProduct.name}
              onChange={(e) => setNewProduct({ ...newProduct, name: e.target.value })}
            />
            <select
              value={newProduct.unit}
              onChange={(e) => setNewProduct({ ...newProduct, unit: e.target.value })}
            >
              {["lb", "oz", "fl_oz", "gal", "each"].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
            <button onClick={createProduct}>Create</button>
          </div>
        )}
      </div>

      <div className="row gap end">
        <span className="muted small">
          {unresolved > 0
            ? `${unresolved} line(s) not linked to a product will be saved without a price.`
            : "All lines linked to products."}{" "}
          Products you pick by hand are remembered for next time.
        </span>
        <button className="secondary" onClick={props.onDiscard}>
          Discard
        </button>
        <button onClick={props.onSave} disabled={props.saving || !draft.store.trim()}>
          {props.saving ? "Saving..." : "Save receipt"}
        </button>
      </div>
    </div>
  );
}
