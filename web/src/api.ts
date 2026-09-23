// Typed client for the FastAPI backend. Every network call in the UI goes
// through this file, and the types mirror src/grocery_optimizer/api/models.py.

export type ReceiptUnit =
  | "each" | "lb" | "oz" | "kg" | "g" | "gal" | "qt" | "pt" | "fl_oz" | "l" | "ml";

export const RECEIPT_UNITS: ReceiptUnit[] = [
  "each", "lb", "oz", "kg", "g", "gal", "qt", "pt", "fl_oz", "l", "ml",
];

export interface Health {
  status: string;
  demo_mode: boolean;
  extractor: string;
  model: string;
}

export interface Product {
  name: string;
  unit: string;
  category: string;
}

export interface LineItem {
  raw_name: string;
  quantity: number;
  unit: ReceiptUnit;
  size: string | null;
  unit_price: number;
  line_total: number;
}

export interface Candidate {
  product: string;
  score: number;
}

export interface LineMatch {
  item: LineItem;
  product: string | null;
  match_method: string; // "alias" | "fuzzy" | "llm" | "unmatched" | "user"
  match_score: number | null;
  needs_review: boolean;
  candidates: Candidate[];
}

export interface DraftReceipt {
  store: string;
  date: string | null; // YYYY-MM-DD
  total: number | null;
  lines: LineMatch[];
  warnings: string[];
  source: string;
  file_name: string | null;
}

export interface ReceiptSummary {
  id: number;
  store: string;
  purchase_date: string | null;
  total: number | null;
  source: string;
  file_name: string | null;
  n_items: number;
  n_unmatched: number;
}

export interface SavedLineItem {
  id: number;
  receipt_id: number;
  store: string;
  purchase_date: string | null;
  raw_name: string;
  quantity: number;
  unit: string;
  size: string | null;
  unit_price: number;
  line_total: number;
  product: string | null;
  match_method: string | null;
  match_score: number | null;
  comparable_price: number | null;
  product_unit: string | null;
}

export interface PriceCell {
  price: number;
  n_observations: number;
  last_seen: string;
}

export interface PriceRow {
  product: string;
  unit: string;
  category: string;
  prices: Record<string, PriceCell>;
  cheapest_store: string | null;
}

export interface PriceTable {
  method: string;
  stores: string[];
  rows: PriceRow[];
}

export interface PricePoint {
  store: string;
  date: string;
  unit_price: number;
}

export interface ShoppingItem {
  product: string;
  quantity: number;
}

export type PriceMethod = "weighted" | "latest";

export interface PlanRequest {
  items: ShoppingItem[];
  stores: string[] | null;
  trip_cost: number;
  trip_costs?: Record<string, number> | null;
  max_stores: number | null;
  price_method: PriceMethod;
}

export interface PlanLine {
  product: string;
  quantity: number;
  unit: string;
  unit_price: number;
  cost: number;
}

export interface StoreStop {
  store: string;
  trip_cost: number;
  items: PlanLine[];
  subtotal: number;
}

export interface Plan {
  name: string;
  status: string;
  total: number;
  items_total: number;
  trips_total: number;
  stops: StoreStop[];
}

export interface PlanResult {
  optimal: Plan;
  single_store: Plan | null;
  greedy: Plan;
  single_store_candidates: Record<string, number>;
  savings_vs_single_store: { amount: number; percent: number } | null;
  unavailable: string[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail) message = JSON.stringify(body.detail);
    } catch {
      // response had no JSON body; keep the status text
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const api = {
  health: () => request<Health>("/api/health"),
  loadDemo: (reset = true) =>
    request<{ receipts_loaded: number }>("/api/demo/load", json("POST", { reset })),
  sampleShoppingList: () => request<ShoppingItem[]>("/api/demo/shopping-list"),

  stores: () => request<string[]>("/api/stores"),
  products: () => request<Product[]>("/api/products"),
  createProduct: (p: Product) => request<Product>("/api/products", json("POST", p)),

  extractReceipt: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DraftReceipt>("/api/receipts/extract", { method: "POST", body: form });
  },
  parseCsv: (csv: string) => request<DraftReceipt[]>("/api/receipts/parse-csv", json("POST", { csv })),
  saveReceipt: (draft: DraftReceipt) =>
    request<{ receipt_id: number }>(
      "/api/receipts",
      json("POST", {
        store: draft.store,
        date: draft.date || null,
        total: draft.total,
        lines: draft.lines,
        source: draft.source,
        file_name: draft.file_name,
      }),
    ),
  receipts: () => request<ReceiptSummary[]>("/api/receipts"),
  receiptItems: (id: number) => request<SavedLineItem[]>(`/api/receipts/${id}/items`),
  deleteReceipt: (id: number) => request<void>(`/api/receipts/${id}`, { method: "DELETE" }),
  rematch: (lineItemId: number, product: string | null, remember = true) =>
    request<SavedLineItem>(`/api/line-items/${lineItemId}`, json("PATCH", { product, remember })),

  prices: (method: PriceMethod = "weighted") =>
    request<PriceTable>(`/api/prices?method=${method}`),
  priceHistory: (product: string) =>
    request<PricePoint[]>(`/api/prices/history?product=${encodeURIComponent(product)}`),

  plan: (body: PlanRequest) => request<PlanResult>("/api/plan", json("POST", body)),
};

export function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function unitPrice(value: number, unit: string): string {
  const digits = value < 1 ? 3 : 2;
  return `$${value.toFixed(digits)}/${unit.replace("_", " ")}`;
}
