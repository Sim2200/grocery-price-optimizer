import { useState } from "react";
import { api, type AssistResult, type ShoppingItem } from "../api";

/** Paste a recipe or a free-text list; get catalog products to add to the shopping list. */
export default function ListAssistant({ onAdd }: { onAdd: (items: ShoppingItem[]) => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<AssistResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setResult(await api.assistList(text));
    } catch (err) {
      setError((err as Error).message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const matched = result?.lines.filter((l) => l.product && l.quantity > 0) ?? [];
  const unmatched = result?.lines.filter((l) => !l.product) ?? [];

  function add() {
    onAdd(matched.map((l) => ({ product: l.product as string, quantity: l.quantity })));
    setResult(null);
    setText("");
  }

  return (
    <section className="card" aria-labelledby="assist-heading">
      <h2 id="assist-heading">Build a list from a recipe</h2>
      <form className="stack" onSubmit={submit}>
        <label>
          Recipe, dish or list
          <textarea
            rows={3}
            placeholder={'tacos for 4\n2 lb chicken breast, a dozen eggs'}
            value={text}
            onChange={(e) => setText(e.target.value)}
            required
          />
        </label>
        <div>
          <button type="submit" disabled={loading || !text.trim()}>
            {loading ? "Working..." : "Suggest items"}
          </button>
        </div>
      </form>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {result && (
        <div aria-live="polite">
          {result.notes.map((n) => (
            <p key={n} className="muted small">
              {n}
            </p>
          ))}
          {matched.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Suggested products</caption>
                <thead>
                  <tr>
                    <th scope="col">You asked for</th>
                    <th scope="col">Product</th>
                    <th scope="col" className="num">Quantity</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {matched.map((l, i) => (
                    <tr key={`${l.request}-${l.product}-${i}`}>
                      <td>{l.request}</td>
                      <td>{l.product}</td>
                      <td className="num">
                        {l.quantity} {l.unit.replace("_", " ")}
                      </td>
                      <td className="muted small">{l.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {unmatched.length > 0 && (
            <p className="muted small">
              Not in the catalog: {unmatched.map((l) => l.request).join(", ")}
            </p>
          )}
          <button onClick={add} disabled={matched.length === 0}>
            Add {matched.length} {matched.length === 1 ? "item" : "items"} to my list
          </button>
        </div>
      )}
    </section>
  );
}
