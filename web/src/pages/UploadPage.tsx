import { useEffect, useRef, useState } from "react";
import { api, type DraftReceipt, type Product } from "../api";
import DraftEditor from "../components/DraftEditor";

const CSV_EXAMPLE = `store,date,raw_name,quantity,unit,size,unit_price,line_total,total
Aldi,2026-07-02,ORG BANANAS,2.1,lb,,0.79,1.66,
Aldi,2026-07-02,WHL MILK,1,each,1 gal,3.29,3.29,4.95`;

interface Props {
  onSaved: () => void;
  demoMode: boolean;
}

/** Upload images/PDFs (or paste CSV), review the extracted items, then save. */
export default function UploadPage({ onSaved, demoMode }: Props) {
  const [drafts, setDrafts] = useState<DraftReceipt[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [csv, setCsv] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.products().then(setProducts).catch((e: Error) => setErrors([e.message]));
  }, []);

  async function handleFiles(files: FileList | File[]) {
    setBusy(true);
    setErrors([]);
    setNotice(null);
    const newDrafts: DraftReceipt[] = [];
    const newErrors: string[] = [];
    // One at a time: each file is a separate (possibly slow) model call.
    for (const file of Array.from(files)) {
      try {
        newDrafts.push(await api.extractReceipt(file));
      } catch (e) {
        newErrors.push(`${file.name}: ${(e as Error).message}`);
      }
    }
    setDrafts((d) => [...d, ...newDrafts]);
    setErrors(newErrors);
    setBusy(false);
  }

  async function parseCsv() {
    setErrors([]);
    try {
      const parsed = await api.parseCsv(csv);
      setDrafts((d) => [...d, ...parsed]);
      setCsv("");
    } catch (e) {
      setErrors([(e as Error).message]);
    }
  }

  async function save(index: number) {
    setSaving(true);
    setErrors([]);
    try {
      const { receipt_id } = await api.saveReceipt(drafts[index]);
      setDrafts((d) => d.filter((_, i) => i !== index));
      setNotice(`Saved receipt #${receipt_id}.`);
      onSaved();
    } catch (e) {
      setErrors([(e as Error).message]);
    } finally {
      setSaving(false);
    }
  }

  async function createProduct(product: Product) {
    try {
      await api.createProduct(product);
      setProducts(await api.products());
    } catch (e) {
      setErrors([(e as Error).message]);
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h2>1. Add receipts</h2>
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
          }}
          onClick={() => fileInput.current?.click()}
        >
          {busy ? (
            <p>Extracting... (a real receipt takes a few seconds)</p>
          ) : (
            <>
              <p>
                <strong>Drop receipt photos or PDFs here</strong>, or click to choose files.
              </p>
              <p className="muted small">PNG, JPEG, WEBP, GIF or PDF.</p>
            </>
          )}
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".png,.jpg,.jpeg,.webp,.gif,.pdf"
            hidden
            onChange={(e) => e.target.files && handleFiles(e.target.files)}
          />
        </div>
        {demoMode && (
          <p className="muted small">
            Demo mode: without an ANTHROPIC_API_KEY the server can only "extract" the bundled
            synthetic images in <code>data/synthetic/images/</code>. Use CSV entry for anything else.
          </p>
        )}

        <details>
          <summary>Or enter items manually (CSV)</summary>
          <p className="muted small">
            One row per item. Rows with the same store and date become one receipt.
          </p>
          <textarea
            rows={5}
            value={csv}
            placeholder={CSV_EXAMPLE}
            onChange={(e) => setCsv(e.target.value)}
          />
          <div className="row gap">
            <button onClick={parseCsv} disabled={!csv.trim()}>
              Parse CSV
            </button>
            <button className="secondary" onClick={() => setCsv(CSV_EXAMPLE)}>
              Use example
            </button>
          </div>
        </details>
      </section>

      {errors.map((e) => (
        <div key={e} className="alert error">
          {e}
        </div>
      ))}
      {notice && <div className="alert info">{notice}</div>}

      {drafts.length > 0 && <h2>2. Review and correct ({drafts.length} pending)</h2>}
      {drafts.map((draft, i) => (
        <DraftEditor
          key={`${draft.file_name ?? "csv"}-${i}`}
          draft={draft}
          products={products}
          saving={saving}
          onChange={(d) => setDrafts((all) => all.map((x, j) => (j === i ? d : x)))}
          onSave={() => save(i)}
          onDiscard={() => setDrafts((all) => all.filter((_, j) => j !== i))}
          onCreateProduct={createProduct}
        />
      ))}
    </div>
  );
}
