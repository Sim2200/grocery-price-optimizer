"""FastAPI application.

Run:  uvicorn --factory grocery_optimizer.api.app:create_app --reload
Docs: http://localhost:8000/docs  (OpenAPI, generated from the Pydantic models)

Design notes
- The API is a thin layer: every endpoint calls into the core package
  (ingest, matching, pricing, optimizer) so the same logic is used by the
  CLI and the tests.
- Receipt upload is two-step on purpose: POST /api/receipts/extract returns a
  *draft* with suggested product matches; the UI lets the user fix it, then
  POST /api/receipts saves it. Nothing unreviewed silently enters the price DB.
- Observability: every request gets an ID (X-Request-ID) that appears in its
  JSON log lines; Prometheus metrics are served at /metrics; OpenTelemetry
  spans cover extraction, matching and optimization (see observability/).
- One database session per request (a FastAPI dependency). `db_path` can be
  a SQLite file or any SQLAlchemy URL (e.g. Postgres via DATABASE_URL).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanExporter

from ..alerts import latest_by_store, price_alerts
from ..catalog import Product, load_catalog
from ..config import DATABASE_URL, LLM_MATCHING, LLM_MODEL, PROJECT_ROOT
from ..db import PriceDB
from ..extraction import (
    VisionReceiptExtractor,
    DemoReceiptExtractor,
    ExtractionError,
    ReceiptExtractor,
    get_extractor,
)
from ..ingest import (
    add_custom_product,
    build_matcher,
    load_demo_data,
    match_receipt,
    save_receipt,
)
from ..insights import replay_trips, spend_breakdown
from ..list_assistant import ListAssistant, ListAssistantError, get_list_assistant
from ..manual_entry import ManualEntryError, receipts_from_csv
from ..matching import MatchResult, ProductMatcher
from ..optimizer import ListItem, Plan
from ..planning import plan_trip, read_shopping_list
from ..pricing import current_prices
from ..schemas import Receipt, consistency_warnings
from ..observability import metrics
from ..observability.log import configure_logging, request_id_var
from ..observability.tracing import setup_tracing
from ..units import COMPARABLE_UNITS
from . import models as m

logger = logging.getLogger("grocery_optimizer.api")
tracer = trace.get_tracer("grocery_optimizer.api")

FRONTEND_DIST = PROJECT_ROOT / "web" / "out"  # Next.js static export
SAMPLE_LIST = PROJECT_ROOT / "data" / "sample_shopping_list.csv"


def create_app(
    db_path: str | Path = DATABASE_URL,
    extractor: ReceiptExtractor | None = None,
    use_llm_matching: bool = LLM_MATCHING,
    span_exporter: SpanExporter | None = None,
    list_assistant: Callable[[list[Product], ProductMatcher], ListAssistant] = get_list_assistant,
) -> FastAPI:
    """App factory. Tests pass a temp DB path and a fake extractor.

    `db_path` is a SQLite file path or a SQLAlchemy database URL. `span_exporter`
    lets tests capture trace spans in memory; `list_assistant` builds the recipe/list
    assistant (tests pass one with a fake LLM client)."""
    configure_logging()
    app = FastAPI(
        title="Grocery Price Optimizer API",
        version="0.1.0",
        description="Receipts in, cheapest shopping plan out. Sample data is SYNTHETIC.",
    )
    app.state.db_path = str(db_path)
    app.state.extractor = extractor or get_extractor()
    app.state.use_llm_matching = use_llm_matching
    app.state.list_assistant = list_assistant

    # Vite dev server runs on :5173 and calls the API on :8000.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def observe_requests(request: Request, call_next):
        """Request ID + one JSON access-log line + HTTP metrics for every request."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)  # picked up by every log line in this request
        start = time.perf_counter()
        status = 500  # stays 500 if the endpoint raises
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed = time.perf_counter() - start
            # The route template ("/api/receipts/{receipt_id}") keeps metric labels few.
            route = request.scope.get("route")
            route_label = getattr(route, "path", "unmatched")
            metrics.HTTP_REQUESTS.labels(request.method, route_label, str(status)).inc()
            metrics.HTTP_LATENCY.labels(request.method, route_label).observe(elapsed)
            logger.info("request", extra={
                "method": request.method, "path": request.url.path, "route": route_label,
                "status": status, "duration_ms": round(elapsed * 1000, 1)})
            request_id_var.reset(token)

    app.state.tracing = setup_tracing(app, exporter=span_exporter)

    setup_db = PriceDB(app.state.db_path)
    setup_db.sync_catalog(load_catalog())
    setup_db.close()

    def get_db(request: Request) -> Iterator[PriceDB]:
        db = PriceDB(request.app.state.db_path)
        try:
            yield db
        finally:
            db.close()

    # ----- probes (Docker HEALTHCHECK, Kubernetes liveness/readiness) --------------
    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict:
        """Liveness: the process is up and serving requests. Deliberately checks nothing else,
        so a database outage doesn't make Kubernetes restart healthy pods."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["meta"])
    def readyz(db: PriceDB = Depends(get_db)) -> dict:
        """Readiness: the database answers, so this instance can take traffic."""
        try:
            db.ping()
        except Exception as exc:  # any DB error means "not ready"
            raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from exc
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        """Prometheus scrape endpoint."""
        body, content_type = metrics.render()
        return Response(body, media_type=content_type)

    # ----- meta --------------------------------------------------------------
    @app.get("/api/health", response_model=m.Health, tags=["meta"])
    def health(request: Request) -> m.Health:
        ext = request.app.state.extractor
        name = "llm" if isinstance(ext, VisionReceiptExtractor) else (
            "demo" if isinstance(ext, DemoReceiptExtractor) else type(ext).__name__)
        return m.Health(status="ok", demo_mode=isinstance(ext, DemoReceiptExtractor),
                        extractor=name, model=LLM_MODEL)

    @app.post("/api/demo/load", response_model=m.DemoLoadOut, tags=["meta"])
    def load_demo(body: m.DemoLoadIn, db: PriceDB = Depends(get_db)) -> m.DemoLoadOut:
        """Load the bundled SYNTHETIC receipts (optionally wiping existing data first)."""
        if body.reset:
            db.reset_data()
        return m.DemoLoadOut(receipts_loaded=load_demo_data(db))

    @app.get("/api/demo/shopping-list", response_model=list[m.ShoppingItem], tags=["meta"])
    def sample_shopping_list() -> list[m.ShoppingItem]:
        items = read_shopping_list(SAMPLE_LIST.read_text())
        return [m.ShoppingItem(product=i.product, quantity=i.quantity) for i in items]

    # ----- products & stores ----------------------------------------------------
    @app.get("/api/stores", response_model=list[str], tags=["catalog"])
    def list_stores(db: PriceDB = Depends(get_db)) -> list[str]:
        return db.store_names()

    @app.get("/api/products", response_model=list[m.ProductOut], tags=["catalog"])
    def list_products(db: PriceDB = Depends(get_db)) -> list[m.ProductOut]:
        return [m.ProductOut(name=p.name, unit=p.unit, category=p.category) for p in db.products()]

    @app.post("/api/products", response_model=m.ProductOut, status_code=201, tags=["catalog"])
    def create_product(body: m.ProductIn, db: PriceDB = Depends(get_db)) -> m.ProductOut:
        if body.unit not in COMPARABLE_UNITS:
            raise HTTPException(422, f"unit must be one of {', '.join(COMPARABLE_UNITS)}")
        product = add_custom_product(db, body.name, body.unit, body.category)
        return m.ProductOut(name=product.name, unit=product.unit, category=product.category)

    # ----- receipts ----------------------------------------------------------------
    def _draft(receipt: Receipt, db: PriceDB, source: str, file_name: str | None,
               use_llm: bool) -> m.DraftReceipt:
        with tracer.start_as_current_span("receipt.match") as span:
            matches = match_receipt(receipt, build_matcher(db, use_llm=use_llm))
            span.set_attribute("receipt.line_items", len(matches))
            span.set_attribute("receipt.needs_review", sum(mr.needs_review for mr in matches))
        for mr in matches:
            metrics.LINES_MATCHED.labels(mr.method).inc()
        lines = [
            m.LineMatch(
                item=item, product=mr.product, match_method=mr.method, match_score=mr.score,
                needs_review=mr.needs_review,
                candidates=[m.Candidate(product=p, score=s) for p, s in mr.candidates],
            )
            for item, mr in zip(receipt.line_items, matches, strict=True)
        ]
        return m.DraftReceipt(store=receipt.store, date=receipt.date, total=receipt.total,
                              lines=lines, warnings=consistency_warnings(receipt),
                              source=source, file_name=file_name)

    @app.post("/api/receipts/extract", response_model=m.DraftReceipt, tags=["receipts"])
    def extract_receipt(request: Request, file: UploadFile = File(...),
                        db: PriceDB = Depends(get_db)) -> m.DraftReceipt:
        """Upload an image/PDF. Returns a draft with suggested matches; nothing is saved yet.

        A plain (sync) endpoint on purpose: the LLM call blocks, and FastAPI
        runs sync endpoints in a worker thread so the event loop stays free."""
        data = file.file.read()
        if not data:
            raise HTTPException(400, "Empty file")
        extractor = request.app.state.extractor
        source = "demo" if isinstance(extractor, DemoReceiptExtractor) else "llm"
        with tracer.start_as_current_span("receipt.extract") as span:
            span.set_attribute("extractor", source)
            span.set_attribute("file.size_bytes", len(data))
            try:
                receipt = extractor.extract(data, file.filename or "upload")
            except ExtractionError as exc:
                metrics.RECEIPTS_EXTRACTED.labels(source, "error").inc()
                logger.warning("extraction failed", extra={"extractor": source, "error": str(exc)})
                raise HTTPException(422, str(exc)) from exc
            span.set_attribute("receipt.line_items", len(receipt.line_items))
        metrics.RECEIPTS_EXTRACTED.labels(source, "success").inc()
        logger.info("receipt extracted", extra={
            "extractor": source, "store": receipt.store, "line_items": len(receipt.line_items)})
        return _draft(receipt, db, source, file.filename, request.app.state.use_llm_matching)

    @app.post("/api/receipts/parse-csv", response_model=list[m.DraftReceipt], tags=["receipts"])
    def parse_csv(body: m.CsvIn, db: PriceDB = Depends(get_db)) -> list[m.DraftReceipt]:
        """Manual entry: CSV text -> drafts for review (one per store + date)."""
        try:
            receipts = receipts_from_csv(body.csv)
        except ManualEntryError as exc:
            raise HTTPException(422, str(exc)) from exc
        return [_draft(r, db, "manual", None, False) for r in receipts]

    @app.post("/api/receipts", response_model=m.SavedReceipt, status_code=201, tags=["receipts"])
    def create_receipt(body: m.SaveReceiptIn, db: PriceDB = Depends(get_db)) -> m.SavedReceipt:
        """Save a reviewed receipt. Lines with match_method='user' become aliases."""
        known = {p.name for p in db.products()}
        unknown = {line.product for line in body.lines if line.product and line.product not in known}
        if unknown:
            raise HTTPException(422, f"Unknown products: {', '.join(sorted(unknown))}")
        matches = [
            MatchResult(line.item.raw_name, line.product, line.match_score or 0.0,
                        line.match_method, False)
            for line in body.lines
        ]
        receipt_id = save_receipt(db, body.to_receipt(), matches, body.source, body.file_name)
        metrics.RECEIPTS_SAVED.labels(body.source).inc()
        logger.info("receipt saved", extra={"receipt_id": receipt_id, "source": body.source,
                                            "line_items": len(body.lines)})
        return m.SavedReceipt(receipt_id=receipt_id)

    @app.get("/api/receipts", response_model=list[m.ReceiptSummary], tags=["receipts"])
    def list_receipts(db: PriceDB = Depends(get_db)) -> list[dict]:
        return db.receipts()

    @app.get("/api/receipts/{receipt_id}/items", response_model=list[m.LineItemOut], tags=["receipts"])
    def receipt_items(receipt_id: int, db: PriceDB = Depends(get_db)) -> list[dict]:
        return db.line_items(receipt_id=receipt_id)

    @app.delete("/api/receipts/{receipt_id}", status_code=204, tags=["receipts"])
    def delete_receipt(receipt_id: int, db: PriceDB = Depends(get_db)) -> None:
        db.delete_receipt(receipt_id)

    @app.get("/api/line-items", response_model=list[m.LineItemOut], tags=["receipts"])
    def list_line_items(unmatched: bool = False, db: PriceDB = Depends(get_db)) -> list[dict]:
        return db.line_items(only_unmatched=unmatched)

    @app.patch("/api/line-items/{line_item_id}", response_model=m.LineItemOut, tags=["receipts"])
    def rematch(line_item_id: int, body: m.RematchIn, db: PriceDB = Depends(get_db)) -> dict:
        """Correct a saved line's product; its price observation is recomputed."""
        try:
            db.rematch_line_item(line_item_id, body.product, remember=body.remember)
        except KeyError as exc:
            raise HTTPException(422, str(exc)) from exc
        rows = [r for r in db.line_items() if r["id"] == line_item_id]
        if not rows:
            raise HTTPException(404, "Line item not found")
        return rows[0]

    # ----- aliases -----------------------------------------------------------------
    @app.get("/api/aliases", response_model=list[m.AliasOut], tags=["catalog"])
    def list_aliases(db: PriceDB = Depends(get_db)) -> list[dict]:
        return db.alias_rows()

    @app.put("/api/aliases", response_model=list[m.AliasOut], tags=["catalog"])
    def put_alias(body: m.AliasIn, db: PriceDB = Depends(get_db)) -> list[dict]:
        try:
            db.set_alias(body.raw_name, body.product, source="user")
        except KeyError as exc:
            raise HTTPException(422, str(exc)) from exc
        return db.alias_rows()

    @app.delete("/api/aliases/{alias}", status_code=204, tags=["catalog"])
    def delete_alias(alias: str, db: PriceDB = Depends(get_db)) -> None:
        db.delete_alias(alias)

    # ----- prices ------------------------------------------------------------------
    @app.get("/api/prices", response_model=m.PriceTable, tags=["prices"])
    def price_table(method: str = "weighted", db: PriceDB = Depends(get_db)) -> m.PriceTable:
        if method not in ("weighted", "latest"):
            raise HTTPException(422, "method must be 'weighted' or 'latest'")
        estimates = current_prices(db.observations(), method=method)
        rows = []
        for product in db.products():
            cells = {store: m.PriceCell(price=est.price, n_observations=est.n_observations,
                                        last_seen=est.last_seen)
                     for (prod, store), est in estimates.items() if prod == product.name}
            if not cells:
                continue
            cheapest = min(cells, key=lambda s: cells[s].price)
            rows.append(m.PriceRow(product=product.name, unit=product.unit,
                                   category=product.category, prices=cells,
                                   cheapest_store=cheapest))
        return m.PriceTable(method=method, stores=db.store_names(), rows=rows)

    @app.get("/api/prices/history", response_model=list[m.PricePoint], tags=["prices"])
    def price_history(product: str, db: PriceDB = Depends(get_db)) -> list[m.PricePoint]:
        return [m.PricePoint(store=o.store, date=o.observed_date, unit_price=round(o.unit_price, 4))
                for o in db.observations() if o.product == product]

    # ----- watchlist & price-drop alerts ------------------------------------------
    def _watch_rows(db: PriceDB) -> list[m.WatchOut]:
        observations = db.observations()
        watchlist = db.watchlist()
        units = {p.name: p.unit for p in db.products()}
        alerts = price_alerts(watchlist, observations)
        rows = []
        for product, target in watchlist.items():
            latest = {store: hist[-1].unit_price
                      for store, hist in latest_by_store(observations, product).items()}
            best_store = min(latest, key=latest.__getitem__) if latest else None
            rows.append(m.WatchOut(
                product=product, unit=units[product], target_price=target,
                best_price=round(latest[best_store], 4) if best_store else None,
                best_store=best_store,
                alerts=[m.AlertOut(**vars(a)) for a in alerts if a.product == product]))
        return rows

    @app.get("/api/watchlist", response_model=list[m.WatchOut], tags=["alerts"])
    def get_watchlist(db: PriceDB = Depends(get_db)) -> list[m.WatchOut]:
        return _watch_rows(db)

    @app.put("/api/watchlist", response_model=list[m.WatchOut], tags=["alerts"])
    def put_watch(body: m.WatchIn, db: PriceDB = Depends(get_db)) -> list[m.WatchOut]:
        """Watch a product, or change its target price."""
        try:
            db.set_watch(body.product, body.target_price)
        except KeyError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _watch_rows(db)

    @app.delete("/api/watchlist/{product}", status_code=204, tags=["alerts"])
    def delete_watch(product: str, db: PriceDB = Depends(get_db)) -> None:
        try:
            db.delete_watch(product)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/alerts", response_model=list[m.AlertOut], tags=["alerts"])
    def get_alerts(db: PriceDB = Depends(get_db)) -> list[m.AlertOut]:
        """Watched products whose latest price at some store is at or below the target."""
        return [m.AlertOut(**vars(a)) for a in price_alerts(db.watchlist(), db.observations())]

    # ----- spending insights ----------------------------------------------------------
    @app.get("/api/insights", response_model=m.Insights, tags=["insights"])
    def insights(trip_cost: float = 5.0, db: PriceDB = Depends(get_db)) -> m.Insights:
        """Spend by store/category/month, and what each past trip would have cost if planned."""
        if trip_cost < 0:
            raise HTTPException(422, "trip_cost must be >= 0")
        lines = db.line_items()
        categories = {p.name: p.category for p in db.products()}
        breakdown = spend_breakdown(lines, categories)
        with tracer.start_as_current_span("insights.replay_trips") as span:
            trips = replay_trips(lines, db.observations(), trip_cost)
            span.set_attribute("insights.trips", len(trips))
        actual = round(sum(t.actual for t in trips), 2)
        optimal = round(sum(t.optimal for t in trips), 2)
        saved = round(actual - optimal, 2)
        return m.Insights(
            total_spend=round(sum(li["line_total"] for li in lines), 2),
            receipts=len({li["receipt_id"] for li in lines}),
            **{key: [m.Amount(label=k, amount=v) for k, v in rows]
               for key, rows in breakdown.items()},
            trip_cost=trip_cost, actual_total=actual, optimal_total=optimal,
            estimated_savings=saved,
            estimated_savings_percent=round(100 * saved / actual, 1) if actual else 0.0,
            trips=[m.TripReplayOut(receipt_id=t.receipt_id, store=t.store, date=t.date,
                                   actual=t.actual, optimal=t.optimal, saved=t.saved,
                                   stores_in_plan=t.stores_in_plan) for t in trips],
        )

    # ----- recipe / free-text list assistant -------------------------------------------
    @app.post("/api/shopping-list/assist", response_model=m.AssistOut, tags=["plan"])
    def assist_list(body: m.AssistIn, request: Request,
                    db: PriceDB = Depends(get_db)) -> m.AssistOut:
        """Turn a recipe or free text into a draft shopping list of catalog products.
        Sync on purpose: the LLM calls block, so FastAPI runs this in a worker thread."""
        matcher = build_matcher(db)
        assistant = request.app.state.list_assistant(matcher.catalog, matcher)
        kind = type(assistant).__name__
        with tracer.start_as_current_span("list.assist") as span:
            span.set_attribute("assistant", kind)
            try:
                draft = assistant.build(body.text)
            except ListAssistantError as exc:
                metrics.LISTS_ASSISTED.labels(kind, "error").inc()
                logger.warning("list assist failed", extra={"assistant": kind, "error": str(exc)})
                raise HTTPException(422, str(exc)) from exc
            span.set_attribute("list.lines", len(draft.lines))
        metrics.LISTS_ASSISTED.labels(kind, "success").inc()
        logger.info("list assisted", extra={
            "assistant": kind, "lines": len(draft.lines),
            "unmatched": sum(line.product is None for line in draft.lines)})
        return m.AssistOut(source=draft.source, notes=draft.notes,
                           lines=[m.AssistLine(**vars(line)) for line in draft.lines])

    # ----- plan --------------------------------------------------------------------
    @app.post("/api/plan", response_model=m.PlanResult, tags=["plan"])
    def plan(body: m.PlanIn, db: PriceDB = Depends(get_db)) -> m.PlanResult:
        """Assign each item to a store to minimise item cost + trip cost (MILP)."""
        units = {p.name: p.unit for p in db.products()}
        items = [ListItem(i.product, i.quantity) for i in body.items]
        trip_cost: float | dict[str, float] = body.trip_cost
        stores = body.stores if body.stores is not None else db.store_names()
        if body.trip_costs:
            trip_cost = {s: body.trip_costs.get(s, body.trip_cost) for s in stores}
        start = time.perf_counter()
        with tracer.start_as_current_span("plan.optimize") as span:
            result = plan_trip(db, items, stores, trip_cost, body.max_stores, body.price_method)
            span.set_attribute("plan.items", len(items))
            span.set_attribute("plan.stores_considered", len(stores))
            span.set_attribute("plan.status", result.optimal.status)
            span.set_attribute("plan.stores_used", len(result.optimal.stores))
        seconds = time.perf_counter() - start
        metrics.OPTIMIZER_SECONDS.observe(seconds)
        logger.info("plan computed", extra={
            "items": len(items), "stores_used": len(result.optimal.stores),
            "status": result.optimal.status, "total": result.optimal.total,
            "solve_ms": round(seconds * 1000, 1)})
        quantities = {}
        for it in items:
            quantities[it.product] = quantities.get(it.product, 0.0) + it.quantity

        def to_out(plan_obj: Plan) -> m.PlanOut:
            stops = []
            for store, lines in plan_obj.by_store().items():
                plan_lines = [
                    m.PlanLine(product=p, quantity=quantities[p], unit=units.get(p, ""),
                               unit_price=round(cost / quantities[p], 4), cost=cost)
                    for p, cost in lines
                ]
                stops.append(m.StoreStop(store=store, trip_cost=plan_obj.trip_costs[store],
                                         items=plan_lines,
                                         subtotal=round(sum(pl.cost for pl in plan_lines), 2)))
            return m.PlanOut(name=plan_obj.name, status=plan_obj.status, total=plan_obj.total,
                             items_total=plan_obj.items_total, trips_total=plan_obj.trips_total,
                             stops=stops)

        savings = result.savings_vs_single_store()
        return m.PlanResult(
            optimal=to_out(result.optimal),
            single_store=to_out(result.single_store) if result.single_store else None,
            greedy=to_out(result.greedy),
            single_store_candidates=result.single_store_candidates,
            savings_vs_single_store=m.Savings(amount=savings[0], percent=savings[1]) if savings else None,
            unavailable=result.optimal.unavailable,
        )

    # ----- serve the built React app (production-style single process) -----------
    # The frontend is a Next.js static export: /upload is web/out/upload.html, assets
    # live under web/out/_next/. Anything unknown falls back to index.html.
    if FRONTEND_DIST.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            root = FRONTEND_DIST.resolve()
            for name in (path, f"{path}.html", f"{path}/index.html"):
                candidate = (FRONTEND_DIST / name).resolve()
                if path and candidate.is_file() and root in candidate.parents:
                    return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app

